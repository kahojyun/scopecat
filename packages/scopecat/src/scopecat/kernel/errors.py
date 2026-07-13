"""Exception boundaries for expected Scopecat operation failures."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from scopecat.kernel.problems import Problem, ProblemImpact
from scopecat.records.run import RunCertainty, RunOutcome


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


class MeasurementTransformExecutionError(OperationFailure):
    """A selected host measurement transform could not execute its contract."""


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
DomainRuntimeRetry = Literal["safe", "after_reconciliation", "not_retryable"]


class DomainSubmissionUncertainty(Protocol):
    """Runtime-resolvable boundary for a sealed submission uncertainty."""

    @property
    def submission_id(self) -> object: ...

    @property
    def reason(self) -> str: ...

    @property
    def submit_call_attempt(self) -> int: ...

    @property
    def job_id_hint(self) -> str | None: ...

    @property
    def problems(self) -> tuple[Problem, ...]: ...


class DomainSubmissionAbsence(Protocol):
    """Runtime-resolvable boundary for sealed definitive absence evidence."""

    @property
    def submission_id(self) -> object: ...

    @property
    def origin(self) -> str: ...

    @property
    def receipt(self) -> object: ...


class MeasurementRecordReceiptEvidence(Protocol):
    """Runtime-resolvable boundary for one durable measurement-record receipt."""

    @property
    def operation_id(self) -> str: ...

    @property
    def chunk_content_hash(self) -> str: ...

    @property
    def record_ref(self) -> str: ...


class MeasurementRecordingError(StorageError):
    """A projected record write or its journal evidence did not complete cleanly."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        dataset_id: str,
        recording_contract_fingerprint: str,
        operation_id: str,
        attempt: int,
        logical_point_id: str,
        point_index: int,
        committed_prefix: Sequence[MeasurementRecordReceiptEvidence],
        pending_receipt: MeasurementRecordReceiptEvidence | None,
        write_may_have_completed: bool,
        reconciliation: str,
    ) -> None:
        if (
            not run_id
            or not dataset_id
            or not recording_contract_fingerprint
            or not operation_id
            or not logical_point_id
        ):
            msg = "measurement recording identity fields must be non-empty"
            raise ValueError(msg)
        if type(attempt) is not int or attempt < 1:
            msg = "measurement recording attempt must be a positive integer"
            raise ValueError(msg)
        if isinstance(point_index, bool) or point_index < 0:
            msg = "measurement recording point index must be a non-negative integer"
            raise ValueError(msg)
        if not reconciliation:
            msg = "measurement recording error requires reconciliation guidance"
            raise ValueError(msg)
        selected_prefix = tuple(committed_prefix)
        operation_ids = tuple(receipt.operation_id for receipt in selected_prefix)
        if any(not value for value in operation_ids) or len(operation_ids) != len(
            set(operation_ids)
        ):
            msg = "committed measurement receipt operation ids must be unique"
            raise ValueError(msg)
        record_refs = tuple(receipt.record_ref for receipt in selected_prefix)
        if any(not value for value in record_refs) or len(record_refs) != len(
            set(record_refs)
        ):
            msg = "committed measurement receipt refs must be unique"
            raise ValueError(msg)
        if pending_receipt is not None and not pending_receipt.operation_id:
            msg = "pending measurement receipt operation id must be non-empty"
            raise ValueError(msg)
        self.run_id = run_id
        self.dataset_id = dataset_id
        self.recording_contract_fingerprint = recording_contract_fingerprint
        self.operation_id = operation_id
        self.attempt = attempt
        self.logical_point_id = logical_point_id
        self.point_index = point_index
        self.committed_prefix = selected_prefix
        self.pending_receipt = pending_receipt
        self.write_may_have_completed = write_may_have_completed
        self.retry: Literal["safe"] = "safe"
        self.reconciliation = reconciliation
        super().__init__(problems)


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


class DomainRuntimeFailure(OperationFailure):
    """Expected failure at one host-visible domain-runtime boundary."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        phase: Literal["submit", "fetch", "reconcile"],
        retry: DomainRuntimeRetry,
        reconciliation: str,
        job_id: str | None = None,
    ) -> None:
        if not run_id or not operation_id or not invocation_id or not submission_key:
            msg = "domain runtime failure identity fields must be non-empty"
            raise ValueError(msg)
        if isinstance(attempt, bool) or attempt < 1:
            msg = "domain runtime failure attempt must be a positive integer"
            raise ValueError(msg)
        if not reconciliation:
            msg = "domain runtime failure requires reconciliation guidance"
            raise ValueError(msg)
        if job_id is not None and not job_id:
            msg = "domain runtime failure job_id must be non-empty when present"
            raise ValueError(msg)
        self.run_id = run_id
        self.operation_id = operation_id
        self.attempt = attempt
        self.invocation_id = invocation_id
        self.submission_key = submission_key
        self.phase = phase
        self.retry = retry
        self.reconciliation = reconciliation
        self.job_id = job_id
        super().__init__(problems)


class DomainSubmissionIndeterminate(DomainRuntimeFailure):
    """Submission may have reached the target and must be reconciled."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        job_id: str | None = None,
        uncertainty: DomainSubmissionUncertainty,
    ) -> None:
        super().__init__(
            problems,
            run_id=run_id,
            operation_id=operation_id,
            attempt=attempt,
            invocation_id=invocation_id,
            submission_key=submission_key,
            phase="submit",
            retry="after_reconciliation",
            reconciliation=(
                "reconcile before creating another submission-key generation"
            ),
            job_id=job_id,
        )
        self.uncertainty = uncertainty


class DomainSubmissionFailed(DomainRuntimeFailure):
    """The target established that the invocation was not submitted."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        absence: DomainSubmissionAbsence,
    ) -> None:
        super().__init__(
            problems,
            run_id=run_id,
            operation_id=operation_id,
            attempt=attempt,
            invocation_id=invocation_id,
            submission_key=submission_key,
            phase="submit",
            retry="safe",
            reconciliation=(
                "retry the same key or use the absence to create a new generation"
            ),
        )
        self.absence = absence


class DomainFetchFailed(DomainRuntimeFailure):
    """Fetching a known submitted job failed without changing target state."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        job_id: str,
        certainty: RunCertainty,
    ) -> None:
        self.certainty = certainty
        super().__init__(
            problems,
            run_id=run_id,
            operation_id=operation_id,
            attempt=attempt,
            invocation_id=invocation_id,
            submission_key=submission_key,
            phase="fetch",
            retry="safe",
            reconciliation="retry fetch using the known submitted job",
            job_id=job_id,
        )


class DomainReconciliationFailed(DomainRuntimeFailure):
    """Reading the target's submission state failed and may be retried."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        job_id: str | None = None,
        uncertainty: DomainSubmissionUncertainty,
    ) -> None:
        super().__init__(
            problems,
            run_id=run_id,
            operation_id=operation_id,
            attempt=attempt,
            invocation_id=invocation_id,
            submission_key=submission_key,
            phase="reconcile",
            retry="safe",
            reconciliation="retry reconciliation using the same submission key",
            job_id=job_id,
        )
        self.uncertainty = uncertainty


class DomainRuntimePersistenceError(StorageError):
    """Domain effect intent or receipt evidence could not be journaled."""

    def __init__(
        self,
        problems: Sequence[Problem],
        *,
        run_id: str,
        operation_id: str,
        attempt: int,
        invocation_id: str,
        submission_key: str,
        phase: str,
        retry: DomainRuntimeRetry,
        certainty: RunCertainty,
        reconciliation: str,
        job_id: str | None = None,
        uncertainty: DomainSubmissionUncertainty | None = None,
    ) -> None:
        if (
            not run_id
            or not operation_id
            or not invocation_id
            or not submission_key
            or not phase
        ):
            msg = "domain persistence context fields must be non-empty"
            raise ValueError(msg)
        if isinstance(attempt, bool) or attempt < 1:
            msg = "domain persistence attempt must be a positive integer"
            raise ValueError(msg)
        if not reconciliation:
            msg = "domain persistence error requires reconciliation guidance"
            raise ValueError(msg)
        if job_id is not None and not job_id:
            msg = "domain persistence job_id must be non-empty when present"
            raise ValueError(msg)
        self.run_id = run_id
        self.operation_id = operation_id
        self.attempt = attempt
        self.invocation_id = invocation_id
        self.submission_key = submission_key
        self.phase = phase
        self.retry = retry
        self.certainty = certainty
        self.reconciliation = reconciliation
        self.job_id = job_id
        self.uncertainty = uncertainty
        super().__init__(problems)


__all__ = [
    "CheckFailed",
    "Conflict",
    "DataIntegrityError",
    "DomainFetchFailed",
    "DomainReconciliationFailed",
    "DomainRuntimeFailure",
    "DomainRuntimePersistenceError",
    "DomainRuntimeRetry",
    "DomainSubmissionAbsence",
    "DomainSubmissionFailed",
    "DomainSubmissionIndeterminate",
    "DomainSubmissionUncertainty",
    "MeasurementRecordReceiptEvidence",
    "MeasurementRecordingError",
    "MeasurementTransformExecutionError",
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
