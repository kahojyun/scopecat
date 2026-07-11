"""Crash-visible local execution journal and point measurement commits."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from hashlib import sha256
from io import BufferedRandom
from pathlib import Path
from threading import Lock

from scopecat._content_identity import model_wire_content_hash
from scopecat._execution.journal import (
    CollectionChunk,
    CommittedCollectionChunk,
    CommittedPayloadEvidence,
    ExecutionJournalEntry,
    ExecutionJournalError,
    PayloadEvidence,
)
from scopecat._execution.program import ResourceClaim
from scopecat._storage.local.io import (
    ensure_durable_directory,
    read_model,
    write_model_atomic,
    write_model_if_absent,
)
from scopecat._storage.local.layout import LocalRunLayout
from scopecat._storage.refs import (
    EXECUTION_JOURNAL_DIR,
    EXECUTION_MEASUREMENTS_DIR,
    EXECUTION_PAYLOADS_DIR,
    EXECUTION_READBACKS_DIR,
)
from scopecat.results import MeasurementRecord


class LocalExecutionJournal:
    """Append immutable operation transitions as individually atomic files."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        self._layout = LocalRunLayout.from_workspace(workspace)
        self._directory = self._layout.run_dir(run_id) / EXECUTION_JOURNAL_DIR
        self._thread_lock = Lock()

    def append(self, entry: ExecutionJournalEntry) -> ExecutionJournalEntry:
        if entry.run_id != self._run_id:
            msg = "execution journal entry run_id does not match its journal"
            raise ExecutionJournalError(msg)
        ensure_durable_directory(self._directory)
        lock_path = self._directory / ".journal.lock"
        with self._thread_lock, lock_path.open("a+b") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                sequence = self._next_sequence()
                committed = entry.model_copy(
                    update={
                        "sequence": sequence,
                        "timestamp": datetime.now(UTC),
                    }
                )
                write_model_atomic(
                    self._directory / f"{sequence:08d}.json",
                    committed,
                )
                return committed
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                msg = f"failed to commit execution journal entry: {error}"
                raise ExecutionJournalError(msg) from error
            finally:
                flock(lock_file.fileno(), LOCK_UN)

    def entries(self) -> tuple[ExecutionJournalEntry, ...]:
        if not self._directory.is_dir():
            return ()
        return tuple(
            read_model(path, ExecutionJournalEntry)
            for path in sorted(self._directory.glob("[0-9]*.json"))
        )

    def _next_sequence(self) -> int:
        paths = sorted(self._directory.glob("[0-9]*.json"))
        if not paths:
            return 0
        try:
            return int(paths[-1].stem) + 1
        except ValueError as error:
            msg = "execution journal contains an invalid sequence filename"
            raise ExecutionJournalError(msg) from error


class LocalMeasurementCommitter:
    """Commit one immutable measurement file before advancing to another point."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.run_dir(run_id) / EXECUTION_MEASUREMENTS_DIR
        self._thread_lock = Lock()

    def commit(self, measurement: MeasurementRecord) -> None:
        if measurement.run_id != self._run_id:
            msg = "measurement run_id does not match its execution committer"
            raise ExecutionJournalError(msg)
        durable_measurement = MeasurementRecord.model_validate(
            measurement.model_dump(mode="json")
        )
        content_hash = model_wire_content_hash(durable_measurement)
        ensure_durable_directory(self._directory)
        path = self._measurement_path(durable_measurement.point_index)
        with self._thread_lock:
            try:
                if write_model_if_absent(path, durable_measurement):
                    return
                existing = read_model(path, MeasurementRecord)
                if model_wire_content_hash(existing) != content_hash:
                    msg = (
                        f"point {durable_measurement.point_index} has a different "
                        "committed measurement"
                    )
                    raise ExecutionJournalError(msg)
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                msg = f"failed to commit point measurement: {error}"
                raise ExecutionJournalError(msg) from error

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        if not self._directory.is_dir():
            return ()
        return tuple(
            read_model(path, MeasurementRecord)
            for path in sorted(self._directory.glob("point-*.json"))
        )

    def _measurement_path(self, point_index: int) -> Path:
        return self._directory / f"point-{point_index:08d}.json"


class LocalCollectionCommitter:
    """Commit immutable per-operation readbacks before journal completion."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.run_dir(run_id) / EXECUTION_READBACKS_DIR
        self._thread_lock = Lock()

    def commit(self, chunk: CollectionChunk) -> CommittedCollectionChunk:
        if chunk.run_id != self._run_id:
            msg = "collection chunk run_id does not match its committer"
            raise ExecutionJournalError(msg)
        durable_chunk = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        content_hash = durable_chunk.content_hash
        operation_digest = sha256(
            durable_chunk.operation_id.encode("utf-8")
        ).hexdigest()
        path = self._directory / f"{operation_digest}.json"
        with self._thread_lock:
            try:
                if not write_model_if_absent(path, durable_chunk):
                    existing = read_model(path, CollectionChunk)
                    if existing.content_hash != content_hash:
                        msg = (
                            "collection operation "
                            f"{durable_chunk.operation_id} already "
                            "has a different committed readback"
                        )
                        raise ExecutionJournalError(msg)
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                msg = f"failed to commit collection readback: {error}"
                raise ExecutionJournalError(msg) from error
        return CommittedCollectionChunk(
            ref=f"{EXECUTION_READBACKS_DIR}/{path.name}",
            content_hash=content_hash,
        )


class LocalPayloadEvidenceCommitter:
    """Commit structural payload evidence before it enters a driver command."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.run_dir(run_id) / EXECUTION_PAYLOADS_DIR
        self._thread_lock = Lock()

    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence:
        if evidence.run_id != self._run_id:
            msg = "payload evidence run_id does not match its committer"
            raise ExecutionJournalError(msg)
        operation_digest = sha256(evidence.operation_id.encode("utf-8")).hexdigest()
        path = self._directory / f"{operation_digest}.json"
        with self._thread_lock:
            if not write_model_if_absent(path, evidence):
                existing = read_model(path, PayloadEvidence)
                if existing != evidence:
                    msg = (
                        f"compute operation {evidence.operation_id} already has "
                        "different payload evidence"
                    )
                    raise ExecutionJournalError(msg)
        return CommittedPayloadEvidence(
            ref=f"{EXECUTION_PAYLOADS_DIR}/{path.name}",
            content_hash=evidence.content_hash,
        )


class LocalResourceLeaseManager:
    """Hold canonical whole-run file leases for instruments/channels/groups."""

    def __init__(self, workspace: str | Path) -> None:
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.workspace / "execution-resources"

    @contextmanager
    def acquire(self, claims: tuple[ResourceClaim, ...]) -> Generator[None]:
        ensure_durable_directory(self._directory)
        lock_files: list[BufferedRandom] = []
        ordered = sorted(claims, key=lambda claim: (claim.kind, claim.id))
        try:
            for claim in ordered:
                digest = sha256(f"{claim.kind}:{claim.id}".encode()).hexdigest()
                lock_file = (self._directory / f"{digest}.lock").open("a+b")
                flock(lock_file.fileno(), LOCK_EX)
                lock_files.append(lock_file)
            yield
        finally:
            for lock_file in reversed(lock_files):
                flock(lock_file.fileno(), LOCK_UN)
                lock_file.close()


__all__ = [
    "LocalCollectionCommitter",
    "LocalExecutionJournal",
    "LocalMeasurementCommitter",
    "LocalPayloadEvidenceCommitter",
    "LocalResourceLeaseManager",
]
