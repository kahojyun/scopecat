"""Execution journal, readback, and payload persistence ports."""

from typing import Protocol

from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)


class ExecutionJournal(Protocol):
    """Mandatory journal used before and after external effects."""

    def append(self, entry: ExecutionTransition) -> ExecutionTransition: ...


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be committed."""


class CollectionRepository(Protocol):
    """Persist readbacks and resolve them later for ingress or recovery."""

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt: ...

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk: ...


class PayloadEvidenceCommitter(Protocol):
    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence: ...


__all__ = [
    "CollectionRepository",
    "ExecutionJournal",
    "ExecutionJournalError",
    "PayloadEvidenceCommitter",
]
