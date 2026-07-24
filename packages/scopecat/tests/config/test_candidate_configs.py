from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_from_snapshot,
    resolve_candidate_config_snapshot,
)
from scopecat.config.changes import (
    list_parameter_change_decisions,
    load_parameter_change_proposal,
)
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.registry import list_config_registry_entries
from scopecat.config.resolution import register_and_activate_candidate_config
from scopecat.kernel.errors import CheckFailed, Conflict, DataIntegrityError
from scopecat.records.parameter import Quantity, ScalarParameterValue
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.testing import (
    sqlite_config_registry_unit_of_work,
    sqlite_project_services,
    sqlite_run_repository,
)
from tests.testkit.in_process_lab import InProcessLab, in_process_lab
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_invocation


def test_candidate_config_resolves_proposal_and_runs_follow_up(
    tmp_path: Path,
) -> None:
    lab = _lab(tmp_path)
    run = lab.prepare(load_invocation()).run()
    analysis = run.analysis("manual readout review").propose(
        "drive_frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.5, "GHz"),
        ),
        confidence=0.9,
    )
    analysis.save()
    candidate = analysis.candidate_config()

    follow_up = lab.prepare(load_invocation(), config=candidate).run()
    decision = lab.review_parameter_proposal(
        run,
        "drive_frequency",
        note="checked parameter proposal",
    )

    assert decision.decision == "approved"
    assert decision.proposal_id == "drive_frequency"
    assert candidate.proposal_ids == ("drive_frequency",)
    updated = follow_up.config.parameter_snapshot.get("drive_frequency")
    assert isinstance(updated, ScalarParameterValue)
    assert updated.value == Quantity(value=5.5, unit="GHz")
    proposal = analysis.parameter_proposals[0]
    assert proposal.deltas[0].after == updated


def test_unsaved_candidate_fails_closed_before_follow_up_run(
    tmp_path: Path,
) -> None:
    lab = _lab(tmp_path)
    source_run = lab.prepare(load_invocation()).run()
    candidate = (
        source_run.analysis("unsaved candidate")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .candidate_config()
    )
    prepared = lab.prepare(load_invocation(), config=candidate)

    check = prepared.check()
    assert not check.ok
    assert check.problems[0].code == "config.candidate_evidence_missing"
    with pytest.raises(CheckFailed) as error:
        prepared.run()
    assert error.value.problems[0].code == "config.candidate_evidence_missing"


def test_candidate_checks_and_run_leave_source_run_unchanged(
    tmp_path: Path,
) -> None:
    lab = _lab(tmp_path)
    source_run = lab.prepare(load_invocation()).run()
    analysis = source_run.analysis("read-only candidate").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.4, "GHz"),
        ),
    )
    analysis.save()
    candidate = analysis.candidate_config()
    prepared = lab.prepare(load_invocation(), config=candidate)
    storage = sqlite_run_repository(tmp_path)
    manifest_before = storage.read_manifest(source_run.id)
    refs_before = _run_ref_contents(tmp_path, source_run.id)

    def assert_source_run_unchanged() -> None:
        assert storage.read_manifest(source_run.id) == manifest_before
        assert _run_ref_contents(tmp_path, source_run.id) == refs_before

    assert lab.resolve_config(config=candidate).id == "candidate-drive-frequency"
    assert_source_run_unchanged()
    assert prepared.check().ok
    assert_source_run_unchanged()
    assert_source_run_unchanged()
    assert prepared.preview().point_count == 3
    assert_source_run_unchanged()
    follow_up = prepared.run()

    assert follow_up.config.id == "candidate-drive-frequency"
    assert_source_run_unchanged()


@pytest.mark.parametrize(
    "update",
    [
        sc.replace_scalar_parameter(
            "missing_frequency",
            sc.Quantity(4.9, "GHz"),
        ),
        sc.replace_series_parameter(
            "drive_frequency",
            [sc.Quantity(4.9, "GHz")],
        ),
        sc.replace_scalar_parameter("drive_frequency", True),
    ],
)
def test_analysis_rejects_invalid_update_at_propose(
    tmp_path: Path,
    update: ParameterUpdate,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()

    with pytest.raises(CheckFailed) as error:
        run.analysis("invalid proposal").propose("invalid", update)

    assert error.value.problems[0].code == "analysis_parameter_proposal_invalid"


def test_candidate_config_rejects_overlapping_proposals(tmp_path: Path) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    analysis = (
        run.analysis("competing fits")
        .propose(
            "fit-a",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .propose(
            "fit-b",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.5, "GHz"),
            ),
        )
    )

    with pytest.raises(CheckFailed) as error:
        resolve_candidate_config_snapshot(
            analysis.candidate_config(("fit-a", "fit-b")),
            services=sqlite_project_services(tmp_path),
        )

    assert error.value.problems[0].code == ("parameter_change_proposal_merge_invalid")
    assert "overlap" in error.value.problems[0].message


def test_candidate_config_from_snapshot_rejects_stale_base_hash(
    tmp_path: Path,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    candidate = (
        run.analysis("stale hash")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .candidate_config()
    )
    changed_source = run.config.model_copy(
        update={
            "environment": run.config.environment.model_copy(
                update={"id": "changed-environment"}
            )
        }
    )

    with pytest.raises(Conflict) as error:
        resolve_candidate_config_from_snapshot(
            candidate,
            source_config=changed_source,
        )

    assert error.value.problems[0].code == ("parameter_change_proposal_base_mismatch")


def test_candidate_config_from_snapshot_rejects_stale_base_id(
    tmp_path: Path,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    proposal = (
        run.analysis("stale id")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .parameter_proposals[0]
    )
    candidate = CandidateConfig(
        parameter_proposals=(
            proposal.model_copy(update={"base_config_id": "different-config"}),
        )
    )

    with pytest.raises(Conflict) as error:
        resolve_candidate_config_from_snapshot(
            candidate,
            source_config=run.config,
        )

    assert error.value.problems[0].code == (
        "parameter_change_proposal_base_id_mismatch"
    )


def test_candidate_config_from_snapshot_validates_proposal_merge(
    tmp_path: Path,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    analysis = (
        run.analysis("competing fits")
        .propose(
            "fit-a",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .propose(
            "fit-b",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.5, "GHz"),
            ),
        )
    )

    with pytest.raises(CheckFailed) as error:
        resolve_candidate_config_from_snapshot(
            analysis.candidate_config(("fit-a", "fit-b")),
            source_config=run.config,
        )

    assert error.value.problems[0].code == ("parameter_change_proposal_merge_invalid")


def test_candidate_config_rejects_drifted_source_snapshot_before_registration(
    tmp_path: Path,
) -> None:
    lab = _lab(tmp_path)
    run = lab.prepare(load_invocation()).run()
    candidate = (
        run.analysis("stale fit")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .candidate_config()
    )
    stale_source = run.config.model_copy(update={"id": "changed-after-fit"})
    sqlite_run_repository(tmp_path).write_model(
        run.id,
        "config-profile.snapshot.json",
        stale_source,
    )

    with pytest.raises(DataIntegrityError) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            services=sqlite_project_services(tmp_path),
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "run.config_provenance_mismatch"
    assert (
        list_config_registry_entries(
            unit_of_work=sqlite_config_registry_unit_of_work(tmp_path)
        )
        == []
    )


def test_parameter_change_proposal_round_trips_and_is_persisted(
    tmp_path: Path,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    analysis = run.analysis("round trip fit").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.4, "GHz"),
        ),
        reason="fit converged",
        confidence=0.8,
    )
    proposal = analysis.parameter_proposals[0]

    restored = ParameterChangeProposal.model_validate_json(proposal.model_dump_json())
    analysis.save()
    persisted = load_parameter_change_proposal(
        run_id=run.id,
        selector=proposal.id,
        services=sqlite_project_services(tmp_path),
    )

    assert restored == proposal
    assert persisted == proposal
    assert persisted.schema_version == "scopecat.parameter_change_proposal.v3"
    assert persisted.deltas == proposal.deltas


def test_durable_proposal_validation_rejects_invalid_invariants(
    tmp_path: Path,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    proposal = (
        run.analysis("validated copy")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .parameter_proposals[0]
    )

    delta_data = proposal.deltas[0].model_dump(mode="python")
    delta_data["parameter_id"] = "other"
    with pytest.raises(ValidationError):
        type(proposal.deltas[0]).model_validate(delta_data)

    proposal_data = proposal.model_dump(mode="python")
    proposal_data["deltas"] = ()
    with pytest.raises(ValidationError):
        ParameterChangeProposal.model_validate(proposal_data)


def test_proposal_records_are_immutable_but_idempotent(tmp_path: Path) -> None:
    lab = _lab(tmp_path)
    run = lab.prepare(load_invocation()).run()
    first = run.analysis("first fit").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.4, "GHz"),
        ),
        reason="first fit",
    )
    first.save()
    first.save()
    first_proposal = first.parameter_proposals[0]
    decision = lab.review_parameter_proposal(
        run,
        first_proposal.id,
        decision="rejected",
        note="review history must survive an idempotent analysis-cell retry",
    )
    rebuilt = run.analysis("first fit").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.4, "GHz"),
        ),
        reason="first fit",
    )
    rebuilt_proposal = rebuilt.parameter_proposals[0]
    assert rebuilt_proposal.proposed_at != first_proposal.proposed_at
    rebuilt.save()
    second = run.analysis("second fit").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.5, "GHz"),
        ),
        reason="second fit",
    )

    with pytest.raises(Conflict) as error:
        second.save()

    assert error.value.problems[0].code == "parameter_change_proposal_conflict"
    persisted = load_parameter_change_proposal(
        run_id=run.id,
        selector="drive-frequency",
        services=sqlite_project_services(tmp_path),
    )
    manifest = sqlite_run_repository(tmp_path).read_manifest(run.id)
    assert persisted == first_proposal
    assert persisted.proposed_at == first_proposal.proposed_at
    assert [
        record.id
        for record in manifest.records
        if record.kind == "parameter_change_proposal"
    ] == [first_proposal.id]
    decisions = list_parameter_change_decisions(
        run_id=run.id,
        selector=first_proposal.id,
        storage=sqlite_run_repository(tmp_path),
    )
    assert [event.decision for event in decisions] == [decision.decision]
    assert [event.event_id for event in decisions] == [decision.event_id]


def _lab(tmp_path: Path) -> InProcessLab:
    return in_process_lab(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
    )


def _run_ref_contents(project_root: Path, run_id: str) -> dict[str, str]:
    repository = sqlite_run_repository(project_root)
    with sqlite3.connect(repository.database) as connection:
        return dict(
            connection.execute(
                """
                SELECT ref, digest
                FROM run_repository_refs
                WHERE run_id = ?
                ORDER BY ref
                """,
                (run_id,),
            )
        )
