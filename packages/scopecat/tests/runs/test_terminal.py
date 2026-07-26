"""Terminal manifest merge behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.execution.evidence import (
    build_terminal_contents,
    instrument_state_evidence_ref,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.artifact import RunContentEntry
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.run import RunManifest
from scopecat.runs.repository import (
    RunContentPublication,
    TerminalRunCommit,
)
from tests.testkit.runtime import sqlite_run_repository

_CONFIG_HASH = "sha256:" + "0" * 64


def test_run_manifest_is_an_immutable_snapshot() -> None:
    manifest = RunManifest(
        run_id="run-immutable",
        config_content_hash=_CONFIG_HASH,
    )

    assert manifest.records == ()
    assert manifest.datasets == ()
    assert manifest.artifacts == ()
    assert manifest.status == "planned"
    with pytest.raises(ValidationError):
        manifest.__setattr__("run_id", "changed")


def _successful_outcome(run_id: str) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
    )


def test_terminal_outcome_lives_only_in_the_manifest(tmp_path: Path) -> None:
    run_id = "run-domain"
    outcome = _successful_outcome(run_id)
    contents = build_terminal_contents(
        outcome=outcome,
        measurement_count=0,
        dataset_content_hash=None,
        dataset_schema=None,
        expected_record_count=None,
        instrument_state=None,
    )
    storage = sqlite_run_repository(tmp_path)
    accepted = RunManifest(
        run_id=run_id,
        config_content_hash=_CONFIG_HASH,
    )
    storage.write_manifest(accepted)

    committed = storage.commit_terminal(
        TerminalRunCommit(
            run_id=run_id,
            outcome=outcome,
            contents=contents,
        )
    )

    assert committed.records == ()
    assert committed.outcome == outcome
    assert committed.status == "completed"
    assert committed.created_at == accepted.created_at
    assert not storage.exists(run_id, instrument_state_evidence_ref())
    assert storage.read_manifest(run_id) == committed


def test_terminal_manifest_preserves_existing_attachments(tmp_path: Path) -> None:
    run_id = "run-existing-attachment"
    outcome = _successful_outcome(run_id)
    storage = sqlite_run_repository(tmp_path)
    storage.write_manifest(
        RunManifest(
            run_id=run_id,
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
        TerminalRunCommit(run_id=run_id, outcome=outcome)
    )

    assert committed.artifacts == (attachment,)
    assert workflow_record in committed.records
    assert storage.read_manifest(run_id) == committed


def test_terminal_contents_index_supplied_instrument_state() -> None:
    outcome = _successful_outcome("run-instrument")
    instrument_state = InstrumentStateEvidence(run_id=outcome.run_id)

    contents = build_terminal_contents(
        outcome=outcome,
        measurement_count=0,
        dataset_content_hash=None,
        dataset_schema=None,
        expected_record_count=None,
        instrument_state=instrument_state,
    )

    assert "instrument-state-evidence" in {
        entry.id for entry in contents if entry.role == "record"
    }
