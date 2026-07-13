"""In-memory implementations of execution persistence ports."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from scopecat.execution.ports.journal import ExecutionJournalError
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
)


class MemoryExecutionJournal:
    """Deterministic in-memory journal for tests and embedded execution."""

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
        self._chunks: dict[str, CollectionChunk] = {}
        self._receipts: dict[str, CollectionChunkReceipt] = {}
        self._lock = Lock()

    @property
    def chunks(self) -> tuple[CollectionChunk, ...]:
        with self._lock:
            return tuple(
                CollectionChunk.model_validate(chunk.model_dump(mode="json"))
                for chunk in self._chunks.values()
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
            existing = self._chunks.get(durable.operation_id)
            if existing is not None and existing.content_hash != digest:
                msg = f"collection operation {durable.operation_id} already has a chunk"
                raise ExecutionJournalError(msg)
            if existing is None:
                self._chunks[durable.operation_id] = durable
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
            stored_chunk = self._chunks.get(durable.operation_id)
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


class MemoryMeasurementRecordCommitter:
    """Deterministic in-memory measurement record committer."""

    def __init__(self) -> None:
        self._chunks: dict[str, MeasurementRecordChunk] = {}
        self._receipts: dict[str, MeasurementRecordReceipt] = {}
        self._lock = Lock()

    @property
    def chunks(self) -> tuple[MeasurementRecordChunk, ...]:
        with self._lock:
            return tuple(_measurement_chunk(chunk) for chunk in self._chunks.values())

    @property
    def receipts(self) -> tuple[MeasurementRecordReceipt, ...]:
        with self._lock:
            return tuple(
                _measurement_receipt(receipt) for receipt in self._receipts.values()
            )

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        with self._lock:
            chunks = sorted(
                self._chunks.values(),
                key=lambda chunk: (
                    chunk.point_index,
                    chunk.dataset_id,
                    chunk.operation_id,
                ),
            )
            return tuple(
                MeasurementRecord.model_validate(chunk.record.model_dump(mode="python"))
                for chunk in chunks
            )

    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        durable = _measurement_chunk(chunk)
        with self._lock:
            existing = self._chunks.get(durable.operation_id)
            if existing is not None and existing.content_hash != durable.content_hash:
                msg = (
                    f"measurement record operation {durable.operation_id} already "
                    "has different content"
                )
                raise ExecutionJournalError(msg)
            if existing is None:
                self._chunks[durable.operation_id] = durable
                self._receipts[durable.operation_id] = MeasurementRecordReceipt(
                    operation_id=durable.operation_id,
                    chunk_content_hash=durable.content_hash,
                    record_ref=(
                        "memory/measurement-records/"
                        f"{durable.operation_id.removeprefix('measurement-record:')}"
                        ".json"
                    ),
                )
            return _measurement_receipt(self._receipts[durable.operation_id])


def _measurement_chunk(chunk: MeasurementRecordChunk) -> MeasurementRecordChunk:
    return MeasurementRecordChunk.model_validate(chunk.model_dump(mode="python"))


def _measurement_receipt(
    receipt: MeasurementRecordReceipt,
) -> MeasurementRecordReceipt:
    return MeasurementRecordReceipt.model_validate(receipt.model_dump(mode="json"))


__all__ = [
    "MemoryCollectionRepository",
    "MemoryExecutionJournal",
    "MemoryMeasurementRecordCommitter",
    "MemoryPayloadEvidenceCommitter",
]
