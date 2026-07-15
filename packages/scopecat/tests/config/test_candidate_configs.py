from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat.composition.local import (
    local_config_registry_unit_of_work,
    local_run_repository,
    local_workspace_services,
)
from scopecat.config.candidates import materialize_candidate_config
from scopecat.config.changes import load_parameter_change_proposal
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.registry import list_config_registry_entries
from scopecat.config.resolution import register_and_activate_candidate_config
from scopecat.kernel.errors import CheckFailed, Conflict, DataIntegrityError
from scopecat.records.parameter import Quantity, ScalarParameterValue
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.refs import record_content_ref
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
    assert proposal.candidate_snapshot.get("drive_frequency") == updated
    assert proposal.deltas[0].after == updated


def test_candidate_checks_are_read_only_until_run_materializes_evidence(
    tmp_path: Path,
) -> None:
    lab = _lab(tmp_path)
    source_run = lab.prepare(load_invocation()).run()
    candidate = (
        source_run.analysis("read-only candidate")
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
    storage = local_run_repository(tmp_path)
    manifest_before = storage.read_manifest(source_run.id)
    refs_before = _run_ref_contents(tmp_path, source_run.id)

    def assert_source_run_unchanged() -> None:
        assert storage.read_manifest(source_run.id) == manifest_before
        assert _run_ref_contents(tmp_path, source_run.id) == refs_before

    assert lab.system(config=candidate)
    assert_source_run_unchanged()
    assert prepared.check().ok
    assert_source_run_unchanged()
    assert prepared.validate().ok
    assert_source_run_unchanged()
    assert prepared.preview().point_count == 3
    assert_source_run_unchanged()
    assert prepared.explain().startswith("experiment check: passed")
    assert_source_run_unchanged()

    follow_up = prepared.run()

    manifest_after = storage.read_manifest(source_run.id)
    materialized_records = [
        record
        for record in manifest_after.records
        if record.kind in {"parameter_change_proposal", "candidate_config"}
    ]
    refs_after = _run_ref_contents(tmp_path, source_run.id)
    assert follow_up.config.id.startswith("candidate-read-only-candidate-")
    assert manifest_after != manifest_before
    assert {record.kind for record in materialized_records} == {
        "parameter_change_proposal",
        "candidate_config",
    }
    for record in materialized_records:
        ref = record_content_ref(record_id=record.id, kind=record.kind)
        assert ref not in refs_before
        assert ref in refs_after


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
        materialize_candidate_config(
            analysis.candidate_config(("fit-a", "fit-b")),
            services=local_workspace_services(tmp_path),
        )

    assert error.value.problems[0].code == ("parameter_change_proposal_merge_invalid")
    assert "overlap" in error.value.problems[0].message


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
    local_run_repository(tmp_path).write_model(
        run.id,
        "config-profile.snapshot.json",
        stale_source,
    )

    with pytest.raises(DataIntegrityError) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            services=local_workspace_services(tmp_path),
            registered_by="operator",
            operator="operator",
        )

    assert error.value.problems[0].code == "run.config_provenance_mismatch"
    assert (
        list_config_registry_entries(
            unit_of_work=local_config_registry_unit_of_work(tmp_path)
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
        services=local_workspace_services(tmp_path),
    )

    assert restored == proposal
    assert persisted == proposal
    assert persisted.candidate_snapshot == proposal.candidate_snapshot
    assert persisted.deltas == proposal.deltas


def test_durable_proposal_copies_revalidate_all_invariants(tmp_path: Path) -> None:
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

    with pytest.raises(ValidationError):
        proposal.deltas[0].model_copy(update={"parameter_id": "other"})
    with pytest.raises(ValidationError):
        proposal.model_copy(update={"deltas": ()})


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
    materialize_candidate_config(
        rebuilt.candidate_config(),
        services=local_workspace_services(tmp_path),
    )
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
        services=local_workspace_services(tmp_path),
    )
    manifest = local_run_repository(tmp_path).read_manifest(run.id)
    assert persisted == first_proposal
    assert persisted.proposed_at == first_proposal.proposed_at
    assert [
        record.id
        for record in manifest.records
        if record.kind == "parameter_change_proposal"
    ] == [first_proposal.id]
    decision_info = lab.overview(run).parameter_change_proposals[0].decision_info
    assert decision_info.status == "reviewed"
    assert decision_info.decision == decision.decision
    assert [event.event_id for event in decision_info.history] == [decision.event_id]


def test_candidate_config_record_is_immutable(tmp_path: Path) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    candidate = (
        run.analysis("immutable candidate")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .candidate_config()
    )
    resolved = materialize_candidate_config(
        candidate, services=local_workspace_services(tmp_path)
    )
    storage = local_run_repository(tmp_path)
    storage.write_model(
        run.id,
        record_content_ref(
            record_id=resolved.candidate_config_record.id,
            kind=resolved.candidate_config_record.kind,
        ),
        resolved.config.model_copy(update={"id": "tampered"}),
    )

    with pytest.raises(Conflict) as error:
        materialize_candidate_config(
            candidate, services=local_workspace_services(tmp_path)
        )

    assert error.value.problems[0].code == "candidate_config_record_conflict"


def test_concurrent_candidate_materialization_is_idempotent(tmp_path: Path) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()
    candidate = (
        run.analysis("concurrent candidate")
        .propose(
            "drive-frequency",
            sc.replace_scalar_parameter(
                "drive_frequency",
                sc.Quantity(5.4, "GHz"),
            ),
        )
        .candidate_config()
    )
    barrier = Barrier(2)

    def resolve(_: int) -> str:
        barrier.wait()
        return materialize_candidate_config(
            candidate, services=local_workspace_services(tmp_path)
        ).config.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        resolved_ids = list(executor.map(resolve, (0, 1)))

    manifest = local_run_repository(tmp_path).read_manifest(run.id)
    proposal_records = [
        record
        for record in manifest.records
        if record.kind == "parameter_change_proposal"
    ]
    candidate_records = [
        record for record in manifest.records if record.kind == "candidate_config"
    ]
    assert resolved_ids[0] == resolved_ids[1]
    assert len(proposal_records) == 1
    assert len(candidate_records) == 1
    assert not list((tmp_path / "runs" / run.id).rglob("*.tmp"))


def _lab(tmp_path: Path) -> sc.Workspace:
    return sc.open(
        tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
        execution_backend=sc.ExecutionBackend(provider=TestSignalInstrumentProvider()),
    )


def _run_ref_contents(workspace: Path, run_id: str) -> dict[str, bytes]:
    run_dir = workspace / "runs" / run_id
    return {
        path.relative_to(run_dir).as_posix(): path.read_bytes()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
