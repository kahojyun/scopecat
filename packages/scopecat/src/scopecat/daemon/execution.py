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
    RunSubmission,
    TerminalModelWrite,
    TerminalRunCommitCommand,
)
from scopecat.execution.services import ExecutionSession
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit

_JSON_DOCUMENT = TypeAdapter(dict[str, JsonValue])


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
    return ExecutionSession(
        accepted=admission.manifest,
        config=submission.config,
        begin=authority.start,
        commit_terminal=authority.commit_terminal,
        journal=_DaemonExecutionJournal(authority),
        measurements=_DaemonMeasurementRepository(authority),
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


def _json_document(model: BaseModel) -> dict[str, JsonValue]:
    return _JSON_DOCUMENT.validate_python(model.model_dump(mode="json"))


__all__ = [
    "ExecutorLeaseLostError",
    "LeaseSupervisor",
    "daemon_execution_session",
]
