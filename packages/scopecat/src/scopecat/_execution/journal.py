"""Required operation journal boundary for structured execution."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from scopecat._content_identity import model_wire_content_hash
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import InstrumentReadback
from scopecat.results import MeasurementRecord

type ExecutionEffect = Literal[
    "pure",
    "read",
    "state_write",
    "acquisition",
    "lifecycle",
    "persistence",
]
type JournalEntryState = Literal[
    "started",
    "completed",
    "failed",
    "unknown",
    "skipped",
]


class ExecutionJournalEntry(BaseModel):
    """Immutable evidence for one execution operation transition."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_version: Literal["scopecat.execution_journal_entry.v1"] = (
        "scopecat.execution_journal_entry.v1"
    )
    sequence: int | None = Field(default=None, ge=0)
    run_id: str
    operation_id: str
    stage: str
    effect: ExecutionEffect
    state: JournalEntryState
    attempt: int = Field(default=1, ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    point_index: int | None = Field(default=None, ge=0)
    instrument_id: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ExecutionJournal(Protocol):
    """Mandatory journal used before and after external effects."""

    def append(self, entry: ExecutionJournalEntry) -> ExecutionJournalEntry: ...


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be committed."""


class MeasurementCommitter(Protocol):
    """Durably commit one point result before the engine advances."""

    def commit(self, measurement: MeasurementRecord) -> None: ...


class CollectionChunk(BaseModel):
    """Immutable durable receipt for one successful driver collection call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.collection_chunk.v1"] = (
        "scopecat.collection_chunk.v1"
    )
    run_id: str
    operation_id: str
    attempt: int = Field(default=1, ge=1)
    point_index: int = Field(ge=0)
    instrument_id: str
    readback: InstrumentReadback

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class CommittedCollectionChunk(BaseModel):
    """Reference returned only after a collection chunk is durably committed."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    content_hash: str


class CollectionCommitter(Protocol):
    """Persist a readback before its collection operation can complete."""

    def commit(self, chunk: CollectionChunk) -> CommittedCollectionChunk: ...


class PayloadEvidence(BaseModel):
    """Durable structural evidence for one transient command payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.payload_evidence.v1"] = (
        "scopecat.payload_evidence.v1"
    )
    run_id: str
    operation_id: str
    point_index: int = Field(ge=0)
    payload_id: str
    schema_id: str
    content_hash: str
    fingerprint: Any


class CommittedPayloadEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    content_hash: str


class PayloadEvidenceCommitter(Protocol):
    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence: ...


class MemoryExecutionJournal:
    """Deterministic in-memory journal for tests and embedded execution."""

    def __init__(self) -> None:
        self._entries: list[ExecutionJournalEntry] = []
        self._lock = Lock()

    @property
    def entries(self) -> tuple[ExecutionJournalEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def append(self, entry: ExecutionJournalEntry) -> ExecutionJournalEntry:
        with self._lock:
            committed = entry.model_copy(
                update={
                    "sequence": len(self._entries),
                    "timestamp": datetime.now(UTC),
                }
            )
            self._entries.append(committed)
            return committed


class NullExecutionJournal:
    """Explicit opt-out intended only for pure engine unit tests."""

    def append(self, entry: ExecutionJournalEntry) -> ExecutionJournalEntry:
        return entry


class MemoryMeasurementCommitter:
    """In-memory point committer used by engine unit tests."""

    def __init__(self) -> None:
        self._measurements: list[MeasurementRecord] = []

    @property
    def measurements(self) -> tuple[MeasurementRecord, ...]:
        return tuple(self._measurements)

    def commit(self, measurement: MeasurementRecord) -> None:
        durable_measurement = MeasurementRecord.model_validate(
            measurement.model_dump(mode="json")
        )
        existing = next(
            (
                item
                for item in self._measurements
                if item.point_index == durable_measurement.point_index
            ),
            None,
        )
        if existing is not None and model_wire_content_hash(
            existing
        ) != model_wire_content_hash(durable_measurement):
            msg = (
                f"measurement for point {durable_measurement.point_index} "
                "is already committed"
            )
            raise ExecutionJournalError(msg)
        if existing is None:
            self._measurements.append(durable_measurement)


class MemoryCollectionCommitter:
    """In-memory collection receipt store for interpreter tests."""

    def __init__(self) -> None:
        self._chunks: dict[str, CollectionChunk] = {}

    @property
    def chunks(self) -> tuple[CollectionChunk, ...]:
        return tuple(self._chunks.values())

    def commit(self, chunk: CollectionChunk) -> CommittedCollectionChunk:
        durable_chunk = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        digest = durable_chunk.content_hash
        existing = self._chunks.get(durable_chunk.operation_id)
        if existing is not None and existing.content_hash != digest:
            msg = (
                f"collection operation {durable_chunk.operation_id} already has a chunk"
            )
            raise ExecutionJournalError(msg)
        self._chunks[durable_chunk.operation_id] = durable_chunk
        return CommittedCollectionChunk(
            ref=f"memory/collection/{digest}.json",
            content_hash=digest,
        )


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


__all__ = [
    "CollectionChunk",
    "CollectionCommitter",
    "CommittedCollectionChunk",
    "CommittedPayloadEvidence",
    "ExecutionEffect",
    "ExecutionJournal",
    "ExecutionJournalEntry",
    "ExecutionJournalError",
    "JournalEntryState",
    "MeasurementCommitter",
    "MemoryCollectionCommitter",
    "MemoryExecutionJournal",
    "MemoryMeasurementCommitter",
    "MemoryPayloadEvidenceCommitter",
    "NullExecutionJournal",
    "PayloadEvidence",
    "PayloadEvidenceCommitter",
]
