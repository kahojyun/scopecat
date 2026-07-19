from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from pydantic import BaseModel, ValidationError

from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.execution.evidence import (
    build_execution_manifest,
    instrument_state_evidence_ref,
    run_outcome_ref,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.manifest import write_manifest_artifacts, write_manifest_records
from scopecat.runs.repository import RunModelWrite, TerminalRunCommit

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
        measurements=[],
        expected_schema=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=None,
    )
    storage = FilesystemRunRepository(tmp_path)
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


def test_terminal_manifest_preserves_a_concurrent_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run-concurrent-attachment"
    outcome = _successful_outcome(run_id)
    terminal = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurements=[],
        expected_schema=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=None,
    )
    storage = FilesystemRunRepository(tmp_path)
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
    terminal_content_ready = Event()
    attachment_committed = Event()
    original_write_model = storage.write_model

    def synchronized_write_model(
        selected_run_id: str,
        ref: str,
        model: BaseModel,
    ) -> None:
        original_write_model(selected_run_id, ref, model)
        if selected_run_id == run_id and ref == run_outcome_ref():
            terminal_content_ready.set()
            if not attachment_committed.wait(timeout=5):
                raise TimeoutError("concurrent attachment did not commit")

    monkeypatch.setattr(storage, "write_model", synchronized_write_model)

    def attach() -> None:
        if not terminal_content_ready.wait(timeout=5):
            raise TimeoutError("terminal content was not ready")
        try:
            write_manifest_artifacts(
                storage=storage,
                manifest=storage.read_manifest(run_id),
                artifacts=[attachment],
            )
            write_manifest_records(
                storage=storage,
                manifest=storage.read_manifest(run_id),
                records=[workflow_record],
            )
        finally:
            attachment_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        attachment_future = executor.submit(attach)
        terminal_future = executor.submit(
            storage.commit_terminal,
            TerminalRunCommit(
                manifest=terminal,
                models=(RunModelWrite(ref=run_outcome_ref(), value=outcome),),
            ),
        )
        committed = terminal_future.result(timeout=10)
        attachment_future.result(timeout=10)

    assert committed.artifacts == (attachment,)
    assert workflow_record in committed.records
    assert storage.read_manifest(run_id) == committed


def test_execution_manifest_indexes_supplied_instrument_state() -> None:
    outcome = _successful_outcome("run-instrument")
    instrument_state = InstrumentStateEvidence(run_id=outcome.run_id)

    manifest = build_execution_manifest(
        run_id=outcome.run_id,
        outcome=outcome,
        measurements=[],
        expected_schema=None,
        config_content_hash=_CONFIG_HASH,
        config_source=None,
        instrument_state=instrument_state,
    )

    assert "instrument-state-evidence" in {record.id for record in manifest.records}
