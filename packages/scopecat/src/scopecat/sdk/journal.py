"""Effect intent and evidence ledger persistence contract for SDK runtimes."""

from typing import Protocol

from scopecat.records.execution_journal import ExecutionTransition


class ExecutionJournal(Protocol):
    """Mandatory crash-containment ledger around external effects."""

    def append(self, entry: ExecutionTransition) -> ExecutionTransition: ...


def commit_transition(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
) -> ExecutionTransition:
    """Append one exact durable transition and return its ledger identity."""

    expected = transition.model_dump(mode="json", exclude={"sequence", "timestamp"})
    committed = journal.append(transition)
    if committed.sequence is None:
        raise ValueError("execution journal did not assign a durable sequence")
    actual = committed.model_dump(mode="json", exclude={"sequence", "timestamp"})
    if actual != expected:
        raise ValueError("execution journal changed transition identity or evidence")
    return committed.model_copy(deep=True)


class ExecutionJournalError(RuntimeError):
    """Raised when operation intent or receipt evidence cannot be committed."""
