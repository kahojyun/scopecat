"""Process-local effect sequencing for SDK runtimes."""

from threading import Lock
from typing import Protocol

from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
)


class ExecutionJournal(Protocol):
    """Sequence effect attempts and reject duplicate operations within one run."""

    def claim(self, entry: ExecutionTransition) -> ExecutionTransition:
        """Claim a new effect operation, rejecting an existing operation."""
        ...

    def append(self, entry: ExecutionTransition) -> ExecutionTransition: ...


class ProcessExecutionJournal:
    """Keep effect ordering and duplicate protection for one executor process.

    A daemon or executor restart ends the old execution attempt, so this journal
    deliberately does not imply restart recovery. Durable measurement prefixes,
    terminal outcomes, and hardware-unknown events are stored by their owning
    services instead.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_sequence = 0
        self._claims: set[str] = set()
        self._entries_by_hash: dict[str, ExecutionTransition] = {}

    def claim(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.state != "started":
            raise ExecutionJournalError(
                "only a started transition can claim an execution operation"
            )
        with self._lock:
            if entry.operation_id in self._claims:
                raise ExecutionJournalError(
                    f"execution operation {entry.operation_id!r} is already claimed"
                )
            committed = self._append_locked(entry)
            self._claims.add(entry.operation_id)
            return committed.model_copy(deep=True)

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        with self._lock:
            committed = self._append_locked(entry)
            return committed.model_copy(deep=True)

    def _append_locked(self, entry: ExecutionTransition) -> ExecutionTransition:
        content_hash = execution_transition_content_hash(entry)
        existing = self._entries_by_hash.get(content_hash)
        if existing is not None:
            return existing
        committed = entry.model_copy(
            update={"sequence": self._next_sequence},
            deep=True,
        )
        self._next_sequence += 1
        self._entries_by_hash[content_hash] = committed
        return committed


def claim_transition(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
) -> ExecutionTransition:
    """Atomically claim a new operation before its first external effect."""

    if transition.state != "started":
        raise ValueError("only a started transition can claim an operation")
    return _validate_committed_transition(transition, journal.claim(transition))


def commit_transition(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
) -> ExecutionTransition:
    """Append one exact transition and return its journal identity."""

    return _validate_committed_transition(transition, journal.append(transition))


def _validate_committed_transition(
    transition: ExecutionTransition,
    committed: ExecutionTransition,
) -> ExecutionTransition:
    expected = transition.model_dump(mode="json", exclude={"sequence", "timestamp"})
    if committed.sequence is None:
        raise ValueError("execution journal did not assign a sequence")
    actual = committed.model_dump(mode="json", exclude={"sequence", "timestamp"})
    if actual != expected:
        raise ValueError("execution journal changed transition identity or evidence")
    return committed.model_copy(deep=True)


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be journaled."""
