from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat._storage.refs import record_content_ref
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import resolve_candidate_config
from scopecat.config_registry import list_config_registry_entries
from scopecat.errors import ValidationFailed
from scopecat.models.parameter import Quantity, ScalarParameterValue
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.parameter_changes import load_parameter_change_proposal
from scopecat.runs import open_run_store
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_invocation

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


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


@pytest.mark.parametrize(
    "update",
    [
        object(),
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
def test_analysis_rejects_unknown_or_wrong_typed_update_at_propose(
    tmp_path: Path,
    update: object,
) -> None:
    run = _lab(tmp_path).prepare(load_invocation()).run()

    with pytest.raises(ValidationFailed) as error:
        run.analysis("invalid proposal").propose(
            "invalid",
            update,  # type: ignore[arg-type]
        )

    assert error.value.diagnostics[0].code == "analysis_parameter_proposal_invalid"


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

    with pytest.raises(ValidationFailed) as error:
        resolve_candidate_config(
            analysis.candidate_config(("fit-a", "fit-b")),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == (
        "parameter_change_proposal_merge_invalid"
    )
    assert "overlap" in error.value.diagnostics[0].message


def test_candidate_config_rejects_stale_base_hash_before_registration(
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
    stale_source = run.config.model_copy(
        update={"metadata": {"config_revision": "changed-after-fit"}},
    )
    open_run_store(tmp_path).write_model(
        run.id,
        "config-profile.snapshot.json",
        stale_source,
    )

    with pytest.raises(ValidationFailed) as error:
        register_and_activate_candidate_config(
            candidate=candidate,
            workspace=tmp_path,
            registered_by="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == (
        "parameter_change_proposal_base_mismatch"
    )
    assert list_config_registry_entries(workspace=tmp_path) == []


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
        workspace=tmp_path,
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
    run = _lab(tmp_path).prepare(load_invocation()).run()
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
    second = run.analysis("second fit").propose(
        "drive-frequency",
        sc.replace_scalar_parameter(
            "drive_frequency",
            sc.Quantity(5.5, "GHz"),
        ),
        reason="second fit",
    )

    with pytest.raises(ValidationFailed) as error:
        second.save()

    assert error.value.diagnostics[0].code == "parameter_change_proposal_conflict"
    persisted = load_parameter_change_proposal(
        run_id=run.id,
        selector="drive-frequency",
        workspace=tmp_path,
    )
    assert persisted == first.parameter_proposals[0]


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
    resolved = resolve_candidate_config(candidate, workspace=tmp_path)
    storage = open_run_store(tmp_path)
    storage.write_model(
        run.id,
        record_content_ref(
            record_id=resolved.candidate_config_record.id,
            kind=resolved.candidate_config_record.kind,
        ),
        resolved.config.model_copy(update={"metadata": {"tampered": True}}),
    )

    with pytest.raises(ValidationFailed) as error:
        resolve_candidate_config(candidate, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "candidate_config_record_conflict"


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
        return resolve_candidate_config(candidate, workspace=tmp_path).config.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        resolved_ids = list(executor.map(resolve, (0, 1)))

    manifest = open_run_store(tmp_path).read_manifest(run.id)
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
        instrument_provider=TestSignalInstrumentProvider(),
    )
