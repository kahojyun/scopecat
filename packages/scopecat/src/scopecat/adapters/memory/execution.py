"""In-memory implementations of execution persistence ports."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING

from scopecat.execution.ports.journal import ExecutionJournalError
from scopecat.measurements.datasets import MEASUREMENT_DATASET_KIND
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
    measurement_dataset_content_hash,
)
from scopecat.runs.refs import dataset_content_ref

if TYPE_CHECKING:
    from scopecat.runs.repository import RunRepository


class MemoryExecutionJournal:
    """Deterministic in-memory journal for in-process tests."""

    def __init__(self) -> None:
        self._entries: list[ExecutionTransition] = []
        self._lock = Lock()

    @property
    def entries(self) -> tuple[ExecutionTransition, ...]:
        with self._lock:
            return tuple(self._entries)

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        with self._lock:
            committed = entry.model_copy(
                update={
                    "sequence": len(self._entries),
                    "timestamp": datetime.now(UTC),
                },
                deep=True,
            )
            self._entries.append(committed)
            return committed


class MemoryCollectionRepository:
    """In-memory collection repository for interpreter tests."""

    def __init__(self) -> None:
        self._writes: dict[str, CollectionChunk] = {}
        self._receipts: dict[str, CollectionChunkReceipt] = {}
        self._lock = Lock()

    @property
    def chunks(self) -> tuple[CollectionChunk, ...]:
        with self._lock:
            return tuple(
                CollectionChunk.model_validate(chunk.model_dump(mode="json"))
                for chunk in self._writes.values()
            )

    @property
    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        with self._lock:
            return tuple(
                CollectionChunkReceipt.model_validate(receipt.model_dump(mode="json"))
                for receipt in self._receipts.values()
            )

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        durable = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        digest = durable.content_hash
        with self._lock:
            existing = self._writes.get(durable.operation_id)
            if existing is not None and existing.content_hash != digest:
                msg = f"collection operation {durable.operation_id} already has a chunk"
                raise ExecutionJournalError(msg)
            if existing is None:
                self._writes[durable.operation_id] = durable
                self._receipts[durable.operation_id] = CollectionChunkReceipt(
                    operation_id=durable.operation_id,
                    ref=f"memory/collection/{digest}.json",
                    content_hash=digest,
                )
            return CollectionChunkReceipt.model_validate(
                self._receipts[durable.operation_id].model_dump(mode="json")
            )

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        durable = CollectionChunkReceipt.model_validate(receipt.model_dump(mode="json"))
        with self._lock:
            stored_receipt = self._receipts.get(durable.operation_id)
            stored_chunk = self._writes.get(durable.operation_id)
            if stored_receipt != durable or stored_chunk is None:
                msg = "collection receipt is not backed by this repository"
                raise ExecutionJournalError(msg)
            return CollectionChunk.model_validate(stored_chunk.model_dump(mode="json"))


class MemoryPayloadEvidenceCommitter:
    """In-memory payload evidence store for interpreter tests."""

    def __init__(self) -> None:
        self._evidence: dict[str, PayloadEvidence] = {}

    @property
    def evidence(self) -> tuple[PayloadEvidence, ...]:
        return tuple(self._evidence.values())

    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence:
        existing = self._evidence.get(evidence.operation_id)
        if existing is not None and existing != evidence:
            msg = f"compute operation {evidence.operation_id} has different payload"
            raise ExecutionJournalError(msg)
        self._evidence[evidence.operation_id] = evidence.model_copy(deep=True)
        return CommittedPayloadEvidence(
            ref=f"memory/payload/{evidence.content_hash}.json",
            content_hash=evidence.content_hash,
        )


class MemoryMeasurementDatasetRepository:
    """Deterministic in-memory measurement record committer."""

    def __init__(
        self,
        *,
        run_id: str | None = None,
        run_repository: RunRepository | None = None,
    ) -> None:
        self._appends: dict[str, MeasurementDatasetAppend] = {}
        self._indices: dict[str, MeasurementDatasetAppendIndex] = {}
        self._seals: dict[tuple[str, str], MeasurementDatasetSeal] = {}
        self._receipts: dict[str, MeasurementDatasetReceipt] = {}
        self._lock = Lock()
        self._run_id = run_id
        self._run_repository = run_repository

    @property
    def appends(self) -> tuple[MeasurementDatasetAppend, ...]:
        with self._lock:
            return tuple(_measurement_append(item) for item in self._appends.values())

    @property
    def receipts(self) -> tuple[MeasurementDatasetReceipt, ...]:
        with self._lock:
            return tuple(
                _measurement_receipt(receipt) for receipt in self._receipts.values()
            )

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        with self._lock:
            return tuple(
                MeasurementRecord.model_validate(record.model_dump(mode="python"))
                for append in self._appends.values()
                for record in append.records
            )

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]:
        with self._lock:
            return tuple(self._indices.values())

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        durable = _measurement_append(append)
        with self._lock:
            key = (durable.run_id, durable.dataset_id)
            if key in self._seals:
                raise ExecutionJournalError("measurement dataset is already sealed")
            existing = self._appends.get(durable.operation_id)
            if existing is not None and existing.content_hash != durable.content_hash:
                msg = (
                    f"measurement append operation {durable.operation_id} already "
                    "has different content"
                )
                raise ExecutionJournalError(msg)
            if existing is None:
                selected = tuple(
                    item
                    for item in self._appends.values()
                    if (item.run_id, item.dataset_id) == key
                )
                if durable.start_index != sum(len(item.records) for item in selected):
                    raise ExecutionJournalError(
                        "measurement dataset append is not the next contiguous range"
                    )
                if any(
                    item.recording_contract_fingerprint
                    != durable.recording_contract_fingerprint
                    for item in selected
                ):
                    raise ExecutionJournalError(
                        "measurement dataset append changed its contract"
                    )
                self._appends[durable.operation_id] = durable
                self._indices[durable.operation_id] = (
                    MeasurementDatasetAppendIndex.from_append(durable)
                )
                self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                    operation_id=durable.operation_id,
                    dataset_content_hash=durable.content_hash,
                    dataset_ref=(
                        "memory/measurement-appends/"
                        f"{durable.operation_id.removeprefix('measurement-dataset-append:')}"
                        ".json"
                    ),
                )
                self._publish_model(
                    durable.dataset_id,
                    f"chunks/{durable.start_index:020d}.json",
                    durable,
                )
            return _measurement_receipt(self._receipts[durable.operation_id])

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        durable = MeasurementDatasetSeal.model_validate(seal.model_dump(mode="python"))
        key = (durable.run_id, durable.dataset_id)
        with self._lock:
            existing = self._seals.get(key)
            if existing is not None and existing.content_hash != durable.content_hash:
                raise ExecutionJournalError(
                    "measurement dataset seal already has different content"
                )
            if existing is None:
                indices = tuple(
                    item
                    for operation_id, item in self._indices.items()
                    if (
                        self._appends[operation_id].run_id,
                        self._appends[operation_id].dataset_id,
                    )
                    == key
                )
                if sum(item.record_count for item in indices) != durable.point_count:
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
                    recording_contract_fingerprint=durable.recording_contract_fingerprint,
                    append_content_hashes=tuple(
                        item.append_content_hash for item in indices
                    ),
                )
                if actual_hash != durable.dataset_content_hash:
                    raise ExecutionJournalError(
                        "measurement dataset seal content hash does not match appends"
                    )
                self._seals[key] = durable
                self._receipts[durable.operation_id] = MeasurementDatasetReceipt(
                    operation_id=durable.operation_id,
                    dataset_content_hash=durable.dataset_content_hash,
                    dataset_ref=(
                        "memory/measurement-datasets/"
                        f"{durable.operation_id.removeprefix('measurement-dataset-seal:')}"
                        ".json"
                    ),
                )
                self._publish_model(durable.dataset_id, "seal.json", durable)
            return _measurement_receipt(self._receipts[durable.operation_id])

    def _publish_model(
        self,
        dataset_id: str,
        suffix: str,
        model: MeasurementDatasetAppend | MeasurementDatasetSeal,
    ) -> None:
        if self._run_repository is None or self._run_id is None:
            return
        ref = dataset_content_ref(
            dataset_id=dataset_id,
            kind=MEASUREMENT_DATASET_KIND,
        )
        self._run_repository.write_model(
            self._run_id,
            f"{ref}/{suffix}",
            model,
        )


def _measurement_append(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend.model_validate(append.model_dump(mode="python"))


def _measurement_receipt(
    receipt: MeasurementDatasetReceipt,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt.model_validate(receipt.model_dump(mode="json"))
