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
    MeasurementSealCommand,
    RunAdmission,
    RunInstrumentApplyCommand,
    RunInstrumentCollectCommand,
    RunInstrumentLifecycleCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunInstrumentReadCommand,
    RunSubmission,
    TerminalModelWrite,
    TerminalRunCommitCommand,
)
from scopecat.execution.ports.instruments import (
    InstrumentLifecycleAction,
)
from scopecat.execution.services import ExecutionSession
from scopecat.kernel.problems import Problem
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentStateCommand,
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
        instruments.provision()

    return ExecutionSession(
        accepted=admission.manifest,
        begin=begin,
        commit_terminal=authority.commit_terminal,
        journal=_DaemonExecutionJournal(authority),
        measurements=_DaemonMeasurementRepository(authority),
        instruments=instruments,
    )


class LeaseSupervisor(Protocol):
    """Observe lease start and reject work after background renewal fails."""

    def start(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None: ...

    def require_live(self) -> None: ...


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
    def provider_id(self) -> str | None:
        return self._receipt().provider_id

    @property
    def descriptions(self) -> tuple[InstrumentDescription, ...]:
        return self._receipt().descriptions

    @property
    def ready(self) -> bool:
        return self._receipt().status == "ready"

    @property
    def setup_problems(self) -> tuple[Problem, ...]:
        return self._receipt().problems

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

    def read_state(
        self,
        instrument_id: str,
        *,
        operation_id: str,
    ) -> InstrumentStateSnapshot:
        return self._authority.client.read_run_instrument_state(
            self._authority.run_id,
            instrument_id,
            RunInstrumentReadCommand(
                lease_id=self._authority.fence(),
                operation_id=operation_id,
            ),
        )

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        operation_id = command.operation_id
        if operation_id is None:
            raise ValueError("run instrument apply requires an operation id")
        return self._authority.client.apply_run_instrument_state(
            self._authority.run_id,
            command.instrument_id,
            RunInstrumentApplyCommand(
                lease_id=self._authority.fence(),
                operation_id=operation_id,
                command=command,
            ),
        )

    def collect(self, command: CollectCommand) -> CollectReceipt:
        operation_id = command.operation_id
        if operation_id is None:
            raise ValueError("run instrument collect requires an operation id")
        return self._authority.client.collect_run_instrument(
            self._authority.run_id,
            command.instrument_id,
            RunInstrumentCollectCommand(
                lease_id=self._authority.fence(),
                operation_id=operation_id,
                command=command,
            ),
        )

    def lifecycle(
        self,
        instrument_id: str,
        *,
        operation_id: str,
        action: InstrumentLifecycleAction,
    ) -> None:
        receipt = self._authority.client.run_instrument_lifecycle(
            self._authority.run_id,
            instrument_id,
            RunInstrumentLifecycleCommand(
                lease_id=self._authority.fence(),
                operation_id=operation_id,
                action=action,
            ),
        )
        if (
            receipt.run_id != self._authority.run_id
            or receipt.instrument_id != instrument_id
            or receipt.operation_id != operation_id
            or receipt.action != action
        ):
            raise ValueError("run instrument lifecycle receipt does not match command")

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
