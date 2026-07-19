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

from scopecat.adapters.filesystem.io import (
    ensure_durable_directory,
    read_model,
    write_model,
    write_model_if_absent,
)
from scopecat.adapters.filesystem.layout import FilesystemRunLayout
from scopecat.execution.ports.journal import ExecutionJournalError
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.datasets import MEASUREMENT_DATASET_KIND
from scopecat.measurements.results import MeasurementRecord
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionJournalEntry,
    PayloadEvidence,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.runs.refs import (
    EXECUTION_JOURNAL_DIR,
    EXECUTION_PAYLOADS_DIR,
    EXECUTION_READBACKS_DIR,
    dataset_content_ref,
)


class FilesystemExecutionJournal:
    """Append immutable operation transitions as individually atomic files."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        self._layout = FilesystemRunLayout.from_workspace(workspace)
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
                write_model(
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


class FilesystemMeasurementDatasetRepository:
    """Append immutable ranges and seal one canonical dataset."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = FilesystemRunLayout.from_workspace(workspace)
        self._run_directory = layout.run_dir(run_id)
        self._thread_lock = Lock()

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        durable = MeasurementDatasetAppend.model_validate(
            append.model_dump(mode="python")
        )
        if durable.run_id != self._run_id:
            msg = "measurement run_id does not match its execution committer"
            raise ExecutionJournalError(msg)
        dataset_dir = self._dataset_directory(
            durable.run_id,
            durable.dataset_id,
        )
        path = dataset_dir / "chunks" / f"{durable.start_index:020d}.json"
        index_path = dataset_dir / "index" / f"{durable.start_index:020d}.json"
        with self._thread_lock:
            try:
                ensure_durable_directory(dataset_dir)
                if (dataset_dir / "seal.json").exists():
                    raise ExecutionJournalError("measurement dataset is already sealed")
                if path.exists():
                    existing = read_model(path, MeasurementDatasetAppend)
                    if existing.content_hash != durable.content_hash:
                        raise ExecutionJournalError(
                            "measurement dataset append already has different content"
                        )
                else:
                    indices = self._read_indices(dataset_dir)
                    if durable.start_index != sum(
                        item.record_count for item in indices
                    ):
                        raise ExecutionJournalError(
                            "measurement dataset append is not the next "
                            "contiguous range"
                        )
                    if any(
                        item.recording_contract_fingerprint
                        != durable.recording_contract_fingerprint
                        for item in indices
                    ):
                        raise ExecutionJournalError(
                            "measurement dataset append changed its contract"
                        )
                    write_model(path, durable)
                index = MeasurementDatasetAppendIndex.from_append(durable)
                if not write_model_if_absent(index_path, index):
                    existing_index = read_model(
                        index_path,
                        MeasurementDatasetAppendIndex,
                    )
                    if existing_index != index:
                        raise ExecutionJournalError(
                            "measurement dataset append index has different content"
                        )
                dataset_ref = self._dataset_ref(
                    dataset_dir,
                    f"chunks/{path.name}",
                )
                return MeasurementDatasetReceipt(
                    operation_id=durable.operation_id,
                    dataset_content_hash=durable.content_hash,
                    dataset_ref=dataset_ref,
                )
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                msg = f"failed to append measurement dataset: {error}"
                raise ExecutionJournalError(msg) from error

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        durable = MeasurementDatasetSeal.model_validate(seal.model_dump(mode="python"))
        if durable.run_id != self._run_id:
            raise ExecutionJournalError(
                "measurement run_id does not match its execution committer"
            )
        dataset_dir = self._dataset_directory(durable.run_id, durable.dataset_id)
        path = dataset_dir / "seal.json"
        with self._thread_lock:
            try:
                ensure_durable_directory(dataset_dir)
                if path.exists():
                    existing = read_model(path, MeasurementDatasetSeal)
                    if existing.content_hash != durable.content_hash:
                        raise ExecutionJournalError(
                            "measurement dataset seal already has different content"
                        )
                else:
                    indices = self._read_indices(dataset_dir)
                    if (
                        sum(item.record_count for item in indices)
                        != durable.point_count
                    ):
                        raise ExecutionJournalError(
                            "measurement dataset seal point count is incomplete"
                        )
                    if any(
                        item.recording_contract_fingerprint
                        != durable.recording_contract_fingerprint
                        for item in indices
                    ):
                        raise ExecutionJournalError(
                            "measurement dataset seal changed its contract"
                        )
                    actual_hash = measurement_dataset_content_hash(
                        recording_contract_fingerprint=(
                            durable.recording_contract_fingerprint
                        ),
                        append_content_hashes=tuple(
                            item.append_content_hash for item in indices
                        ),
                    )
                    if actual_hash != durable.dataset_content_hash:
                        raise ExecutionJournalError(
                            "measurement dataset seal content hash does not "
                            "match appends"
                        )
                    write_model(path, durable)
                return MeasurementDatasetReceipt(
                    operation_id=durable.operation_id,
                    dataset_content_hash=durable.dataset_content_hash,
                    dataset_ref=self._dataset_ref(dataset_dir, path.name),
                )
            except Exception as error:
                if isinstance(error, ExecutionJournalError):
                    raise
                raise ExecutionJournalError(
                    f"failed to seal measurement dataset: {error}"
                ) from error

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        if not self._run_directory.is_dir():
            return ()
        appends = tuple(
            append
            for dataset_dir in self._dataset_directories()
            for append in self._read_appends(dataset_dir)
        )
        return tuple(
            MeasurementRecord.model_validate(record.model_dump(mode="python"))
            for append in appends
            for record in append.records
        )

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]:
        return tuple(
            index
            for dataset_dir in self._dataset_directories()
            for index in self._read_indices(dataset_dir)
        )

    def _dataset_directory(self, run_id: str, dataset_id: str) -> Path:
        if run_id != self._run_id:
            raise ExecutionJournalError("measurement dataset run_id is foreign")
        return self._run_directory / dataset_content_ref(
            dataset_id=dataset_id,
            kind=MEASUREMENT_DATASET_KIND,
        )

    def _read_appends(self, dataset_dir: Path) -> tuple[MeasurementDatasetAppend, ...]:
        return tuple(
            read_model(path, MeasurementDatasetAppend)
            for path in sorted((dataset_dir / "chunks").glob("[0-9]*.json"))
        )

    def _read_indices(
        self,
        dataset_dir: Path,
    ) -> tuple[MeasurementDatasetAppendIndex, ...]:
        return tuple(
            read_model(path, MeasurementDatasetAppendIndex)
            for path in sorted((dataset_dir / "index").glob("[0-9]*.json"))
        )

    def _dataset_directories(self) -> tuple[Path, ...]:
        data_root = self._run_directory / "data" / MEASUREMENT_DATASET_KIND
        if not data_root.is_dir():
            return ()
        return tuple(sorted(path for path in data_root.iterdir() if path.is_dir()))

    def _dataset_ref(self, dataset_dir: Path, name: str) -> str:
        return (dataset_dir / name).relative_to(self._run_directory).as_posix()


class FilesystemCollectionRepository:
    """Commit readbacks and resolve them later for ingress or recovery."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = FilesystemRunLayout.from_workspace(workspace)
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


class FilesystemPayloadEvidenceCommitter:
    """Commit structural payload evidence before it enters a driver command."""

    def __init__(self, workspace: str | Path, *, run_id: str) -> None:
        self._run_id = run_id
        layout = FilesystemRunLayout.from_workspace(workspace)
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


class FilesystemResourceLeaseManager:
    """Hold canonical whole-run file leases for instruments/channels/groups."""

    def __init__(self, workspace: str | Path) -> None:
        layout = FilesystemRunLayout.from_workspace(workspace)
        self._directory = layout.workspace / "execution-resources"

    @contextmanager
    def acquire(self, claims: tuple[ResourceClaim, ...]) -> Generator[None]:
        ensure_durable_directory(self._directory)
        lock_files: list[BufferedRandom] = []
        ordered = sorted(set(claims), key=lambda claim: (claim.kind, claim.id))
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
