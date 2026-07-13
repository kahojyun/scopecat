"""Durable effect and recovery journal boundary for structured execution."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scopecat._content_identity import model_wire_content_hash
from scopecat.instruments.sdk import InstrumentReadback
from scopecat.problems import Problem

type ExecutionEffect = Literal[
    "action",
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
type ExecutionStage = Literal[
    "provide_instruments",
    "setup_cleanup",
    "setup_terminal_readback",
    "initial_readback",
    "point",
    "compute",
    "apply_state",
    "action",
    "collect",
    "record_measurement",
    "abort",
    "cleanup",
    "terminal_readback",
    "domain_submit",
    "domain_fetch",
    "domain_reconcile",
]


class ExecutionTransition(BaseModel):
    """Immutable carrier shared by effect evidence and live observation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.execution_transition.v3"] = (
        "scopecat.execution_transition.v3"
    )
    sequence: int | None = Field(default=None, ge=0)
    run_id: str
    operation_id: str
    stage: ExecutionStage
    effect: ExecutionEffect
    state: JournalEntryState
    attempt: int = Field(default=1, ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    point_index: int | None = Field(default=None, ge=0)
    instrument_id: str | None = None
    problems: tuple[Problem, ...] = ()
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


# The local storage adapter still consumes this runtime class name.  It is an
# internal spelling, not an additional wire schema.
ExecutionJournalEntry = ExecutionTransition


class ExecutionJournal(Protocol):
    """Mandatory journal used before and after external effects."""

    def append(self, entry: ExecutionTransition) -> ExecutionTransition: ...


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be committed."""


class CollectionChunk(BaseModel):
    """Durable payload for one successful driver collection call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.collection_chunk.v2"] = (
        "scopecat.collection_chunk.v2"
    )
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    command_content_hash: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    readback: InstrumentReadback

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class CollectionChunkReceipt(BaseModel):
    """Immutable reference to a chunk resolvable by its collection repository."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    operation_id: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class CollectionRepository(Protocol):
    """Persist readbacks and resolve them later for ingress or recovery."""

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt: ...

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk: ...


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
        durable_chunk = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        digest = durable_chunk.content_hash
        with self._lock:
            existing = self._chunks.get(durable_chunk.operation_id)
            if existing is not None and existing.content_hash != digest:
                msg = (
                    f"collection operation {durable_chunk.operation_id} already "
                    "has a chunk"
                )
                raise ExecutionJournalError(msg)
            if existing is None:
                receipt = CollectionChunkReceipt(
                    operation_id=durable_chunk.operation_id,
                    ref=f"memory/collection/{digest}.json",
                    content_hash=digest,
                )
                self._chunks[durable_chunk.operation_id] = durable_chunk
                self._receipts[durable_chunk.operation_id] = receipt
            return CollectionChunkReceipt.model_validate(
                self._receipts[durable_chunk.operation_id].model_dump(mode="json")
            )

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        durable_receipt = CollectionChunkReceipt.model_validate(
            receipt.model_dump(mode="json")
        )
        with self._lock:
            stored_receipt = self._receipts.get(durable_receipt.operation_id)
            stored_chunk = self._chunks.get(durable_receipt.operation_id)
            if stored_receipt != durable_receipt or stored_chunk is None:
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


__all__ = [
    "CollectionChunk",
    "CollectionChunkReceipt",
    "CollectionRepository",
    "CommittedPayloadEvidence",
    "ExecutionEffect",
    "ExecutionJournal",
    "ExecutionJournalEntry",
    "ExecutionJournalError",
    "ExecutionStage",
    "ExecutionTransition",
    "JournalEntryState",
    "MemoryCollectionRepository",
    "MemoryExecutionJournal",
    "MemoryPayloadEvidenceCommitter",
    "PayloadEvidence",
    "PayloadEvidenceCommitter",
]
