"""Execution ports for a notebook-owned delegated program."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Lock
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, JsonValue, TypeAdapter

from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    CollectionCommitCommand,
    CollectionResolveCommand,
    DelegatedRunSubmission,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementSealCommand,
    PayloadCommitCommand,
    RunAdmission,
    TerminalModelWrite,
    TerminalRecordSetWrite,
    TerminalRunCommitCommand,
)
from scopecat.execution.services import ExecutionServices
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunManifest
from scopecat.runs.repository import TerminalRunCommit

_JSON_DOCUMENT = TypeAdapter(dict[str, JsonValue])


def delegated_execution_services(
    client: DaemonClient,
    submission: DelegatedRunSubmission,
    admission: RunAdmission,
    *,
    lease_supervisor: DelegatedLeaseSupervisor | None = None,
) -> ExecutionServices:
    """Bind transient notebook code to the admitted daemon-owned run."""

    if admission.execution_mode != "delegated":
        raise ValueError("delegated execution requires a delegated admission")
    if admission.submission_id != submission.submission_id:
        raise ValueError("submission and admission ids do not match")
    if admission.config_content_hash != submission.config_content_hash:
        raise ValueError("submission and admission config snapshots do not match")

    authority = _LeaseAuthority(
        client=client,
        run_id=admission.run_id,
        executor_id=submission.executor_id,
        lease_supervisor=lease_supervisor,
    )
    runs = _DelegatedRunStore(
        authority=authority,
        config=submission.config,
        admission=admission,
    )
    resources = _DelegatedResourceLeaseManager(authority=authority, runs=runs)
    return ExecutionServices(
        runs=runs,
        resources=resources,
        journal_for=lambda run_id: _DelegatedExecutionJournal(authority, run_id),
        measurements_for=lambda run_id: _DelegatedMeasurementRepository(
            authority,
            run_id,
        ),
        collections_for=lambda run_id: _DelegatedCollectionRepository(
            authority,
            run_id,
        ),
        payloads_for=lambda run_id: _DelegatedPayloadCommitter(authority, run_id),
    )


class DelegatedLeaseSupervisor(Protocol):
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
        lease_supervisor: DelegatedLeaseSupervisor | None,
    ) -> None:
        self.client = client
        self.run_id = run_id
        self.executor_id = executor_id
        self.lease: ExecutorLease | None = None
        self._lease_supervisor = lease_supervisor
        self._lock = Lock()

    def start(self, manifest: RunManifest) -> None:
        with self._lock:
            if self.lease is not None:
                return
        lease = self.client.start_executor(
            ExecutorStartRequest(
                run_id=self.run_id,
                executor_id=self.executor_id,
                manifest=manifest,
            )
        )
        with self._lock:
            self.lease = lease
        if self._lease_supervisor is not None:
            self._lease_supervisor.start(lease, self.heartbeat)

    def fence(self) -> tuple[str, int]:
        if self._lease_supervisor is not None:
            self._lease_supervisor.require_live()
        with self._lock:
            lease = self.lease
        if lease is None:
            raise RuntimeError("delegated executor has not started")
        return lease.lease_id, lease.generation

    def heartbeat(self) -> ExecutorLease:
        lease_id, generation = self.fence()
        lease = self.client.heartbeat_executor(
            self.run_id,
            ExecutorHeartbeat(
                run_id=self.run_id,
                lease_id=lease_id,
                generation=generation,
            ),
        )
        with self._lock:
            self.lease = lease
        return lease

    def recovery(self) -> ExecutionRecoverySnapshot:
        lease_id, generation = self.fence()
        return self.client.recover_execution(
            ExecutionRecoveryRequest(
                run_id=self.run_id,
                lease_id=lease_id,
                generation=generation,
            )
        )

    def require_run(self, run_id: str) -> None:
        if run_id != self.run_id:
            raise ValueError("execution port run_id does not match its admission")


class _DelegatedRunStore:
    def __init__(
        self,
        *,
        authority: _LeaseAuthority,
        config: ConfigProfileSnapshot,
        admission: RunAdmission,
    ) -> None:
        self._authority = authority
        self._config = config
        self._manifest = RunManifest(
            run_id=admission.run_id,
            created_at=admission.accepted_at,
            lifecycle="accepted",
            config_content_hash=admission.config_content_hash,
        )
        self._running: RunManifest | None = None

    def read_manifest(self, run_id: str) -> RunManifest:
        self._authority.require_run(run_id)
        return self._manifest

    def write_manifest(self, manifest: RunManifest) -> None:
        self._authority.require_run(manifest.run_id)
        if manifest.lifecycle != "running":
            raise ValueError("delegated execution can only stage a running manifest")
        self._manifest = manifest
        self._running = manifest

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        self._authority.require_run(run_id)
        return self._config

    def running_manifest(self) -> RunManifest:
        if self._running is None:
            raise RuntimeError("running manifest must be staged before executor start")
        return self._running

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        self._authority.require_run(commit.manifest.run_id)
        lease_id, generation = self._authority.fence()
        command_id = f"terminal:{commit.manifest.run_id}"
        receipt = self._authority.client.commit_terminal(
            TerminalRunCommitCommand(
                command_id=command_id,
                run_id=commit.manifest.run_id,
                lease_id=lease_id,
                generation=generation,
                manifest=commit.manifest,
                models=tuple(
                    TerminalModelWrite(
                        ref=write.ref,
                        value=_json_document(write.value),
                    )
                    for write in commit.models
                ),
                record_sets=tuple(
                    TerminalRecordSetWrite(
                        ref=write.ref,
                        records=tuple(
                            _json_document(record) for record in write.records
                        ),
                    )
                    for write in commit.record_sets
                ),
            )
        )
        if receipt.command_id != command_id:
            raise ValueError("terminal receipt command_id does not match")
        self._manifest = receipt.manifest
        return receipt.manifest


class _DelegatedResourceLeaseManager:
    def __init__(
        self,
        *,
        authority: _LeaseAuthority,
        runs: _DelegatedRunStore,
    ) -> None:
        self._authority = authority
        self._runs = runs

    @contextmanager
    def acquire(self, claims: tuple[ResourceClaim, ...]) -> Generator[None]:
        """Start once; the daemon leases the claims captured at admission."""

        del claims
        self._authority.start(self._runs.running_manifest())
        yield


class _DelegatedExecutionJournal:
    def __init__(self, authority: _LeaseAuthority, run_id: str) -> None:
        authority.require_run(run_id)
        self._authority = authority
        self._run_id = run_id

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        lease_id, generation = self._authority.fence()
        batch_id = f"transition:{uuid4()}"
        receipt = self._authority.client.append_transitions(
            ExecutionTransitionBatch(
                batch_id=batch_id,
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                transitions=(entry,),
            )
        )
        if receipt.batch_id != batch_id:
            raise ValueError("transition receipt batch_id does not match")
        return receipt.committed[0]

    def entries(self) -> tuple[ExecutionTransition, ...]:
        return self._authority.recovery().transitions


class _DelegatedMeasurementRepository:
    def __init__(self, authority: _LeaseAuthority, run_id: str) -> None:
        authority.require_run(run_id)
        self._authority = authority
        self._run_id = run_id

    def append(
        self,
        append: MeasurementDatasetAppend,
    ) -> MeasurementDatasetReceipt:
        lease_id, generation = self._authority.fence()
        command_id = append.operation_id
        receipt = self._authority.client.append_measurements(
            MeasurementAppendCommand(
                command_id=command_id,
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                append=append,
            )
        )
        if receipt.command_id != command_id:
            raise ValueError("measurement append receipt command_id does not match")
        return receipt.receipt

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        lease_id, generation = self._authority.fence()
        command_id = seal.operation_id
        receipt = self._authority.client.seal_measurements(
            MeasurementSealCommand(
                command_id=command_id,
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                seal=seal,
            )
        )
        if receipt.command_id != command_id:
            raise ValueError("measurement seal receipt command_id does not match")
        return receipt.receipt

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        return self._authority.recovery().measurements

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]:
        return self._authority.recovery().measurement_append_indices


class _DelegatedCollectionRepository:
    def __init__(self, authority: _LeaseAuthority, run_id: str) -> None:
        authority.require_run(run_id)
        self._authority = authority
        self._run_id = run_id

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        lease_id, generation = self._authority.fence()
        command_id = chunk.operation_id
        receipt = self._authority.client.commit_collection(
            CollectionCommitCommand(
                command_id=command_id,
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                chunk=chunk,
            )
        )
        if receipt.command_id != command_id:
            raise ValueError("collection receipt command_id does not match")
        return receipt.receipt

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        lease_id, generation = self._authority.fence()
        response = self._authority.client.resolve_collection(
            CollectionResolveCommand(
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                receipt=receipt,
            )
        )
        return response.chunk

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        return self._authority.recovery().collection_receipts


class _DelegatedPayloadCommitter:
    def __init__(self, authority: _LeaseAuthority, run_id: str) -> None:
        authority.require_run(run_id)
        self._authority = authority
        self._run_id = run_id

    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence:
        lease_id, generation = self._authority.fence()
        command_id = evidence.operation_id
        receipt = self._authority.client.commit_payload(
            PayloadCommitCommand(
                command_id=command_id,
                run_id=self._run_id,
                lease_id=lease_id,
                generation=generation,
                evidence=evidence,
            )
        )
        if receipt.command_id != command_id:
            raise ValueError("payload receipt command_id does not match")
        return receipt.evidence


def _json_document(model: BaseModel) -> dict[str, JsonValue]:
    return _JSON_DOCUMENT.validate_python(model.model_dump(mode="json"))


__all__ = ["DelegatedLeaseSupervisor", "delegated_execution_services"]
