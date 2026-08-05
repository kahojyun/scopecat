"""Synchronous correlated effects for one closed domain invocation.

Core journals a deterministic submit intent, accepts one correlated job receipt,
then performs one complete result fetch. A provider may report success, a known
rejection, or an unknown outcome.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainRuntimePersistenceError,
    DomainSubmissionFailed,
    DomainSubmissionIndeterminate,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
)
from scopecat.sdk.journal import ExecutionJournal
from scopecat.sdk.journal import commit_transition as _commit_transition
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.sdk.runtime_problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)


class DomainSubmissionId(BaseModel):
    """Deterministic idempotency identity for one run operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    logical_compute_node_id: str
    invocation_id: str
    intent_fingerprint: str

    @field_validator(
        "run_id",
        "logical_compute_node_id",
        "invocation_id",
        "intent_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("domain submission identity fields must be non-empty")
        return value

    @property
    def submission_key(self) -> str:
        return _submission_key(
            run_id=self.run_id,
            logical_compute_node_id=self.logical_compute_node_id,
            invocation_id=self.invocation_id,
            intent_fingerprint=self.intent_fingerprint,
        )

    @property
    def submit_operation_id(self) -> str:
        return f"domain:{self.submission_key}:submit"

    @property
    def fetch_operation_id(self) -> str:
        return f"domain:{self.submission_key}:fetch"


class DomainSubmitReceipt(BaseModel):
    """Provider evidence for the single synchronous submit call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submission_key: str
    status: Literal["submitted", "not_submitted", "unknown"]
    job_id: str | None = None
    problems: tuple[Problem, ...] = ()

    @field_validator("submission_key")
    @classmethod
    def validate_submission_key(cls, value: str) -> str:
        if not value:
            raise ValueError("domain submit receipts require a submission key")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> DomainSubmitReceipt:
        if self.status == "submitted":
            if not self.job_id or self.problems:
                raise ValueError(
                    "submitted domain receipts require a job and no problems"
                )
        elif not self.problems or (
            self.status == "not_submitted" and self.job_id is not None
        ):
            raise ValueError(
                "negative domain submit receipts require consistent problem evidence"
            )
        elif self.job_id == "":
            raise ValueError("domain submit job ids must be non-empty when present")
        return self


class DomainFetchReceipt(BaseModel):
    """Provider evidence for the single complete result fetch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submission_key: str
    job_id: str
    status: Literal["fetched", "not_found", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    problems: tuple[Problem, ...] = ()

    @field_validator("submission_key")
    @classmethod
    def validate_submission_key(cls, value: str) -> str:
        if not value:
            raise ValueError("domain fetch receipts require a submission key")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> DomainFetchReceipt:
        if not self.job_id:
            raise ValueError("domain fetch receipts require a job id")
        has_result = (
            self.result_fingerprint is not None and self.result_count is not None
        )
        if self.status == "fetched":
            if not has_result or not self.result_fingerprint or self.problems:
                raise ValueError(
                    "fetched domain receipts require result evidence and no problems"
                )
        elif (
            has_result
            or self.result_fingerprint is not None
            or self.result_count is not None
            or not self.problems
        ):
            raise ValueError(
                "negative domain fetch receipts require problem evidence and no result"
            )
        return self


@dataclass(frozen=True, slots=True)
class DomainFetchResult[ResultT]:
    """A successful result paired with the provider evidence that covers it."""

    receipt: DomainFetchReceipt
    result: ResultT = field(repr=False)

    def __post_init__(self) -> None:
        if self.receipt.status != "fetched":
            raise ValueError("domain results require fetched receipt evidence")


class DomainRuntime[PayloadT, ResultT](Protocol):
    """Synchronous target ABI with receipt-only negative fetch outcomes."""

    def submit(
        self,
        submission_key: str,
        payload: PayloadT,
        /,
    ) -> DomainSubmitReceipt: ...

    def fetch(
        self,
        submission_key: str,
        job_id: str,
        /,
    ) -> DomainFetchReceipt | DomainFetchResult[ResultT]: ...


def plan_domain_submission[
    ResultAddressT: Hashable,
    PayloadT,
](
    invocation: ClosedDomainInvocation[ResultAddressT, PayloadT],
    *,
    run_id: str,
    logical_compute_node_id: str,
) -> DomainSubmissionId:
    intent = invocation.intent
    return DomainSubmissionId(
        run_id=run_id,
        logical_compute_node_id=logical_compute_node_id,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
    )


def submit_domain_invocation[
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    runtime: DomainRuntime[PayloadT, ResultT],
    invocation: ClosedDomainInvocation[ResultAddressT, PayloadT],
    submission_id: DomainSubmissionId,
    *,
    journal: ExecutionJournal,
) -> str:
    intent = invocation.intent
    _validate_submission_id(intent, submission_id)
    operation_id = submission_id.submit_operation_id
    started = _transition(
        submission_id,
        operation_id,
        "domain_submit",
        "acquisition",
        "started",
        _intent_evidence(intent, submission_id),
    )
    _append_before_effect(journal, started, submission_id, "submit", None)
    try:
        receipt = runtime.submit(
            submission_id.submission_key,
            invocation.payload,
        )
    except Exception as error:
        problem = problem_from_exception(
            "domain_submit_raised",
            "domain runtime raised while submitting the invocation",
            run_id=submission_id.run_id,
            operation_id=operation_id,
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            submission_id,
            "submit",
            "indeterminate",
            None,
            (problem,),
        )
        raise DomainSubmissionIndeterminate(
            (problem,),
            run_id=submission_id.run_id,
            operation_id=operation_id,
            invocation_id=intent.invocation_id,
            submission_key=submission_id.submission_key,
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, started, submission_id)
        raise
    try:
        _require_submission_key(receipt.submission_key, expected=submission_id)
    except Exception as error:
        problem = _provider_problem(
            submission_id,
            operation_id,
            "domain_submit_receipt_invalid",
            "domain runtime returned an invalid or uncorrelated submit receipt",
            error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            submission_id,
            "submit",
            "indeterminate",
            None,
            (problem,),
        )
        raise DomainSubmissionIndeterminate(
            (problem,),
            run_id=submission_id.run_id,
            operation_id=operation_id,
            invocation_id=intent.invocation_id,
            submission_key=submission_id.submission_key,
        ) from error
    problems = contextualize_problems(
        receipt.problems, run_id=submission_id.run_id, operation_id=operation_id
    )
    evidence = {**started.evidence, **_receipt_evidence(receipt)}
    if receipt.status == "submitted":
        _append_after_effect(
            journal,
            started.model_copy(
                update={
                    "state": "completed",
                    "problems": problems,
                    "evidence": evidence,
                }
            ),
            submission_id,
            "submit",
            "known",
            receipt.job_id,
            problems,
        )
        return cast("str", receipt.job_id)
    state: Literal["failed", "unknown"] = (
        "failed" if receipt.status == "not_submitted" else "unknown"
    )
    certainty: Literal["known", "indeterminate"] = (
        "known" if state == "failed" else "indeterminate"
    )
    _append_after_effect(
        journal,
        started.model_copy(
            update={"state": state, "problems": problems, "evidence": evidence}
        ),
        submission_id,
        "submit",
        certainty,
        receipt.job_id,
        problems,
    )
    if state == "failed":
        raise DomainSubmissionFailed(
            problems,
            run_id=submission_id.run_id,
            operation_id=operation_id,
            invocation_id=intent.invocation_id,
            submission_key=submission_id.submission_key,
        )
    raise DomainSubmissionIndeterminate(
        problems,
        run_id=submission_id.run_id,
        operation_id=operation_id,
        invocation_id=intent.invocation_id,
        submission_key=submission_id.submission_key,
        job_id=receipt.job_id,
    )


def fetch_domain_invocation[PayloadT, ResultT](
    runtime: DomainRuntime[PayloadT, ResultT],
    intent: DomainInvocationIntent,
    submission_id: DomainSubmissionId,
    job_id: str,
    *,
    journal: ExecutionJournal,
) -> DomainFetchResult[ResultT]:
    _validate_submission_id(intent, submission_id)
    operation_id = submission_id.fetch_operation_id
    evidence = {**_intent_evidence(intent, submission_id), "job_id": job_id}
    started = _transition(
        submission_id, operation_id, "domain_fetch", "read", "started", evidence
    )
    _append_before_effect(journal, started, submission_id, "fetch", job_id)
    try:
        outcome = runtime.fetch(submission_id.submission_key, job_id)
    except Exception as error:
        problem = problem_from_exception(
            "domain_fetch_raised",
            "domain runtime raised while fetching the result",
            run_id=submission_id.run_id,
            operation_id=operation_id,
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            submission_id,
            "fetch",
            "indeterminate",
            job_id,
            (problem,),
        )
        raise DomainFetchFailed(
            (problem,),
            run_id=submission_id.run_id,
            operation_id=operation_id,
            invocation_id=intent.invocation_id,
            submission_key=submission_id.submission_key,
            job_id=job_id,
            certainty="indeterminate",
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, started, submission_id)
        raise
    try:
        receipt = outcome.receipt if isinstance(outcome, DomainFetchResult) else outcome
        _require_submission_key(receipt.submission_key, expected=submission_id)
        if receipt.job_id != job_id:
            raise ValueError("domain fetch receipt belongs to another job")
        if receipt.status == "fetched" and not isinstance(outcome, DomainFetchResult):
            raise ValueError("fetched domain receipts require a result")
    except Exception as error:
        problem = _provider_problem(
            submission_id,
            operation_id,
            "domain_fetch_receipt_invalid",
            "domain runtime returned an invalid or uncorrelated fetch receipt",
            error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            submission_id,
            "fetch",
            "indeterminate",
            job_id,
            (problem,),
        )
        raise DomainFetchFailed(
            (problem,),
            run_id=submission_id.run_id,
            operation_id=operation_id,
            invocation_id=intent.invocation_id,
            submission_key=submission_id.submission_key,
            job_id=job_id,
            certainty="indeterminate",
        ) from error
    problems = contextualize_problems(
        receipt.problems, run_id=submission_id.run_id, operation_id=operation_id
    )
    evidence = {**started.evidence, **_receipt_evidence(receipt)}
    if isinstance(outcome, DomainFetchResult):
        _append_after_effect(
            journal,
            started.model_copy(
                update={
                    "state": "completed",
                    "problems": problems,
                    "evidence": evidence,
                }
            ),
            submission_id,
            "fetch",
            "known",
            job_id,
            problems,
        )
        return outcome
    certainty: Literal["known", "indeterminate"] = (
        "known" if receipt.status == "not_found" else "indeterminate"
    )
    state: Literal["failed", "unknown"] = (
        "failed" if certainty == "known" else "unknown"
    )
    _append_after_effect(
        journal,
        started.model_copy(
            update={"state": state, "problems": problems, "evidence": evidence}
        ),
        submission_id,
        "fetch",
        certainty,
        job_id,
        problems,
    )
    raise DomainFetchFailed(
        problems,
        run_id=submission_id.run_id,
        operation_id=operation_id,
        invocation_id=intent.invocation_id,
        submission_key=submission_id.submission_key,
        job_id=job_id,
        certainty=certainty,
    )


def _submission_key(
    *,
    run_id: str,
    logical_compute_node_id: str,
    invocation_id: str,
    intent_fingerprint: str,
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.domain_submission_key.v2",
            "run_id": run_id,
            "logical_compute_node_id": logical_compute_node_id,
            "invocation_id": invocation_id,
            "intent_fingerprint": intent_fingerprint,
        }
    )


def _validate_submission_id(
    intent: DomainInvocationIntent, submission_id: DomainSubmissionId
) -> None:
    if (
        submission_id.invocation_id != intent.invocation_id
        or submission_id.intent_fingerprint != intent.intent_fingerprint
    ):
        raise ValueError("domain submission identity does not match its invocation")


def _require_submission_key(
    actual: str,
    *,
    expected: DomainSubmissionId,
) -> None:
    if actual != expected.submission_key:
        raise ValueError("domain receipt belongs to another submission")


def _transition(
    submission_id: DomainSubmissionId,
    operation_id: str,
    stage: Literal["domain_submit", "domain_fetch"],
    effect: Literal["acquisition", "read"],
    state: Literal["started", "completed", "failed", "unknown"],
    evidence: Mapping[str, JsonValue],
) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=submission_id.run_id,
        operation_id=operation_id,
        stage=stage,
        effect=effect,
        state=state,
        evidence=dict(evidence),
    )


def _intent_evidence(
    intent: DomainInvocationIntent, submission_id: DomainSubmissionId
) -> dict[str, JsonValue]:
    return {
        "invocation_intent": intent.model_dump(mode="json"),
        "logical_compute_node_id": submission_id.logical_compute_node_id,
        "submission_key": submission_id.submission_key,
    }


def _receipt_evidence(receipt: BaseModel) -> dict[str, JsonValue]:
    return {"receipt": receipt.model_dump(mode="json")}


def _append_before_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    submission_id: DomainSubmissionId,
    phase: Literal["submit", "fetch"],
    job_id: str | None,
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        problem = problem_from_exception(
            "domain_runtime_intent_persistence_failed",
            f"failed to persist domain {phase} intent before the runtime call",
            run_id=submission_id.run_id,
            operation_id=transition.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
        )
        raise DomainRuntimePersistenceError(
            (problem,),
            run_id=submission_id.run_id,
            operation_id=transition.operation_id,
            invocation_id=submission_id.invocation_id,
            submission_key=submission_id.submission_key,
            phase=phase,
            certainty="known",
            job_id=job_id,
        ) from error


def _append_after_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    submission_id: DomainSubmissionId,
    phase: Literal["submit", "fetch"],
    certainty: Literal["known", "indeterminate"],
    job_id: str | None,
    prior_problems: Sequence[Problem],
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        problem = problem_from_exception(
            "domain_runtime_receipt_persistence_failed",
            f"failed to persist domain {phase} result after the runtime call",
            run_id=submission_id.run_id,
            operation_id=transition.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
        )
        raise DomainRuntimePersistenceError(
            (*prior_problems, problem),
            run_id=submission_id.run_id,
            operation_id=transition.operation_id,
            invocation_id=submission_id.invocation_id,
            submission_key=submission_id.submission_key,
            phase=phase,
            certainty=certainty,
            job_id=job_id,
        ) from error


def _append_interruption_best_effort(
    journal: ExecutionJournal,
    started: ExecutionTransition,
    submission_id: DomainSubmissionId,
) -> None:
    problem = runtime_problem(
        "domain_runtime_interrupted",
        "domain runtime call was interrupted before returning a receipt",
        run_id=submission_id.run_id,
        operation_id=started.operation_id,
    )
    with suppress(BaseException):
        _commit_transition(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
        )


def _provider_problem(
    submission_id: DomainSubmissionId,
    operation_id: str,
    code: str,
    message: str,
    error: Exception,
) -> Problem:
    return runtime_problem(
        code,
        message,
        run_id=submission_id.run_id,
        operation_id=operation_id,
        details={"error_type": f"{type(error).__module__}.{type(error).__qualname__}"},
    )


__all__ = [
    "DomainFetchReceipt",
    "DomainFetchResult",
    "DomainRuntime",
    "DomainSubmissionId",
    "DomainSubmitReceipt",
    "fetch_domain_invocation",
    "plan_domain_submission",
    "submit_domain_invocation",
]
