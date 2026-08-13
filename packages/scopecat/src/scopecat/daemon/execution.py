"""Execution ports for a client-owned program admitted by the daemon."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from threading import Lock
from time import monotonic
from typing import Protocol, cast

from pydantic import BaseModel, JsonValue, TypeAdapter

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.points import (
    RunPointCoordinateValue,
    RunPointDecisionCommand,
    RunPointPlanCloseCommand,
    RunPointProposalAttemptView,
)
from scopecat.daemon.reviews import (
    ReviewCoordinateValue,
    ReviewInspectionView,
    ReviewPointView,
    RunInspectionAppendCommand,
    RunPointInspectionEvent,
)
from scopecat.daemon.wire import (
    ExecutionTransitionAppend,
    ExecutionTransitionClaim,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementFlushCommand,
    MeasurementHeaderCommand,
    MeasurementSealCommand,
    RunAdmission,
    RunCoverageAdvanceCommand,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalModelWrite,
    TerminalRunCommitCommand,
)
from scopecat.execution.program import RunPointInspection
from scopecat.execution.services import ExecutionSession, QueuedRunPointCandidate
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.problems import Problem
from scopecat.kernel.value_data import CellValue
from scopecat.measurements.points import (
    AcceptedRunPoint,
    OperatorPointRequest,
    PointProposalAttempt,
)
from scopecat.optimization import PointProposalDecision
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementRecord,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetBatch,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
)

_JSON_DOCUMENT = TypeAdapter(dict[str, JsonValue])
_PROVISION_OPERATION_ID = "lifecycle.provide-instruments"
_MEASUREMENT_TRANSPORT_RECORD_LIMIT = 64
_MEASUREMENT_TRANSPORT_VALUE_BYTE_LIMIT = 8 * 1024 * 1024
_MEASUREMENT_TRANSPORT_LATENCY_SECONDS = 0.1
_COVERAGE_TRANSPORT_POINT_LIMIT = 256
_COVERAGE_TRANSPORT_LATENCY_SECONDS = 0.1


class ExecutorLeaseLostError(RuntimeError):
    """An executor can no longer commit effects to its run."""

    def __init__(self, lease: ExecutorLease, cause: Exception) -> None:
        super().__init__(
            f"executor lease {lease.lease_id!r} for run "
            f"{lease.run_id!r} is no longer live: {cause}"
        )
        self.lease = lease
        self.cause = cause


def daemon_execution_session(
    client: DaemonClient,
    submission: RunSubmission,
    admission: RunAdmission,
    *,
    executor_id: str,
    lease_supervisor: LeaseSupervisor | None = None,
) -> ExecutionSession:
    """Bind client-owned code to the admitted daemon-owned run."""

    if admission.manifest.outcome is not None:
        raise ValueError("terminal run cannot start execution")
    if admission.submission_id != submission.submission_id:
        raise ValueError("submission and admission ids do not match")
    if admission.manifest.config_content_hash != config_content_hash(submission.config):
        raise ValueError("submission and admission config snapshots do not match")
    if admission.manifest.config_source != submission.config_source:
        raise ValueError("submission and admission config sources do not match")

    authority = _LeaseAuthority(
        client=client,
        run_id=admission.manifest.run_id,
        executor_id=executor_id,
        lease_supervisor=lease_supervisor,
    )
    instruments = _DaemonRunInstrumentHost(authority)
    coverage = _DaemonRunCoverage(authority)
    point_proposals = _DaemonRunPointProposals(authority)

    def begin() -> None:
        authority.start()
        if not authority.cancellation_requested():
            instruments.provision()

    return ExecutionSession(
        accepted=admission.manifest,
        begin=begin,
        commit_terminal=authority.commit_terminal,
        journal=_DaemonExecutionJournal(authority),
        measurements=_DaemonMeasurementRepository(authority),
        instruments=instruments,
        coverage=coverage,
        point_proposals=point_proposals,
        cancellation_requested=authority.cancellation_requested,
        effects_ready=lambda: instruments.provisioned,
    )


class LeaseSupervisor(Protocol):
    """Observe lease start and reject work after background renewal fails."""

    def start(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None: ...

    def require_live(self) -> None: ...

    def cancellation_requested(self) -> bool: ...


class _LeaseAuthority:
    def __init__(
        self,
        *,
        client: DaemonClient,
        run_id: str,
        executor_id: str,
        lease_supervisor: LeaseSupervisor | None,
    ) -> None:
        self.client = client
        self.run_id = run_id
        self.executor_id = executor_id
        self._lease: ExecutorLease | None = None
        self._lease_supervisor = lease_supervisor
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._lease is not None:
                return
        lease = self.client.start_executor(
            self.run_id,
            ExecutorStartRequest(
                executor_id=self.executor_id,
            ),
        )
        with self._lock:
            self._lease = lease
        if self._lease_supervisor is not None:
            self._lease_supervisor.start(lease, self.heartbeat)

    def fence(self) -> str:
        if self._lease_supervisor is not None:
            self._lease_supervisor.require_live()
        with self._lock:
            lease = self._lease
        if lease is None:
            raise RuntimeError("executor has not started")
        return lease.lease_id

    def heartbeat(self) -> ExecutorLease:
        lease_id = self.fence()
        lease = self.client.heartbeat_executor(
            self.run_id,
            ExecutorHeartbeat(
                lease_id=lease_id,
            ),
        )
        with self._lock:
            if self._lease is None:
                raise RuntimeError("executor has not started")
            self._lease = lease
        return lease

    def cancellation_requested(self) -> bool:
        if self._lease_supervisor is not None:
            return self._lease_supervisor.cancellation_requested()
        with self._lock:
            lease = self._lease
        return lease is not None and lease.cancellation_requested_at is not None

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        lease_id = self.fence()
        return self.client.commit_terminal(
            self.run_id,
            TerminalRunCommitCommand(
                lease_id=lease_id,
                outcome=commit.outcome,
                contents=commit.contents,
                models=tuple(
                    TerminalModelWrite(
                        ref=write.ref,
                        value=_json_document(write.value),
                    )
                    for write in commit.models
                ),
            ),
        )


class _DaemonExecutionJournal:
    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        lease_id = self._authority.fence()
        return self._authority.client.append_transition(
            self._authority.run_id,
            ExecutionTransitionAppend(
                lease_id=lease_id,
                transition=entry,
            ),
        )

    def claim(self, entry: ExecutionTransition) -> ExecutionTransition:
        lease_id = self._authority.fence()
        return self._authority.client.claim_transition(
            self._authority.run_id,
            ExecutionTransitionClaim(
                lease_id=lease_id,
                transition=entry,
            ),
        )


class _DaemonRunCoverage:
    """Coalesce no-dataset point progress before durable daemon writes."""

    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority
        self._pending_start: int | None = None
        self._pending_count = 0
        self._last_send_at: float | None = None

    def advance(self, *, start_index: int, point_count: int) -> None:
        if point_count < 1:
            raise ValueError("coverage advance must be non-empty")
        if self._pending_start is None:
            self._pending_start = start_index
        elif start_index != self._pending_start + self._pending_count:
            raise ValueError("coverage advances must be contiguous")
        self._pending_count += point_count
        now = monotonic()
        if (
            self._last_send_at is None
            or self._pending_count >= _COVERAGE_TRANSPORT_POINT_LIMIT
            or now - self._last_send_at >= _COVERAGE_TRANSPORT_LATENCY_SECONDS
        ):
            self._send_pending(now=now)

    def flush(self) -> None:
        self._send_pending()

    def _send_pending(self, *, now: float | None = None) -> None:
        start_index = self._pending_start
        point_count = self._pending_count
        if start_index is None:
            return
        state = self._authority.client.advance_run_coverage(
            self._authority.run_id,
            RunCoverageAdvanceCommand(
                lease_id=self._authority.fence(),
                start_index=start_index,
                point_count=point_count,
            ),
        )
        expected_count = start_index + point_count
        if state.run_id != self._authority.run_id:
            raise ValueError("run coverage receipt does not match its request")
        if state.completed_point_count != expected_count:
            raise ValueError("run coverage receipt did not commit the requested prefix")
        self._pending_start = None
        self._pending_count = 0
        self._last_send_at = monotonic() if now is None else now


class _DaemonRunPointProposals:
    """Persist point decisions and publish bounded transient inspections."""

    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority

    def next_queued(self) -> QueuedRunPointCandidate | None:
        pending = next(
            (
                entry
                for entry in self._authority.client.get_next_queued_run_point(
                    self._authority.run_id
                ).items
                if entry.status == "pending"
            ),
            None,
        )
        if pending is None:
            return None
        return QueuedRunPointCandidate(
            request=OperatorPointRequest(
                request_id=pending.request.request_id,
                coordinates=cast(
                    "dict[str, CellValue]",
                    pending.request.coordinates,
                ),
            ),
        )

    def append(
        self,
        decision: PointProposalDecision,
        inspection: RunPointInspection | None,
        *,
        operator_request_id: str | None = None,
    ) -> None:
        durable = self._authority.client.append_run_point_decision(
            self._authority.run_id,
            RunPointDecisionCommand(
                lease_id=self._authority.fence(),
                operation_id=_point_decision_operation_id(
                    decision,
                    operator_request_id=operator_request_id,
                ),
                operator_request_id=operator_request_id,
                proposal=_point_proposal_attempt(decision.candidate),
                outcome=decision.outcome,
                reason=decision.reason,
            ),
        )
        if durable.proposal_index != decision.proposal_index:
            raise ValueError("daemon assigned a different proposal index")
        if durable.outcome != decision.outcome:
            raise ValueError("daemon recorded a different proposal outcome")
        if decision.accepted_point is not None:
            accepted = durable.accepted_point
            if (
                accepted is None
                or accepted.point_index != decision.accepted_point.ordinal
            ):
                raise ValueError("daemon assigned a different accepted point ordinal")
        with suppress(Exception):
            self._authority.client.append_run_inspection(
                self._authority.run_id,
                RunInspectionAppendCommand(
                    lease_id=self._authority.fence(),
                    event=RunPointInspectionEvent(
                        proposal_index=durable.proposal_index,
                        occurred_at=durable.occurred_at,
                        candidate=_review_point(decision.candidate),
                        outcome=durable.outcome,
                        accepted_point=(
                            None
                            if decision.accepted_point is None
                            else _review_point(decision.accepted_point)
                        ),
                        reason=durable.reason,
                        inspections=_review_inspections(inspection),
                    ),
                ),
            )

    def close(self, *, completed_point_count: int, reason: str) -> None:
        self._authority.client.close_run_point_plan(
            self._authority.run_id,
            RunPointPlanCloseCommand(
                lease_id=self._authority.fence(),
                operation_id=_point_plan_close_operation_id(
                    completed_point_count=completed_point_count,
                    reason=reason,
                ),
                based_on_completed_point_count=completed_point_count,
                reason=reason,
            ),
        )


class _DaemonMeasurementRepository:
    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority
        self._pending: list[MeasurementRecord] = []
        self._pending_value_bytes = 0
        self._last_send_at: float | None = None
        self._header_content_hash: str | None = None
        self._dataset_schema: MeasurementDatasetSchema | None = None

    def initialize(
        self,
        header: MeasurementDatasetHeader,
    ) -> MeasurementDatasetReceipt:
        lease_id = self._authority.fence()
        receipt = self._authority.client.initialize_measurements(
            self._authority.run_id,
            MeasurementHeaderCommand(
                lease_id=lease_id,
                header=header,
            ),
        )
        self._header_content_hash = header.content_hash
        self._dataset_schema = header.dataset_schema
        return receipt

    def ingest(
        self,
        batch: MeasurementDatasetBatch,
    ) -> tuple[MeasurementDatasetReceipt, ...]:
        self._pending.extend(batch.records)
        self._pending_value_bytes += sum(
            _measurement_record_value_bytes(record) for record in batch.records
        )
        now = monotonic()
        if (
            self._last_send_at is None
            or len(self._pending) >= _MEASUREMENT_TRANSPORT_RECORD_LIMIT
            or self._pending_value_bytes >= _MEASUREMENT_TRANSPORT_VALUE_BYTE_LIMIT
            or now - self._last_send_at >= _MEASUREMENT_TRANSPORT_LATENCY_SECONDS
        ):
            return self._send_pending(now=now)
        return ()

    def _send_pending(
        self,
        *,
        now: float | None = None,
    ) -> tuple[MeasurementDatasetReceipt, ...]:
        if not self._pending:
            return ()
        records = tuple(self._pending)
        header_content_hash = self._header_content_hash
        if header_content_hash is None:
            raise RuntimeError("measurement transport requires an initialized header")
        dataset_schema = self._dataset_schema
        if dataset_schema is None:
            raise RuntimeError("measurement transport requires an initialized schema")
        batch = MeasurementDatasetBatch(
            run_id=self._authority.run_id,
            header_content_hash=header_content_hash,
            start_index=records[0].point_index,
            records=records,
        )
        lease_id = self._authority.fence()
        receipt = self._authority.client.ingest_measurements(
            self._authority.run_id,
            lease_id=lease_id,
            batch=batch,
            dataset_schema=dataset_schema,
        )
        self._pending.clear()
        self._pending_value_bytes = 0
        self._last_send_at = monotonic() if now is None else now
        return receipt.durable_receipts

    def flush(self) -> tuple[MeasurementDatasetReceipt, ...]:
        receipts = list(self._send_pending())
        receipt = self._authority.client.flush_measurements(
            self._authority.run_id,
            MeasurementFlushCommand(lease_id=self._authority.fence()),
        )
        receipts.extend(receipt.durable_receipts)
        return tuple(receipts)

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        lease_id = self._authority.fence()
        return self._authority.client.seal_measurements(
            self._authority.run_id,
            MeasurementSealCommand(
                lease_id=lease_id,
                seal=seal,
            ),
        )


class _DaemonRunInstrumentHost:
    """Typed transport proxy for drivers retained by the project daemon."""

    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority
        self._provisioning: RunInstrumentProvisionReceipt | None = None
        self._next_batch_sequence = 0
        self._lock = Lock()

    @property
    def provisioned(self) -> bool:
        with self._lock:
            return self._provisioning is not None

    @property
    def ready(self) -> bool:
        return self._receipt().status == "ready"

    @property
    def setup_problems(self) -> tuple[Problem, ...]:
        return self._receipt().problems

    @property
    def observed_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._receipt().observed_state

    @property
    def baseline_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._receipt().baseline_state

    def provision(self) -> RunInstrumentProvisionReceipt:
        with self._lock:
            if self._provisioning is not None:
                return self._provisioning
        lease_id = self._authority.fence()
        receipt = self._authority.client.provision_run_instruments(
            self._authority.run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id=_PROVISION_OPERATION_ID,
            ),
        )
        if (
            receipt.run_id != self._authority.run_id
            or receipt.operation_id != _PROVISION_OPERATION_ID
        ):
            raise ValueError(
                "run instrument provisioning receipt does not match command"
            )
        with self._lock:
            if self._provisioning is None:
                self._provisioning = receipt
            return self._provisioning

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        with self._lock:
            sequence = self._next_batch_sequence
            receipt = self._authority.client.execute_run_hardware(
                self._authority.run_id,
                RunHardwareBatchCommand(
                    lease_id=self._authority.fence(),
                    sequence=sequence,
                    batch=batch,
                ),
            )
            self._next_batch_sequence = sequence + 1
            return receipt

    def finish(
        self,
        *,
        operation_id: str,
        failed: bool,
    ) -> RunHardwareFinalizationReceipt:
        return self._authority.client.finish_run_hardware(
            self._authority.run_id,
            RunHardwareFinishCommand(
                lease_id=self._authority.fence(),
                operation_id=operation_id,
                failed=failed,
            ),
        )

    def _receipt(self) -> RunInstrumentProvisionReceipt:
        with self._lock:
            receipt = self._provisioning
        if receipt is None:
            raise RuntimeError("run instruments have not been provisioned")
        return receipt


def _review_point(point: PointProposalAttempt | AcceptedRunPoint) -> ReviewPointView:
    return ReviewPointView(
        point_index=(point.ordinal if isinstance(point, AcceptedRunPoint) else None),
        coordinates=cast(
            "dict[str, ReviewCoordinateValue]",
            dict(point.coordinates),
        ),
        proposal_fingerprint=point.proposal_fingerprint,
        source=point.source,
    )


def _point_proposal_attempt(
    proposal: PointProposalAttempt,
) -> RunPointProposalAttemptView:
    return RunPointProposalAttemptView(
        coordinates=cast(
            "dict[str, RunPointCoordinateValue]",
            dict(proposal.coordinates),
        ),
        proposal_fingerprint=proposal.proposal_fingerprint,
        source=proposal.source,
        based_on_completed_point_count=proposal.based_on_completed_point_count,
    )


def _point_decision_operation_id(
    decision: PointProposalDecision,
    *,
    operator_request_id: str | None,
) -> str:
    return "point-decision." + stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.point_decision_operation.v1",
                "proposal_index": decision.proposal_index,
                "proposal_fingerprint": decision.candidate.proposal_fingerprint,
                "operator_request_id": operator_request_id,
                "outcome": decision.outcome,
                "reason": decision.reason,
            }
        )
    )


def _point_plan_close_operation_id(
    *,
    completed_point_count: int,
    reason: str,
) -> str:
    return "point-plan.close." + stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.point_plan_close_operation.v1",
                "completed_point_count": completed_point_count,
                "reason": reason,
            }
        )
    )


def _review_inspections(
    inspection: RunPointInspection | None,
) -> tuple[ReviewInspectionView, ...]:
    if inspection is None:
        return ()
    projected: list[ReviewInspectionView] = []
    for job in inspection.jobs:
        content = job.execution.inspection
        if content is None:
            continue
        intent = job.execution.invocation.intent
        projected.append(
            ReviewInspectionView(
                operation_id=job.id,
                point_index=inspection.point_index,
                target_id=intent.target_id,
                artifact_id=intent.artifact_id,
                artifact_fingerprint=intent.artifact_fingerprint,
                content=content,
            )
        )
    return tuple(projected)


def _json_document(model: BaseModel) -> dict[str, JsonValue]:
    return _JSON_DOCUMENT.validate_python(model.model_dump(mode="json"))


def _measurement_record_value_bytes(record: MeasurementRecord) -> int:
    return sum(
        value.values.nbytes
        for values in (record.coordinates, record.observables)
        for value in values.values()
        if isinstance(value, MeasurementArray)
    )


__all__ = [
    "ExecutorLeaseLostError",
    "LeaseSupervisor",
    "daemon_execution_session",
]
