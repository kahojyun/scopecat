from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from pydantic import BaseModel

from scopecat.daemon import (
    CollectionCommitCommand,
    CollectionCommitReceipt,
    CollectionResolveCommand,
    CollectionResolveReceipt,
    DaemonClient,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementAppendReceipt,
    MeasurementSealCommand,
    MeasurementSealReceipt,
    PayloadCommitCommand,
    PayloadCommitReceipt,
    RunAdmission,
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
    delegated_execution_services,
)
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.instrument import InstrumentReadback
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.parameter import Quantity
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.repository import (
    RunModelWrite,
    RunRecordSetWrite,
    TerminalRunCommit,
)
from tests.testkit.workflow_fixtures import load_config

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_delegated_execution_ports_round_trip_through_fenced_http_commands() -> None:
    submission = DelegatedRunSubmission(
        submission_id="submission-1",
        executor_id="notebook-1",
        config=load_config(),
        request=RunRequest(id="scratch-request"),
        plan=DelegatedPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    )
    admission = RunAdmission(
        run_id="run-1",
        submission_id=submission.submission_id,
        execution_mode="delegated",
        config_content_hash=submission.config_content_hash,
        accepted_at=_NOW,
        event_cursor=1,
    )
    record = _measurement()
    append = _measurement_append(record)
    seal = _measurement_seal(append)
    chunk = _collection_chunk()
    collection_receipt = CollectionChunkReceipt(
        operation_id=chunk.operation_id,
        ref="readbacks/operation-1.json",
        content_hash=chunk.content_hash,
    )
    transition = _transition()
    committed_transition = transition.model_copy(
        update={"sequence": 0, "timestamp": _NOW + timedelta(seconds=1)}
    )
    append_index = MeasurementDatasetAppendIndex.from_append(append)
    fences: list[tuple[str, str, int]] = []
    terminal_commands: list[TerminalRunCommitCommand] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/executor/start"):
            command = ExecutorStartRequest.model_validate_json(request.content)
            assert command.manifest.lifecycle == "running"
            return _model(_lease())
        if path.endswith("/transitions"):
            command = ExecutionTransitionBatch.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                ExecutionTransitionBatchReceipt(
                    batch_id=command.batch_id,
                    committed=(committed_transition,),
                )
            )
        if path.endswith("/measurements/append"):
            command = MeasurementAppendCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                MeasurementAppendReceipt(
                    command_id=command.command_id,
                    receipt=_measurement_receipt(command.append),
                )
            )
        if path.endswith("/measurements/seal"):
            command = MeasurementSealCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                MeasurementSealReceipt(
                    command_id=command.command_id,
                    receipt=_seal_receipt(command.seal),
                )
            )
        if path.endswith("/collections/commit"):
            command = CollectionCommitCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                CollectionCommitReceipt(
                    command_id=command.command_id,
                    receipt=collection_receipt,
                )
            )
        if path.endswith("/collections/resolve"):
            command = CollectionResolveCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            assert command.receipt == collection_receipt
            return _model(CollectionResolveReceipt(chunk=chunk))
        if path.endswith("/payloads/commit"):
            command = PayloadCommitCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                PayloadCommitReceipt(
                    command_id=command.command_id,
                    evidence=CommittedPayloadEvidence(
                        ref="payloads/operation-1.json",
                        content_hash=command.evidence.content_hash,
                    ),
                )
            )
        if path.endswith("/execution/recovery"):
            command = ExecutionRecoveryRequest.model_validate_json(request.content)
            _remember_fence(fences, command)
            return _model(
                ExecutionRecoverySnapshot(
                    transitions=(committed_transition,),
                    measurements=(record,),
                    measurement_append_indices=(append_index,),
                    collection_receipts=(collection_receipt,),
                )
            )
        if path.endswith("/terminal"):
            command = TerminalRunCommitCommand.model_validate_json(request.content)
            _remember_fence(fences, command)
            terminal_commands.append(command)
            return _model(
                TerminalRunCommitReceipt(
                    command_id=command.command_id,
                    manifest=command.manifest,
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    client = _client(handler)
    services = delegated_execution_services(client, submission, admission)
    accepted = services.runs.read_manifest(admission.run_id)
    running = accepted.model_copy(update={"lifecycle": "running"})
    services.runs.write_manifest(running)

    with services.resources.acquire((ResourceClaim(id="scope-1"),)):
        journal = services.journal_for(admission.run_id)
        measurements = services.measurements_for(admission.run_id)
        collections = services.collections_for(admission.run_id)
        payloads = services.payloads_for(admission.run_id)

        assert journal.append(transition) == committed_transition
        assert measurements.append(append) == _measurement_receipt(append)
        assert measurements.seal(seal) == _seal_receipt(seal)
        assert collections.commit(chunk) == collection_receipt
        assert collections.resolve(collection_receipt) == chunk
        assert payloads.commit(_payload()).content_hash == _payload().content_hash

    assert journal.entries() == (committed_transition,)
    assert measurements.measurements() == (record,)
    assert measurements.append_indices() == (append_index,)
    assert collections.receipts() == (collection_receipt,)

    outcome = _outcome()
    terminal = RunManifest(
        run_id=admission.run_id,
        created_at=accepted.created_at,
        lifecycle="terminal",
        config_content_hash=accepted.config_content_hash,
        outcome=outcome,
    )
    committed = services.runs.commit_terminal(
        TerminalRunCommit(
            manifest=terminal,
            models=(RunModelWrite(ref="run/outcome.json", value=outcome),),
            record_sets=(
                RunRecordSetWrite(
                    ref="measurements/raw.jsonl",
                    records=(record,),
                ),
            ),
        )
    )

    assert committed == terminal
    assert terminal_commands[0].models[0].value == outcome.model_dump(mode="json")
    assert terminal_commands[0].record_sets[0].records == (
        record.model_dump(mode="json"),
    )
    assert fences
    assert set(fences) == {("run-1", "lease-1", 7)}


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> DaemonClient:
    return DaemonClient(
        "http://daemon.local",
        transport=httpx.MockTransport(handler),
    )


class _Fenced(Protocol):
    run_id: str
    lease_id: str
    generation: int


def _remember_fence(
    fences: list[tuple[str, str, int]],
    command: _Fenced,
) -> None:
    fences.append((command.run_id, command.lease_id, command.generation))


def _model(model: BaseModel) -> httpx.Response:
    return httpx.Response(200, json=model.model_dump(mode="json"))


def _lease() -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
        generation=7,
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
        heartbeat_interval_seconds=10,
    )


def _transition() -> ExecutionTransition:
    return ExecutionTransition(
        run_id="run-1",
        operation_id="operation-1",
        stage="collect",
        effect="acquisition",
        state="completed",
    )


def _measurement() -> MeasurementRecord:
    return MeasurementRecord(
        run_id="run-1",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={"signal": Quantity(value=1.25, unit="ratio")},
    )


def _measurement_append(
    record: MeasurementRecord,
) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend(
        run_id="run-1",
        dataset_id="raw",
        recording_contract_fingerprint="contract-1",
        start_index=0,
        records=(record,),
    )


def _measurement_receipt(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=append.operation_id,
        dataset_content_hash=append.content_hash,
        dataset_ref="datasets/raw/chunks/0.json",
    )


def _measurement_seal(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
        dataset_id=append.dataset_id,
        recording_contract_fingerprint=append.recording_contract_fingerprint,
        point_count=1,
        dataset_content_hash=measurement_dataset_content_hash(
            recording_contract_fingerprint=append.recording_contract_fingerprint,
            append_content_hashes=(append.content_hash,),
        ),
    )


def _seal_receipt(
    seal: MeasurementDatasetSeal,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=seal.operation_id,
        dataset_content_hash=seal.dataset_content_hash,
        dataset_ref="datasets/raw/seal.json",
    )


def _collection_chunk() -> CollectionChunk:
    return CollectionChunk(
        run_id="run-1",
        operation_id="operation-1",
        command_content_hash="sha256:command",
        point_index=0,
        instrument_id="scope-1",
        readback=InstrumentReadback(
            values={"signal": Quantity(value=1.25, unit="ratio")}
        ),
    )


def _payload() -> PayloadEvidence:
    return PayloadEvidence(
        run_id="run-1",
        operation_id="operation-1",
        point_index=0,
        payload_id="payload-1",
        schema_id="schema-1",
        content_hash="sha256:payload",
        fingerprint={"kind": "test"},
    )


def _outcome() -> RunOutcome:
    return RunOutcome(
        run_id="run-1",
        result="succeeded",
        certainty="known",
        termination_reason="completed",
        finished_at=_NOW + timedelta(seconds=2),
    )
