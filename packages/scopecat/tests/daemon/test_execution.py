from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx2
import pytest
from pydantic import BaseModel
from scopecat_testkit.workflow_fixtures import load_config

import scopecat.daemon.execution as daemon_execution
from scopecat.control.models import RunPlanSummary
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.execution import daemon_execution_session
from scopecat.daemon.points import (
    AcceptedRunPointView,
    RunPointDecisionCommand,
    RunPointDecisionView,
    RunPointPlanCloseCommand,
    RunPointPlanView,
    RunPointQueueView,
)
from scopecat.daemon.reviews import (
    RunInspectionAppendCommand,
    RunInspectionView,
)
from scopecat.daemon.wire import (
    ExecutionTransitionAppend,
    ExecutionTransitionClaim,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementFlushCommand,
    MeasurementFlushReceipt,
    MeasurementHeaderCommand,
    MeasurementIngestReceipt,
    MeasurementSealCommand,
    RunAdmission,
    RunCoverageAdvanceCommand,
    RunCoverageState,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.kernel.state import StateValue
from scopecat.measurements.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.measurements.recording_arrow import decode_measurement_append
from scopecat.optimization import PointProposalDecision
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
)
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.commands import InstrumentStateAssignment
from scopecat.sdk.instruments.execution import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
)

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_daemon_execution_ports_round_trip_through_fenced_http_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(daemon_execution, "monotonic", lambda: 1.0)
    submission = RunSubmission(
        submission_id="submission-1",
        config=load_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=None,
            initial_point_count=1,
            point_limit=3,
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
    header = _measurement_header()
    append = _measurement_append(record, header)
    seal = _measurement_seal(append, header)
    transition = _transition()
    committed_transition = transition.model_copy(
        update={"sequence": 0, "timestamp": _NOW + timedelta(seconds=1)}
    )
    started_manifest = admission.manifest
    fences: list[tuple[str, str]] = []
    transition_commands: list[ExecutionTransitionAppend | ExecutionTransitionClaim] = []
    terminal_commands: list[TerminalRunCommitCommand] = []
    hardware_operation_ids: list[str] = []
    hardware_sequences: list[int] = []
    coverage_ranges: list[tuple[int, int]] = []
    measurement_ingest_ranges: list[tuple[int, int]] = []
    inspection_commands: list[RunInspectionAppendCommand] = []

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
                    instrument_ids=("source-0",),
                    observed_state=(InstrumentStateSnapshot(instrument_id="source-0"),),
                    baseline_state=(InstrumentStateSnapshot(instrument_id="source-0"),),
                )
            )
        if path.endswith("/hardware/execute"):
            command = RunHardwareBatchCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            hardware_operation_ids.append(command.batch.operation_id)
            hardware_sequences.append(command.sequence)
            return _model(
                RunHardwareBatchReceipt(operation_id=command.batch.operation_id)
            )
        if path.endswith("/coverage/advance"):
            command = RunCoverageAdvanceCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            coverage_ranges.append((command.start_index, command.point_count))
            return _model(
                RunCoverageState(
                    run_id="run-1",
                    completed_point_count=command.start_index + command.point_count,
                )
            )
        if path.endswith("/point-plan/queue/next") and request.method == "GET":
            return _model(RunPointQueueView(run_id="run-1"))
        if path.endswith("/point-plan/decisions"):
            command = RunPointDecisionCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            accepted_point = AcceptedRunPointView(
                point_index=1,
                coordinates=command.proposal.coordinates,
                proposal_fingerprint=command.proposal.proposal_fingerprint,
                source=command.proposal.source,
            )
            return _model(
                RunPointDecisionView(
                    operation_id=command.operation_id,
                    proposal_index=0,
                    occurred_at=_NOW,
                    proposal=command.proposal,
                    outcome="accepted",
                    accepted_point=accepted_point,
                )
            )
        if path.endswith("/point-plan/close"):
            command = RunPointPlanCloseCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(
                RunPointPlanView(
                    run_id="run-1",
                    initial_point_count=1,
                    accepted_point_count=2,
                    point_limit=3,
                    decision_count=1,
                    optimizer_attempt_count=1,
                    operator_request_count=0,
                    plan_closed=True,
                    stop_reason=command.reason,
                )
            )
        if path.endswith("/inspections"):
            command = RunInspectionAppendCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            inspection_commands.append(command)
            return _model(RunInspectionView(run_id="run-1", items=(command.event,)))
        if path.endswith("/hardware/finish"):
            command = RunHardwareFinishCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            hardware_operation_ids.append(command.operation_id)
            return _model(
                RunHardwareFinalizationReceipt(
                    operation_id=command.operation_id,
                )
            )
        if path.endswith("/transitions/claim"):
            command = ExecutionTransitionClaim.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            transition_commands.append(command)
            return _model(committed_transition)
        if path.endswith("/transitions"):
            command = ExecutionTransitionAppend.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            transition_commands.append(command)
            return _model(committed_transition)
        if path.endswith("/measurements/ingest"):
            assert request.headers["content-type"] == (
                "application/vnd.apache.arrow.file"
            )
            fences.append(("run-1", request.headers["x-scopecat-lease-id"]))
            decoded = decode_measurement_append(
                request.content,
                header.dataset_schema,
            )
            measurement_ingest_ranges.append(
                (decoded.start_index, len(decoded.records))
            )
            return _model(
                MeasurementIngestReceipt(
                    run_id="run-1",
                    received_record_count=1,
                    durable_record_count=0,
                )
            )
        if path.endswith("/measurements/flush"):
            command = MeasurementFlushCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(
                MeasurementFlushReceipt(
                    run_id="run-1",
                    durable_record_count=1,
                    durable_receipts=(_measurement_receipt(append),),
                )
            )
        if path.endswith("/measurements/header"):
            command = MeasurementHeaderCommand.model_validate_json(request.content)
            _remember_fence(fences, "run-1", command)
            return _model(_header_receipt(command.header))
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
    coverage = session.coverage
    point_proposals = session.point_proposals
    assert coverage is not None
    assert point_proposals is not None
    assert instruments.observed_state == (
        InstrumentStateSnapshot(instrument_id="source-0"),
    )
    assert instruments.baseline_state == (
        InstrumentStateSnapshot(instrument_id="source-0"),
    )
    assert point_proposals.next_queued() is None

    batch = RunHardwareBatch(
        operation_id="hardware.batch-1",
        actions=(
            RunHardwareApply(
                effect_id="point-0.apply.source-0",
                point_index=0,
                instrument_id="source-0",
                assignments=(
                    InstrumentStateAssignment(
                        resource_id="source-0",
                        interface_id="test.set_frequency/v1",
                        property_id="frequency",
                        value=StateValue(Quantity(5.0, "GHz")),
                    ),
                ),
            ),
        ),
    )
    assert instruments.execute(batch).operation_id == batch.operation_id
    coverage.advance(start_index=0, point_count=1)
    coverage.advance(start_index=1, point_count=2)
    coverage.flush()
    candidate = PointProposalAttempt(
        {"frequency": Quantity(5.2, "GHz")},
        source="optimizer",
        based_on_completed_point_count=1,
    )
    accepted_point = AcceptedRunPoint.accept(
        candidate,
        logical_id=LogicalPointId(PointDomainId("scratch", "points"), 1),
    )
    point_proposals.append(
        PointProposalDecision(
            proposal_index=0,
            candidate=candidate,
            outcome="accepted",
            accepted_point=accepted_point,
        ),
        None,
    )
    point_proposals.close(completed_point_count=2, reason="test complete")
    assert (
        instruments.finish(operation_id="hardware.finish", failed=False).operation_id
        == "hardware.finish"
    )

    assert journal.claim(transition) == committed_transition
    assert journal.append(transition) == committed_transition
    assert (
        journal.append(
            transition.model_copy(
                update={"timestamp": transition.timestamp + timedelta(seconds=1)}
            )
        )
        == committed_transition
    )
    assert len(transition_commands) == 3
    assert {
        execution_transition_content_hash(command.transition)
        for command in transition_commands
    } == {execution_transition_content_hash(transition)}
    assert measurements.initialize(header) == _header_receipt(header)
    assert measurements.ingest(append) == ()
    second = append.model_copy(
        update={
            "start_index": 1,
            "records": (
                record.model_copy(
                    update={"logical_point_id": "point-1", "point_index": 1}
                ),
            ),
        }
    )
    third = append.model_copy(
        update={
            "start_index": 2,
            "records": (
                record.model_copy(
                    update={"logical_point_id": "point-2", "point_index": 2}
                ),
            ),
        }
    )
    assert measurements.ingest(second) == ()
    assert measurements.ingest(third) == ()
    assert measurements.flush() == (_measurement_receipt(append),)
    assert measurement_ingest_ranges == [(0, 1), (1, 2)]
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
    assert hardware_sequences == [0]
    assert coverage_ranges == [(0, 1), (1, 2)]
    assert inspection_commands[0].event.accepted_point is not None
    assert inspection_commands[0].event.accepted_point.point_index == 1


def test_daemon_execution_rejects_provision_receipt_for_another_operation() -> None:
    submission = RunSubmission(
        submission_id="submission-1",
        config=load_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            initial_point_count=1,
            point_limit=1,
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


def test_initial_lease_cancellation_skips_remote_provisioning() -> None:
    submission = RunSubmission(
        submission_id="submission-1",
        config=load_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=0,
            initial_point_count=0,
            point_limit=0,
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
    provisioned = False

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal provisioned
        if request.url.path.endswith("/executor/start"):
            return _model(
                _lease().model_copy(update={"cancellation_requested_at": _NOW})
            )
        if request.url.path.endswith("/instruments/provision"):
            provisioned = True
            command = RunInstrumentProvisionCommand.model_validate_json(request.content)
            return _model(
                RunInstrumentProvisionReceipt(
                    run_id="run-1",
                    operation_id=command.operation_id,
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

    session.begin()

    assert not provisioned
    assert session.cancellation_requested()
    assert not session.effects_ready()


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
        stage="domain_execute",
        effect="read",
        state="completed",
    )


def _measurement() -> MeasurementRecord:
    return MeasurementRecord(
        run_id="run-1",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={
            "signal": MeasurementScalar.create(
                dtype="float64",
                value=1.25,
                unit="ratio",
            )
        },
    )


def _measurement_header() -> MeasurementDatasetHeader:
    return MeasurementDatasetHeader(
        run_id="run-1",
        recording_contract_fingerprint="contract-1",
        dataset_schema=MeasurementDatasetSchema(
            dataset_id="raw-measurements",
            point_domain=MeasurementProductGridPointDomain(axes=[]),
            dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    unit="ratio",
                    dims=["point"],
                )
            ],
        ),
        expected_record_count=1,
        record_count_limit=1,
    )


def _measurement_append(
    record: MeasurementRecord,
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend(
        run_id="run-1",
        header_content_hash=header.content_hash,
        start_index=0,
        records=(record,),
    )


def _header_receipt(
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=header.operation_id,
        dataset_content_hash=header.content_hash,
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
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
        header_content_hash=header.content_hash,
        point_count=1,
        dataset_content_hash=measurement_dataset_content_hash(
            header_content_hash=header.content_hash,
            record_content_hashes=append.record_content_hashes,
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
