from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.composition.embedded import embedded_run_repository
from scopecat.execution.evidence import (
    build_execution_manifest,
    instrument_state_evidence_ref,
    run_outcome_ref,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.repository import (
    RunContentPublication,
    RunModelWrite,
    TerminalRunCommit,
)

_CONFIG_HASH = "sha256:" + "0" * 64


def test_run_manifest_is_an_immutable_snapshot() -> None:
    manifest = RunManifest(
        run_id="run-immutable",
        lifecycle="accepted",
        config_content_hash=_CONFIG_HASH,
    )

    assert manifest.records == ()
    assert manifest.datasets == ()
    assert manifest.artifacts == ()
    with pytest.raises(ValidationError):
        manifest.__setattr__("lifecycle", "running")


def _successful_outcome(run_id: str) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
        termination_reason="completed",
    )


def test_terminal_evidence_can_omit_instrument_state(tmp_path: Path) -> None:
    run_id = "run-domain"
    outcome = _successful_outcome(run_id)
    manifest = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurement_count=0,
        dataset_content_hash=None,
        dataset_schema=None,
        expected_record_count=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=None,
    )
    storage = embedded_run_repository(tmp_path)
    storage.write_manifest(
        RunManifest(
            run_id=run_id,
            created_at=manifest.created_at,
            lifecycle="running",
            config_content_hash=_CONFIG_HASH,
        )
    )

    committed = storage.commit_terminal(
        TerminalRunCommit(
            manifest=manifest,
            models=(RunModelWrite(ref=run_outcome_ref(), value=outcome),),
        )
    )

    assert {record.id for record in manifest.records} == {"run-outcome"}
    assert storage.exists(run_id, run_outcome_ref())
    assert not storage.exists(run_id, instrument_state_evidence_ref())
    assert committed == manifest
    assert storage.read_manifest(run_id) == committed


def test_terminal_manifest_preserves_existing_attachments(tmp_path: Path) -> None:
    run_id = "run-existing-attachment"
    outcome = _successful_outcome(run_id)
    terminal = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurement_count=0,
        dataset_content_hash=None,
        dataset_schema=None,
        expected_record_count=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=None,
    )
    storage = embedded_run_repository(tmp_path)
    storage.write_manifest(
        RunManifest(
            run_id=run_id,
            created_at=terminal.created_at,
            lifecycle="running",
            config_content_hash=_CONFIG_HASH,
        )
    )
    attachment = RunContentEntry(
        role="artifact",
        id="operator-note",
        kind="attachment",
        content_hash="operator-note-content",
        media_type="text/plain",
    )
    workflow_record = RunContentEntry(
        role="record",
        id="approval",
        kind="workflow_decision",
        content_hash="approval-content",
    )
    storage.publish_content(
        RunContentPublication(
            run_id=run_id,
            entries=(attachment, workflow_record),
        )
    )
    committed = storage.commit_terminal(
        TerminalRunCommit(
            manifest=terminal,
            models=(RunModelWrite(ref=run_outcome_ref(), value=outcome),),
        )
    )

    assert committed.artifacts == (attachment,)
    assert workflow_record in committed.records
    assert storage.read_manifest(run_id) == committed


def test_execution_manifest_indexes_supplied_instrument_state() -> None:
    outcome = _successful_outcome("run-instrument")
    instrument_state = InstrumentStateEvidence(run_id=outcome.run_id)

    manifest = build_execution_manifest(
        run_id=outcome.run_id,
        outcome=outcome,
        measurement_count=0,
        dataset_content_hash=None,
        dataset_schema=None,
        expected_record_count=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=instrument_state,
    )

    assert "instrument-state-evidence" in {record.id for record in manifest.records}
