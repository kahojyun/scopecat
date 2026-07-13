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

from scopecat._content_identity import stable_content_hash
from scopecat._execution.journal import (
    CollectionChunk,
    CollectionChunkReceipt,
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
from scopecat.measurement_recording import (
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
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


class LocalMeasurementRecordCommitter:
    """Commit one immutable measurement file before advancing to another point."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.run_dir(run_id) / EXECUTION_MEASUREMENTS_DIR
        self._thread_lock = Lock()

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        durable_chunk = MeasurementRecordChunk.model_validate(
            chunk.model_dump(mode="python")
        )
        if durable_chunk.run_id != self._run_id:
            msg = "measurement run_id does not match its execution committer"
            raise ExecutionJournalError(msg)
        ensure_durable_directory(self._directory)
        path = self._measurement_path(durable_chunk)
        with self._thread_lock:
            try:
                if not write_model_if_absent(path, durable_chunk):
                    existing = read_model(path, MeasurementRecordChunk)
                    if (
                        existing.operation_id != durable_chunk.operation_id
                        or existing.content_hash != durable_chunk.content_hash
                    ):
                        msg = (
                            f"point {durable_chunk.point_index} has a different "
                            "committed measurement chunk"
                        )
                        raise ExecutionJournalError(msg)
                record_ref = f"{EXECUTION_MEASUREMENTS_DIR}/{path.name}"
                return MeasurementRecordReceipt(
                    operation_id=durable_chunk.operation_id,
                    chunk_content_hash=durable_chunk.content_hash,
                    record_ref=record_ref,
                )
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                msg = f"failed to commit point measurement: {error}"
                raise ExecutionJournalError(msg) from error

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        if not self._directory.is_dir():
            return ()
        chunks = tuple(
            sorted(
                (
                    read_model(path, MeasurementRecordChunk)
                    for path in self._directory.glob("[0-9a-f]*.json")
                ),
                key=lambda chunk: (
                    chunk.point_index,
                    chunk.dataset_id,
                    chunk.operation_id,
                ),
            )
        )
        return tuple(
            MeasurementRecord.model_validate(chunk.record.model_dump(mode="python"))
            for chunk in chunks
        )

    def _measurement_path(self, chunk: MeasurementRecordChunk) -> Path:
        digest = stable_content_hash(
            {
                "dataset_id": chunk.dataset_id,
                "logical_point_id": chunk.logical_point_id,
                "point_index": chunk.point_index,
            }
        )
        return self._directory / f"{digest}.json"


class LocalCollectionRepository:
    """Commit readbacks and resolve them later for ingress or recovery."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = LocalRunLayout.from_workspace(workspace)
        self._directory = layout.run_dir(run_id) / EXECUTION_READBACKS_DIR
        self._thread_lock = Lock()

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        if chunk.run_id != self._run_id:
            msg = "collection chunk run_id does not match its repository"
            raise ExecutionJournalError(msg)
        durable_chunk = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        content_hash = durable_chunk.content_hash
        path = self._collection_path(durable_chunk.operation_id)
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
        return CollectionChunkReceipt(
            operation_id=durable_chunk.operation_id,
            ref=f"{EXECUTION_READBACKS_DIR}/{path.name}",
            content_hash=content_hash,
        )

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        durable_receipt = CollectionChunkReceipt.model_validate(
            receipt.model_dump(mode="json")
        )
        path = self._collection_path(durable_receipt.operation_id)
        expected_ref = f"{EXECUTION_READBACKS_DIR}/{path.name}"
        if durable_receipt.ref != expected_ref:
            msg = "collection receipt ref does not match its operation path"
            raise ExecutionJournalError(msg)
        with self._thread_lock:
            try:
                chunk = read_model(path, CollectionChunk)
            except Exception as error:
                msg = f"failed to resolve collection readback: {error}"
                raise ExecutionJournalError(msg) from error
        if (
            chunk.run_id != self._run_id
            or chunk.operation_id != durable_receipt.operation_id
            or chunk.content_hash != durable_receipt.content_hash
        ):
            msg = "collection receipt does not resolve to its exact committed chunk"
            raise ExecutionJournalError(msg)
        return CollectionChunk.model_validate(chunk.model_dump(mode="json"))

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        """Return canonical receipts for every committed local readback."""

        if not self._directory.is_dir():
            return ()
        with self._thread_lock:
            chunks = tuple(
                sorted(
                    (
                        read_model(path, CollectionChunk)
                        for path in self._directory.glob("*.json")
                    ),
                    key=lambda chunk: chunk.operation_id,
                )
            )
        return tuple(
            CollectionChunkReceipt(
                operation_id=chunk.operation_id,
                ref=(
                    f"{EXECUTION_READBACKS_DIR}/"
                    f"{self._collection_path(chunk.operation_id).name}"
                ),
                content_hash=chunk.content_hash,
            )
            for chunk in chunks
        )

    def _collection_path(self, operation_id: str) -> Path:
        operation_digest = sha256(operation_id.encode("utf-8")).hexdigest()
        return self._directory / f"{operation_digest}.json"


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
    "LocalCollectionRepository",
    "LocalExecutionJournal",
    "LocalMeasurementRecordCommitter",
    "LocalPayloadEvidenceCommitter",
    "LocalResourceLeaseManager",
]
