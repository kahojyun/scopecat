"""Effect intent and evidence ledger persistence contract for SDK runtimes."""

from typing import Protocol

from scopecat.records.execution_journal import ExecutionTransition


class ExecutionJournal(Protocol):
    """Mandatory crash-containment ledger around external effects."""

    def claim(self, entry: ExecutionTransition) -> ExecutionTransition:
        """Commit a new effect intent, rejecting an existing operation."""
        ...

    def append(self, entry: ExecutionTransition) -> ExecutionTransition: ...


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
    """Append one exact durable transition and return its ledger identity."""

    return _validate_committed_transition(transition, journal.append(transition))


def _validate_committed_transition(
    transition: ExecutionTransition,
    committed: ExecutionTransition,
) -> ExecutionTransition:
    expected = transition.model_dump(mode="json", exclude={"sequence", "timestamp"})
    if committed.sequence is None:
        raise ValueError("execution journal did not assign a durable sequence")
    actual = committed.model_dump(mode="json", exclude={"sequence", "timestamp"})
    if actual != expected:
        raise ValueError("execution journal changed transition identity or evidence")
    return committed.model_copy(deep=True)


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be committed."""
