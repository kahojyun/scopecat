"""Exception boundaries for expected Scopecat operation failures."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from scopecat.models.run import RunCertainty, RunOutcome
from scopecat.problems import Problem, ProblemImpact


class ScopecatError(Exception):
    """Base error for Scopecat failures."""


class ProblemFailure(ScopecatError):
    """Base for expected failures described by structured blocking problems."""

    def __init__(self, problems: Sequence[Problem]) -> None:
        selected = tuple(problems)
        if not selected:
            msg = "problem failure requires at least one problem"
            raise ValueError(msg)
        if not any(problem.impact is ProblemImpact.BLOCKING for problem in selected):
            msg = "problem failure requires at least one blocking problem"
            raise ValueError(msg)
        self.problems = selected
        summary = "; ".join(
            f"{problem.code}: {problem.message}" for problem in selected
        )
        super().__init__(summary)


class CheckFailed(ProblemFailure):
    """A definition, authoring, configuration, or planning check failed."""


class OperationFailure(ProblemFailure):
    """An expected non-check operation failed."""


class NotFound(OperationFailure):
    """A requested domain object does not exist."""


class Conflict(OperationFailure):
    """The requested operation conflicts with current state."""


class DataIntegrityError(OperationFailure):
    """Persisted or external data violates its integrity contract."""


class StorageError(OperationFailure):
    """Storage could not complete the requested operation."""


class ProviderContractError(OperationFailure):
    """A provider violates or cannot satisfy its declared contract."""


class RunFailure(ProblemFailure):
    """Base for terminal run failures with a durable outcome."""

    def __init__(self, *, run_id: str, outcome: RunOutcome) -> None:
        if outcome.run_id != run_id:
            msg = "run failure outcome does not belong to the selected run"
            raise ValueError(msg)
        self.run_id = run_id
        self.outcome = outcome
        super().__init__(outcome.problems)


class RunFailed(RunFailure):
    """A run reached a known failed terminal outcome."""

    def __init__(self, *, run_id: str, outcome: RunOutcome) -> None:
        if outcome.result != "failed" or outcome.certainty != "known":
            msg = "RunFailed requires a known failed outcome"
            raise ValueError(msg)
        super().__init__(run_id=run_id, outcome=outcome)


class RunIndeterminate(RunFailure):
    """A run terminated without establishing the outcome of every effect."""

    def __init__(self, *, run_id: str, outcome: RunOutcome) -> None:
        if outcome.certainty != "indeterminate":
            msg = "RunIndeterminate requires an indeterminate outcome"
            raise ValueError(msg)
        super().__init__(run_id=run_id, outcome=outcome)


RunPersistenceRetry = Literal["safe", "after_reconciliation", "not_retryable"]


class RunPersistenceError(StorageError):
    """Terminal run evidence could not be fully committed after execution."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        phase: str,
        reconciliation: str,
        retry: RunPersistenceRetry,
        certainty: RunCertainty,
        committed_refs: Sequence[str],
        pending_ref: str,
    ) -> None:
        if not run_id or not phase or not reconciliation:
            msg = "run persistence context fields must be non-empty"
            raise ValueError(msg)
        selected_refs = tuple(committed_refs)
        if any(not ref for ref in selected_refs):
            msg = "committed run evidence refs must be non-empty"
            raise ValueError(msg)
        if len(selected_refs) != len(set(selected_refs)):
            msg = "committed run evidence refs must be unique"
            raise ValueError(msg)
        if not pending_ref:
            msg = "pending run evidence ref must be non-empty"
            raise ValueError(msg)
        self.run_id = run_id
        self.phase = phase
        self.reconciliation = reconciliation
        self.retry = retry
        self.certainty = certainty
        self.committed_refs = selected_refs
        self.pending_ref = pending_ref
        super().__init__(problems)


__all__ = [
    "CheckFailed",
    "Conflict",
    "DataIntegrityError",
    "NotFound",
    "OperationFailure",
    "ProblemFailure",
    "ProviderContractError",
    "RunFailed",
    "RunFailure",
    "RunIndeterminate",
    "RunPersistenceError",
    "RunPersistenceRetry",
    "ScopecatError",
    "StorageError",
]
