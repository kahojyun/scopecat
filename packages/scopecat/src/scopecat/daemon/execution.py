"""Execution ports for a client-owned program admitted by the daemon."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, JsonValue, TypeAdapter

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    ExecutionTransitionAppend,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementHeaderCommand,
    MeasurementSealCommand,
    RunAdmission,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalModelWrite,
    TerminalRunCommitCommand,
)
from scopecat.execution.services import ExecutionSession
from scopecat.kernel.problems import Problem
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
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


class _DaemonMeasurementRepository:
    def __init__(self, authority: _LeaseAuthority) -> None:
        self._authority = authority

    def initialize(
        self,
        header: MeasurementDatasetHeader,
    ) -> MeasurementDatasetReceipt:
        lease_id = self._authority.fence()
        return self._authority.client.initialize_measurements(
            self._authority.run_id,
            MeasurementHeaderCommand(
                lease_id=lease_id,
                header=header,
            ),
        )

    def append(
        self,
        append: MeasurementDatasetAppend,
    ) -> MeasurementDatasetReceipt:
        lease_id = self._authority.fence()
        return self._authority.client.append_measurements(
            self._authority.run_id,
            MeasurementAppendCommand(
                lease_id=lease_id,
                append=append,
            ),
        )

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
    def prepared_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._receipt().prepared_state

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
        return self._authority.client.execute_run_hardware(
            self._authority.run_id,
            RunHardwareBatchCommand(
                lease_id=self._authority.fence(),
                batch=batch,
            ),
        )

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


def _json_document(model: BaseModel) -> dict[str, JsonValue]:
    return _JSON_DOCUMENT.validate_python(model.model_dump(mode="json"))


__all__ = [
    "ExecutorLeaseLostError",
    "LeaseSupervisor",
    "daemon_execution_session",
]
