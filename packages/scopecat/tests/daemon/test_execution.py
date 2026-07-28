from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx2
import pytest
from pydantic import BaseModel

from scopecat.control.models import RunPlanSummary
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.execution import daemon_execution_session
from scopecat.daemon.wire import (
    ExecutionTransitionAppend,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementSealCommand,
    RunAdmission,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.execution.ports.instruments import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.repository import TerminalRunCommit
from tests.testkit.workflow_fixtures import load_config

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_daemon_execution_ports_round_trip_through_fenced_http_commands() -> None:
    submission = RunSubmission(
        submission_id="submission-1",
        config=load_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    )
    admission = RunAdmission(
        submission_id=submission.submission_id,
        manifest=RunManifest(
            run_id="run-1",
            created_at=_NOW,
            config_content_hash=config_content_hash(submission.config),
        ),
    )
    record = _measurement()
    append = _measurement_append(record)
    seal = _measurement_seal(append)
    transition = _transition()
    committed_transition = transition.model_copy(
        update={"sequence": 0, "timestamp": _NOW + timedelta(seconds=1)}
    )
    started_manifest = admission.manifest
    fences: list[tuple[str, str]] = []
    transition_commands: list[ExecutionTransitionAppend] = []
    terminal_commands: list[TerminalRunCommitCommand] = []
    hardware_operation_ids: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path.endswith("/executor/start"):
            command = ExecutorStartRequest.model_validate_json(request.content)
            assert command.executor_id == "notebook-1"
            return _model(_lease())
        if path.endswith("/instruments/provision"):
            command = RunInstrumentProvisionCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(
                RunInstrumentProvisionReceipt(
                    run_id="run-1",
                    operation_id=command.operation_id,
                    status="ready",
                )
            )
        if path.endswith("/hardware/execute"):
            command = RunHardwareBatchCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            hardware_operation_ids.append(command.batch.operation_id)
            return _model(
                RunHardwareBatchReceipt(operation_id=command.batch.operation_id)
            )
        if path.endswith("/hardware/finish"):
            command = RunHardwareFinishCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            hardware_operation_ids.append(command.operation_id)
            return _model(
                RunHardwareFinalizationReceipt(
                    operation_id=command.operation_id,
                )
            )
        if path.endswith("/transitions"):
            command = ExecutionTransitionAppend.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            transition_commands.append(command)
            return _model(committed_transition)
        if path.endswith("/measurements/append"):
            command = MeasurementAppendCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(_measurement_receipt(command.append))
        if path.endswith("/measurements/seal"):
            command = MeasurementSealCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(_seal_receipt(command.seal))
        if path.endswith("/terminal"):
            command = TerminalRunCommitCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            terminal_commands.append(command)
            return _model(
                started_manifest.model_copy(
                    update={
                        "outcome": command.outcome,
                        "contents": command.contents,
                    }
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    client = _client(handler)
    session = daemon_execution_session(
        client,
        submission,
        admission,
        executor_id="notebook-1",
    )
    accepted = session.accepted
    assert session.begin() is None

    journal = session.journal
    measurements = session.measurements
    instruments = session.instruments

    batch = RunHardwareBatch(
        operation_id="hardware.batch-1",
        actions=(
            RunHardwareApply(
                effect_id="point-0.apply.source-0",
                point_index=0,
                instrument_id="source-0",
                fields=(),
            ),
        ),
    )
    assert instruments.execute(batch).operation_id == batch.operation_id
    assert (
        instruments.finish(operation_id="hardware.finish", failed=False).operation_id
        == "hardware.finish"
    )

    assert journal.append(transition) == committed_transition
    assert (
        journal.append(
            transition.model_copy(
                update={"timestamp": transition.timestamp + timedelta(seconds=1)}
            )
        )
        == committed_transition
    )
    assert len(transition_commands) == 2
    assert {
        execution_transition_content_hash(command.transition)
        for command in transition_commands
    } == {execution_transition_content_hash(transition)}
    assert measurements.append(append) == _measurement_receipt(append)
    assert measurements.seal(seal) == _seal_receipt(seal)

    outcome = _outcome()
    terminal = RunManifest(
        run_id=admission.run_id,
        created_at=accepted.created_at,
        config_content_hash=accepted.config_content_hash,
        outcome=outcome,
    )
    committed = session.commit_terminal(
        TerminalRunCommit(
            run_id=admission.run_id,
            outcome=outcome,
        )
    )

    assert committed == terminal
    assert terminal_commands[0].outcome == outcome
    assert terminal_commands[0].contents == ()
    assert terminal_commands[0].models == ()
    assert fences
    assert set(fences) == {("run-1", "lease-1")}
    assert hardware_operation_ids == [
        "hardware.batch-1",
        "hardware.finish",
    ]


def test_daemon_execution_rejects_provision_receipt_for_another_operation() -> None:
    submission = RunSubmission(
        submission_id="submission-1",
        config=load_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    )
    admission = RunAdmission(
        submission_id=submission.submission_id,
        manifest=RunManifest(
            run_id="run-1",
            created_at=_NOW,
            config_content_hash=config_content_hash(submission.config),
        ),
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/executor/start"):
            return _model(_lease())
        if request.url.path.endswith("/instruments/provision"):
            return _model(
                RunInstrumentProvisionReceipt(
                    run_id="run-1",
                    operation_id="another-operation",
                    status="ready",
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    session = daemon_execution_session(
        _client(handler),
        submission,
        admission,
        executor_id="notebook-1",
    )

    with pytest.raises(ValueError, match="does not match command"):
        session.begin()


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> DaemonClient:
    return DaemonClient(
        "http://daemon.local",
        transport=httpx2.MockTransport(handler),
    )


class _Fenced(Protocol):
    lease_id: str


def _remember_fence(
    fences: list[tuple[str, str]],
    run_id: str,
    command: _Fenced,
) -> None:
    fences.append((run_id, command.lease_id))


def _model(model: BaseModel) -> httpx2.Response:
    return httpx2.Response(200, json=model.model_dump(mode="json"))


def _lease() -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
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
    )


def _measurement_seal(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
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
    )


def _outcome() -> RunOutcome:
    return RunOutcome(
        run_id="run-1",
        result="succeeded",
        certainty="known",
        finished_at=_NOW + timedelta(seconds=2),
    )
