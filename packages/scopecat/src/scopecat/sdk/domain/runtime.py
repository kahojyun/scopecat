"""Correlated host-side effects for one closed domain invocation.

This is a three-state submission protocol, not a scheduler.  Submit consumes a
closed transient payload and yields a sealed known submission.  An uncertain
submit yields a sealed recovery token; only that token may be reconciled.
Fetch consumes a known submission and returns either a sealed correlated
payload or a sealed pending read.  Domain-internal control remains
adapter-owned; adapters still validate provider-specific payload integrity.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
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

from scopecat.execution.ports.journal import ExecutionJournal
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainReconciliationFailed,
    DomainRuntimePersistenceError,
    DomainSubmissionAbsence,
    DomainSubmissionFailed,
    DomainSubmissionIndeterminate,
    DomainSubmissionUncertainty,
    ProviderContractError,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
)


class DomainSubmissionId(BaseModel):
    """Durable identity of one authorized idempotency-key generation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.domain_submission_id.v1"] = (
        "scopecat.domain_submission_id.v1"
    )
    run_id: str
    semantic_operation_id: str
    generation: int = Field(default=1, ge=1)
    invocation_id: str
    intent_fingerprint: str
    submission_key: str

    @field_validator(
        "run_id",
        "semantic_operation_id",
        "invocation_id",
        "intent_fingerprint",
        "submission_key",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "domain submission identity fields must be non-empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_submission_key(self) -> DomainSubmissionId:
        expected = _submission_key(
            run_id=self.run_id,
            semantic_operation_id=self.semantic_operation_id,
            generation=self.generation,
            invocation_id=self.invocation_id,
            intent_fingerprint=self.intent_fingerprint,
        )
        if self.submission_key != expected:
            msg = "domain submission key does not cover its complete generation"
            raise ValueError(msg)
        return self

    @property
    def submit_operation_id(self) -> str:
        return f"domain:{self.submission_key}:submit"

    @property
    def fetch_operation_id(self) -> str:
        return f"domain:{self.submission_key}:fetch"

    @property
    def reconcile_operation_id(self) -> str:
        return f"domain:{self.submission_key}:reconcile"


class DomainReceiptIdentity(BaseModel):
    """Target and invocation identity echoed by every runtime receipt."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.domain_receipt_identity.v1"] = (
        "scopecat.domain_receipt_identity.v1"
    )
    submission_key: str
    invocation_id: str
    intent_fingerprint: str
    target_id: str
    compiler_id: str
    capability_fingerprint: str
    artifact_id: str
    artifact_fingerprint: str

    @field_validator(
        "submission_key",
        "invocation_id",
        "intent_fingerprint",
        "target_id",
        "compiler_id",
        "capability_fingerprint",
        "artifact_id",
        "artifact_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "domain receipt identity fields must be non-empty"
            raise ValueError(msg)
        return value


@dataclass(frozen=True, slots=True)
class DomainSubmitRequest[PayloadT]:
    """Provider request for one authorized submit attempt."""

    submission_id: DomainSubmissionId
    identity: DomainReceiptIdentity
    payload: PayloadT = field(repr=False)


@dataclass(frozen=True, slots=True)
class DomainFetchRequest:
    """Provider request for one repeatable known-job read."""

    submission_id: DomainSubmissionId
    identity: DomainReceiptIdentity
    job_id: str


@dataclass(frozen=True, slots=True)
class DomainReconcileRequest:
    """Provider request for one uncertain-submit lookup."""

    submission_id: DomainSubmissionId
    identity: DomainReceiptIdentity


class DomainSubmitReceipt(BaseModel):
    """Provider candidate reported after one idempotent submit call."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.domain_submit_receipt.v1"] = (
        "scopecat.domain_submit_receipt.v1"
    )
    identity: DomainReceiptIdentity
    status: Literal["submitted", "not_submitted", "unknown"]
    job_id: str | None = None
    problems: tuple[Problem, ...] = ()

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str | None) -> str | None:
        if value is not None and not value:
            msg = "domain submit receipt job_id must be non-empty when present"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> DomainSubmitReceipt:
        blocking = has_blocking_problems(self.problems)
        if self.status == "submitted":
            if self.job_id is None:
                msg = "a submitted domain receipt requires a job_id"
                raise ValueError(msg)
            if blocking:
                msg = "a submitted domain receipt cannot contain blocking problems"
                raise ValueError(msg)
            return self
        if not blocking:
            msg = "a negative or unknown domain submit requires a blocking problem"
            raise ValueError(msg)
        if self.status == "not_submitted" and self.job_id is not None:
            msg = "a not_submitted domain receipt cannot contain a job_id"
            raise ValueError(msg)
        return self


class DomainFetchReceipt(BaseModel):
    """Payload-free provider evidence from one repeatable job-result read."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.domain_fetch_receipt.v1"] = (
        "scopecat.domain_fetch_receipt.v1"
    )
    identity: DomainReceiptIdentity
    job_id: str
    status: Literal["fetched", "pending", "not_found", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    problems: tuple[Problem, ...] = ()

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str) -> str:
        if not value:
            msg = "domain fetch receipt job_id must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("result_fingerprint")
    @classmethod
    def validate_result_fingerprint(cls, value: str | None) -> str | None:
        if value is not None and not value:
            msg = "domain result fingerprint must be non-empty when present"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> DomainFetchReceipt:
        blocking = has_blocking_problems(self.problems)
        has_result_evidence = (
            self.result_fingerprint is not None and self.result_count is not None
        )
        if self.status == "fetched":
            if not has_result_evidence:
                msg = "a fetched domain receipt requires result evidence"
                raise ValueError(msg)
            if blocking:
                msg = "a fetched domain receipt cannot contain blocking problems"
                raise ValueError(msg)
            return self
        if self.result_fingerprint is not None or self.result_count is not None:
            msg = "a non-fetched domain receipt cannot contain result evidence"
            raise ValueError(msg)
        if self.status == "pending":
            if blocking:
                msg = "a pending domain fetch cannot contain blocking problems"
                raise ValueError(msg)
            return self
        if not blocking:
            msg = "a negative or unknown domain fetch requires a blocking problem"
            raise ValueError(msg)
        return self


class DomainReconcileReceipt(BaseModel):
    """Provider candidate from one read-only submission reconciliation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.domain_reconcile_receipt.v1"] = (
        "scopecat.domain_reconcile_receipt.v1"
    )
    identity: DomainReceiptIdentity
    status: Literal["absent", "submitted", "completed", "unknown"]
    job_id: str | None = None
    problems: tuple[Problem, ...] = ()

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str | None) -> str | None:
        if value is not None and not value:
            msg = "domain reconcile receipt job_id must be non-empty when present"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_outcome_truth_table(self) -> DomainReconcileReceipt:
        blocking = has_blocking_problems(self.problems)
        if self.status == "absent":
            if self.job_id is not None or blocking:
                msg = "an absent domain submission has no job or blocking problem"
                raise ValueError(msg)
            return self
        if self.status in {"submitted", "completed"}:
            if self.job_id is None:
                msg = "a known domain submission requires a job_id"
                raise ValueError(msg)
            if blocking:
                msg = "a known domain submission cannot contain blocking problems"
                raise ValueError(msg)
            return self
        if not blocking:
            msg = "an unknown domain reconciliation requires a blocking problem"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True, init=False)
class KnownDomainSubmission:
    """Core-accepted job identity produced by submit or reconciliation."""

    submission_id: DomainSubmissionId
    receipt: DomainSubmitReceipt | DomainReconcileReceipt = field(repr=False)
    origin: Literal["submit", "reconcile"]

    def __init__(
        self,
        submission_id: DomainSubmissionId,
        receipt: DomainSubmitReceipt | DomainReconcileReceipt,
        origin: Literal["submit", "reconcile"],
    ) -> None:
        if origin == "submit":
            if not isinstance(receipt, DomainSubmitReceipt) or receipt.status != (
                "submitted"
            ):
                msg = "known submit state requires a submitted receipt"
                raise ValueError(msg)
        elif not isinstance(receipt, DomainReconcileReceipt) or receipt.status not in {
            "submitted",
            "completed",
        }:
            msg = "known reconcile state requires a known receipt"
            raise ValueError(msg)
        _require_state_identity(submission_id, receipt.identity)
        if receipt.job_id is None:
            msg = "known domain submissions require a job_id"
            raise ValueError(msg)
        object.__setattr__(self, "submission_id", submission_id)
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "origin", origin)

    @property
    def identity(self) -> DomainReceiptIdentity:
        return self.receipt.identity

    @property
    def job_id(self) -> str:
        assert self.receipt.job_id is not None
        return self.receipt.job_id

    @property
    def status(self) -> Literal["submitted", "completed"]:
        return (
            "completed"
            if isinstance(self.receipt, DomainReconcileReceipt)
            and self.receipt.status == "completed"
            else "submitted"
        )


@dataclass(frozen=True, slots=True, init=False)
class AbsentDomainSubmission:
    """Core-accepted proof authorizing a later submission attempt."""

    submission_id: DomainSubmissionId
    receipt: DomainSubmitReceipt | DomainReconcileReceipt = field(repr=False)
    origin: Literal["submit", "reconcile"]

    def __init__(
        self,
        submission_id: DomainSubmissionId,
        receipt: DomainSubmitReceipt | DomainReconcileReceipt,
        origin: Literal["submit", "reconcile"],
    ) -> None:
        valid = (
            origin == "submit"
            and isinstance(receipt, DomainSubmitReceipt)
            and receipt.status == "not_submitted"
        ) or (
            origin == "reconcile"
            and isinstance(receipt, DomainReconcileReceipt)
            and receipt.status == "absent"
        )
        if not valid:
            msg = "absent domain state requires definitive negative evidence"
            raise ValueError(msg)
        _require_state_identity(submission_id, receipt.identity)
        object.__setattr__(self, "submission_id", submission_id)
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "origin", origin)

    @property
    def identity(self) -> DomainReceiptIdentity:
        return self.receipt.identity


@dataclass(frozen=True, slots=True, init=False)
class UncertainDomainSubmission:
    """Sealed capability required to reconcile one indeterminate submit."""

    submission_id: DomainSubmissionId
    identity: DomainReceiptIdentity
    reason: Literal[
        "runtime_exception",
        "invalid_receipt",
        "unknown_receipt",
        "persistence",
    ]
    submit_call_attempt: int
    job_id_hint: str | None
    problems: tuple[Problem, ...] = field(repr=False)

    def __init__(
        self,
        submission_id: DomainSubmissionId,
        identity: DomainReceiptIdentity,
        *,
        reason: Literal[
            "runtime_exception",
            "invalid_receipt",
            "unknown_receipt",
            "persistence",
        ],
        submit_call_attempt: int,
        job_id_hint: str | None,
        problems: Sequence[Problem],
    ) -> None:
        selected_problems = tuple(problems)
        if not selected_problems or not has_blocking_problems(selected_problems):
            msg = "uncertain submissions require a blocking problem"
            raise ValueError(msg)
        if job_id_hint is not None and not job_id_hint:
            msg = "uncertain submission job hint must be non-empty when present"
            raise ValueError(msg)
        _require_positive_attempt(
            submit_call_attempt,
            label="uncertain domain submit call attempt",
        )
        _require_state_identity(submission_id, identity)
        object.__setattr__(self, "submission_id", submission_id)
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "submit_call_attempt", submit_call_attempt)
        object.__setattr__(self, "job_id_hint", job_id_hint)
        object.__setattr__(self, "problems", selected_problems)


@dataclass(frozen=True, slots=True)
class DomainFetchCandidate[ResultT]:
    """Untrusted adapter return awaiting core correlation checks."""

    receipt: DomainFetchReceipt
    result: ResultT | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == "fetched" and self.result is None:
            msg = "a fetched domain candidate requires its transient payload"
            raise ValueError(msg)
        if self.receipt.status != "fetched" and self.result is not None:
            msg = "a non-fetched domain candidate cannot contain a payload"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class CorrelatedDomainFetch[ResultT]:
    """Fetched payload correlated to one receipt and known provider job.

    This token proves host-level receipt identity and job correlation only.
    The adapter must still validate provider-specific payload fingerprints,
    counts, shapes, and value contracts before realizing Scopecat values.
    """

    receipt: DomainFetchReceipt
    result: ResultT = field(repr=False)


def _correlated_domain_fetch[ResultT](
    submission: KnownDomainSubmission,
    receipt: DomainFetchReceipt,
    result: ResultT,
) -> CorrelatedDomainFetch[ResultT]:
    """Mint one fetched payload after core has correlated its durable state."""

    if receipt.status != "fetched" or result is None:
        msg = "correlated domain fetches require a fetched payload"
        raise ValueError(msg)
    if receipt.identity != submission.identity or receipt.job_id != (submission.job_id):
        msg = "correlated domain fetch does not belong to its submission"
        raise ValueError(msg)
    return CorrelatedDomainFetch(
        receipt=receipt,
        result=result,
    )


@dataclass(frozen=True, slots=True, init=False)
class PendingDomainFetch:
    """Core-correlated normal non-terminal read of one known job."""

    submission: KnownDomainSubmission = field(repr=False)
    receipt: DomainFetchReceipt

    def __init__(
        self,
        submission: KnownDomainSubmission,
        receipt: DomainFetchReceipt,
    ) -> None:
        if receipt.status != "pending":
            msg = "pending domain fetches require a pending receipt"
            raise ValueError(msg)
        if receipt.identity != submission.identity or receipt.job_id != (
            submission.job_id
        ):
            msg = "pending domain fetch does not belong to its submission"
            raise ValueError(msg)
        object.__setattr__(self, "submission", submission)
        object.__setattr__(self, "receipt", receipt)


type DomainFetchOutcome[ResultT] = CorrelatedDomainFetch[ResultT] | PendingDomainFetch
type DomainSubmissionResolution = KnownDomainSubmission | AbsentDomainSubmission


class DomainRuntime[PayloadT, ResultT](Protocol):
    """Provider ABI receiving pre-correlated requests assembled by core."""

    def submit(
        self,
        request: DomainSubmitRequest[PayloadT],
    ) -> DomainSubmitReceipt: ...

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[ResultT]: ...

    def reconcile(
        self,
        request: DomainReconcileRequest,
    ) -> DomainReconcileReceipt: ...


def plan_domain_submission[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
](
    invocation: ClosedDomainInvocation[
        EntryAddressT,
        ResultAddressT,
        PayloadT,
    ],
    *,
    run_id: str,
    semantic_operation_id: str,
) -> DomainSubmissionId:
    """Create the only unconditionally authorized, initial submit attempt."""

    return _new_submission_id(
        invocation.intent,
        run_id=run_id,
        semantic_operation_id=semantic_operation_id,
        generation=1,
    )


def plan_domain_submission_retry(
    intent: DomainInvocationIntent,
    absence: DomainSubmissionAbsence,
) -> DomainSubmissionId:
    """Create a new key only from sealed definitive absence evidence."""

    sealed_absence = _require_absence(intent, absence)
    previous = sealed_absence.submission_id
    return _new_submission_id(
        intent,
        run_id=previous.run_id,
        semantic_operation_id=previous.semantic_operation_id,
        generation=previous.generation + 1,
    )


def domain_receipt_identity(
    submission_id: DomainSubmissionId,
    intent: DomainInvocationIntent,
) -> DomainReceiptIdentity:
    """Return the exact correlation identity every provider must echo."""

    _validate_submission_id(intent, submission_id)
    return DomainReceiptIdentity(
        submission_key=submission_id.submission_key,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
        target_id=intent.target_id,
        compiler_id=intent.compiler_id,
        capability_fingerprint=intent.capability_fingerprint,
        artifact_id=intent.artifact_id,
        artifact_fingerprint=intent.artifact_fingerprint,
    )


def _domain_submit_request[PayloadT](
    submission_id: DomainSubmissionId,
    intent: DomainInvocationIntent,
    payload: PayloadT,
) -> DomainSubmitRequest[PayloadT]:
    return DomainSubmitRequest(
        submission_id=submission_id,
        identity=domain_receipt_identity(submission_id, intent),
        payload=payload,
    )


def _domain_fetch_request(
    submission_id: DomainSubmissionId,
    intent: DomainInvocationIntent,
    *,
    job_id: str,
) -> DomainFetchRequest:
    return DomainFetchRequest(
        submission_id=submission_id,
        identity=domain_receipt_identity(submission_id, intent),
        job_id=job_id,
    )


def _domain_reconcile_request(
    submission_id: DomainSubmissionId,
    intent: DomainInvocationIntent,
) -> DomainReconcileRequest:
    return DomainReconcileRequest(
        submission_id=submission_id,
        identity=domain_receipt_identity(submission_id, intent),
    )


def submit_domain_invocation[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    runtime: DomainRuntime[PayloadT, ResultT],
    invocation: ClosedDomainInvocation[
        EntryAddressT,
        ResultAddressT,
        PayloadT,
    ],
    submission_id: DomainSubmissionId,
    *,
    journal: ExecutionJournal,
    retry_from: DomainSubmissionAbsence | None = None,
    submit_attempt: int = 1,
) -> KnownDomainSubmission:
    """Commit intent, perform submit, and accept only a correlated known job."""

    intent = invocation.intent
    attempt = submission_id
    _validate_submit_authorization(intent, attempt, retry_from=retry_from)
    _require_positive_attempt(submit_attempt, label="domain submit call attempt")
    operation_id = attempt.submit_operation_id
    started = _transition(
        intent,
        attempt,
        operation_id=operation_id,
        stage="domain_submit",
        effect="acquisition",
        state="started",
        transition_attempt=submit_attempt,
        evidence=_attempt_evidence(intent, attempt),
    )
    _append_before_effect(
        journal,
        started,
        intent=intent,
        attempt=attempt,
        phase="submit",
        job_id=None,
    )
    try:
        raw_receipt = runtime.submit(
            _domain_submit_request(attempt, intent, invocation.payload)
        )
    except Exception as error:
        problem = problem_from_exception(
            "domain_submit_raised",
            "domain runtime raised while submitting the invocation",
            run_id=attempt.run_id,
            operation_id=operation_id,
            error=error,
        )
        uncertainty = _uncertain_submission(
            intent,
            attempt,
            reason="runtime_exception",
            submit_call_attempt=submit_attempt,
            job_id_hint=None,
            problems=(problem,),
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="submit",
            retry="after_reconciliation",
            certainty="indeterminate",
            reconciliation=(
                "reconcile the sealed uncertain submission before another submit"
            ),
            job_id=None,
            prior_problems=(problem,),
            uncertainty=uncertainty,
        )
        raise DomainSubmissionIndeterminate(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=submit_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            uncertainty=uncertainty,
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, started, attempt=attempt)
        raise

    try:
        receipt = _normalize_submit_receipt(raw_receipt)
        _require_receipt_identity(
            receipt.identity,
            expected=domain_receipt_identity(attempt, intent),
        )
    except Exception as error:
        problem = _provider_problem(
            attempt,
            operation_id=operation_id,
            code="domain_submit_receipt_invalid",
            message="domain runtime returned an invalid or uncorrelated submit receipt",
            error=error,
        )
        uncertainty = _uncertain_submission(
            intent,
            attempt,
            reason="invalid_receipt",
            submit_call_attempt=submit_attempt,
            job_id_hint=None,
            problems=(problem,),
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="submit",
            retry="after_reconciliation",
            certainty="indeterminate",
            reconciliation=(
                "reconcile the sealed uncertain submission before another submit"
            ),
            job_id=None,
            prior_problems=(problem,),
            uncertainty=uncertainty,
        )
        raise DomainSubmissionIndeterminate(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=submit_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            uncertainty=uncertainty,
        ) from error

    receipt_problems = contextualize_problems(
        receipt.problems,
        run_id=attempt.run_id,
        operation_id=operation_id,
    )
    evidence = {**started.evidence, **_receipt_evidence(receipt)}
    if receipt.status == "submitted":
        known = KnownDomainSubmission(
            attempt,
            receipt,
            "submit",
        )
        _append_after_effect(
            journal,
            started.model_copy(
                update={
                    "state": "completed",
                    "problems": receipt_problems,
                    "evidence": evidence,
                }
            ),
            intent=intent,
            attempt=attempt,
            phase="submit",
            retry="after_reconciliation",
            certainty="indeterminate",
            reconciliation=(
                "reconcile the submission before trusting uncommitted job evidence"
            ),
            job_id=known.job_id,
            prior_problems=receipt_problems,
        )
        return known

    if receipt.status == "not_submitted":
        absence = AbsentDomainSubmission(
            attempt,
            receipt,
            "submit",
        )
        _append_after_effect(
            journal,
            started.model_copy(
                update={
                    "state": "failed",
                    "problems": receipt_problems,
                    "evidence": evidence,
                }
            ),
            intent=intent,
            attempt=attempt,
            phase="submit",
            retry="after_reconciliation",
            certainty="indeterminate",
            reconciliation=(
                "reconcile the sealed persistence uncertainty before using "
                "absence evidence"
            ),
            job_id=None,
            prior_problems=receipt_problems,
        )
        raise DomainSubmissionFailed(
            receipt_problems,
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=submit_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            absence=absence,
        )

    uncertainty = _uncertain_submission(
        intent,
        attempt,
        reason="unknown_receipt",
        submit_call_attempt=submit_attempt,
        job_id_hint=receipt.job_id,
        problems=receipt_problems,
    )
    _append_after_effect(
        journal,
        started.model_copy(
            update={
                "state": "unknown",
                "problems": receipt_problems,
                "evidence": evidence,
            }
        ),
        intent=intent,
        attempt=attempt,
        phase="submit",
        retry="after_reconciliation",
        certainty="indeterminate",
        reconciliation=(
            "reconcile the sealed uncertain submission before another submit"
        ),
        job_id=receipt.job_id,
        prior_problems=receipt_problems,
        uncertainty=uncertainty,
    )
    raise DomainSubmissionIndeterminate(
        receipt_problems,
        run_id=attempt.run_id,
        operation_id=operation_id,
        attempt=submit_attempt,
        invocation_id=attempt.invocation_id,
        submission_key=attempt.submission_key,
        job_id=receipt.job_id,
        uncertainty=uncertainty,
    )


def fetch_domain_invocation[PayloadT, ResultT](
    runtime: DomainRuntime[PayloadT, ResultT],
    intent: DomainInvocationIntent,
    submission: KnownDomainSubmission,
    *,
    journal: ExecutionJournal,
    fetch_attempt: int = 1,
) -> DomainFetchOutcome[ResultT]:
    """Repeatably read one sealed known job without needing its transient payload."""

    _require_known_submission(intent, submission)
    attempt = submission.submission_id
    operation_id = attempt.fetch_operation_id
    _require_positive_attempt(fetch_attempt, label="domain fetch attempt")
    started = _transition(
        intent,
        attempt,
        operation_id=operation_id,
        stage="domain_fetch",
        effect="read",
        state="started",
        transition_attempt=fetch_attempt,
        evidence={
            **_attempt_evidence(intent, attempt),
            "job_id": submission.job_id,
            "submission_receipt_content_hash": model_wire_content_hash(
                submission.receipt
            ),
        },
    )
    _append_before_effect(
        journal,
        started,
        intent=intent,
        attempt=attempt,
        phase="fetch",
        job_id=submission.job_id,
    )
    try:
        raw_candidate = runtime.fetch(
            _domain_fetch_request(
                attempt,
                intent,
                job_id=submission.job_id,
            )
        )
    except Exception as error:
        problem = problem_from_exception(
            "domain_fetch_raised",
            "domain runtime raised while fetching the submitted job",
            run_id=attempt.run_id,
            operation_id=operation_id,
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="fetch",
            retry="safe",
            certainty="indeterminate",
            reconciliation="retry fetch using the sealed known submission",
            job_id=submission.job_id,
            prior_problems=(problem,),
        )
        raise DomainFetchFailed(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=fetch_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            job_id=submission.job_id,
            certainty="indeterminate",
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, started, attempt=attempt)
        raise

    try:
        candidate: DomainFetchCandidate[ResultT] = _normalize_fetch_candidate(
            raw_candidate
        )
        receipt = candidate.receipt
        _require_receipt_identity(receipt.identity, expected=submission.identity)
        if receipt.job_id != submission.job_id:
            msg = "domain fetch receipt job_id does not match the known submission"
            raise ValueError(msg)
    except Exception as error:
        problem = _provider_problem(
            attempt,
            operation_id=operation_id,
            code="domain_fetch_receipt_invalid",
            message="domain runtime returned an invalid or uncorrelated fetch result",
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "failed", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="fetch",
            retry="safe",
            certainty="known",
            reconciliation="retry fetch using the sealed known submission",
            job_id=submission.job_id,
            prior_problems=(problem,),
        )
        raise DomainFetchFailed(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=fetch_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            job_id=submission.job_id,
            certainty="known",
        ) from error

    receipt_problems = contextualize_problems(
        receipt.problems,
        run_id=attempt.run_id,
        operation_id=operation_id,
    )
    if receipt.status in {"fetched", "pending"}:
        state: Literal["completed", "failed", "unknown"] = "completed"
    elif receipt.status == "not_found":
        state = "failed"
    else:
        state = "unknown"
    _append_after_effect(
        journal,
        started.model_copy(
            update={
                "state": state,
                "problems": receipt_problems,
                "evidence": {
                    **started.evidence,
                    **_receipt_evidence(receipt),
                },
            }
        ),
        intent=intent,
        attempt=attempt,
        phase="fetch",
        retry="safe",
        certainty=("known" if state != "unknown" else "indeterminate"),
        reconciliation="retry fetch using the sealed known submission",
        job_id=submission.job_id,
        prior_problems=receipt_problems,
    )
    if receipt.status == "fetched":
        assert candidate.result is not None
        return _correlated_domain_fetch(
            submission,
            receipt,
            candidate.result,
        )
    if receipt.status == "pending":
        return PendingDomainFetch(
            submission,
            receipt,
        )
    raise DomainFetchFailed(
        receipt_problems,
        run_id=attempt.run_id,
        operation_id=operation_id,
        attempt=fetch_attempt,
        invocation_id=attempt.invocation_id,
        submission_key=attempt.submission_key,
        job_id=submission.job_id,
        certainty=("indeterminate" if receipt.status == "unknown" else "known"),
    )


def reconcile_domain_invocation[PayloadT, ResultT](
    runtime: DomainRuntime[PayloadT, ResultT],
    intent: DomainInvocationIntent,
    uncertainty: DomainSubmissionUncertainty,
    *,
    journal: ExecutionJournal,
    reconcile_attempt: int = 1,
) -> DomainSubmissionResolution:
    """Resolve exactly one sealed uncertain submit without transient payloads."""

    sealed_uncertainty = _require_uncertainty(intent, uncertainty)
    uncertainty = sealed_uncertainty
    attempt = uncertainty.submission_id
    _require_positive_attempt(reconcile_attempt, label="domain reconcile attempt")
    operation_id = attempt.reconcile_operation_id
    started = _transition(
        intent,
        attempt,
        operation_id=operation_id,
        stage="domain_reconcile",
        effect="read",
        state="started",
        transition_attempt=reconcile_attempt,
        evidence=_attempt_evidence(intent, attempt),
    )
    _append_before_effect(
        journal,
        started,
        intent=intent,
        attempt=attempt,
        phase="reconcile",
        job_id=uncertainty.job_id_hint,
    )
    try:
        raw_receipt = runtime.reconcile(_domain_reconcile_request(attempt, intent))
    except Exception as error:
        problem = problem_from_exception(
            "domain_reconcile_raised",
            "domain runtime raised while reconciling the submission",
            run_id=attempt.run_id,
            operation_id=operation_id,
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="reconcile",
            retry="safe",
            certainty="indeterminate",
            reconciliation="retry with the same sealed uncertainty token",
            job_id=uncertainty.job_id_hint,
            prior_problems=(problem,),
            uncertainty=uncertainty,
        )
        raise DomainReconciliationFailed(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=reconcile_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            job_id=uncertainty.job_id_hint,
            uncertainty=uncertainty,
        ) from error
    except BaseException:
        _append_interruption_best_effort(journal, started, attempt=attempt)
        raise

    try:
        receipt = _normalize_reconcile_receipt(raw_receipt)
        _require_receipt_identity(receipt.identity, expected=uncertainty.identity)
    except Exception as error:
        problem = _provider_problem(
            attempt,
            operation_id=operation_id,
            code="domain_reconcile_receipt_invalid",
            message=(
                "domain runtime returned an invalid or uncorrelated "
                "reconciliation receipt"
            ),
            error=error,
        )
        _append_after_effect(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
            intent=intent,
            attempt=attempt,
            phase="reconcile",
            retry="safe",
            certainty="indeterminate",
            reconciliation="retry with the same sealed uncertainty token",
            job_id=uncertainty.job_id_hint,
            prior_problems=(problem,),
            uncertainty=uncertainty,
        )
        raise DomainReconciliationFailed(
            (problem,),
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=reconcile_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            job_id=uncertainty.job_id_hint,
            uncertainty=uncertainty,
        ) from error

    receipt_problems = contextualize_problems(
        receipt.problems,
        run_id=attempt.run_id,
        operation_id=operation_id,
    )
    if receipt.status == "unknown":
        _append_after_effect(
            journal,
            started.model_copy(
                update={
                    "state": "unknown",
                    "problems": receipt_problems,
                    "evidence": {
                        **started.evidence,
                        **_receipt_evidence(receipt),
                    },
                }
            ),
            intent=intent,
            attempt=attempt,
            phase="reconcile",
            retry="safe",
            certainty="indeterminate",
            reconciliation="retry with the same sealed uncertainty token",
            job_id=receipt.job_id,
            prior_problems=receipt_problems,
            uncertainty=uncertainty,
        )
        raise DomainReconciliationFailed(
            receipt_problems,
            run_id=attempt.run_id,
            operation_id=operation_id,
            attempt=reconcile_attempt,
            invocation_id=attempt.invocation_id,
            submission_key=attempt.submission_key,
            job_id=receipt.job_id,
            uncertainty=uncertainty,
        )

    resolution: DomainSubmissionResolution
    if receipt.status == "absent":
        resolution = AbsentDomainSubmission(
            attempt,
            receipt,
            "reconcile",
        )
    else:
        resolution = KnownDomainSubmission(
            attempt,
            receipt,
            "reconcile",
        )
    # Resolve the unsafe acquisition before completing the read operation.  If
    # the process stops between these writes, the journal never retains a
    # definitive reconcile receipt while the submit remains unresolved.
    _append_submit_resolution(
        journal,
        intent=intent,
        uncertainty=uncertainty,
        receipt=receipt,
    )
    _append_after_effect(
        journal,
        started.model_copy(
            update={
                "state": "completed",
                "problems": receipt_problems,
                "evidence": {
                    **started.evidence,
                    **_receipt_evidence(receipt),
                },
            }
        ),
        intent=intent,
        attempt=attempt,
        phase="reconcile",
        retry="safe",
        certainty="known",
        reconciliation="retry reconciliation to complete its durable read",
        job_id=receipt.job_id,
        prior_problems=receipt_problems,
        uncertainty=uncertainty,
    )
    return resolution


def execute_domain_invocation[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    runtime: DomainRuntime[PayloadT, ResultT],
    invocation: ClosedDomainInvocation[
        EntryAddressT,
        ResultAddressT,
        PayloadT,
    ],
    submission_id: DomainSubmissionId,
    *,
    journal: ExecutionJournal,
) -> DomainFetchOutcome[ResultT]:
    """Submit and perform the first repeatable fetch for a synchronous caller."""

    submission = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )
    return fetch_domain_invocation(
        runtime,
        invocation.intent,
        submission,
        journal=journal,
    )


def _new_submission_id(
    intent: DomainInvocationIntent,
    *,
    run_id: str,
    semantic_operation_id: str,
    generation: int,
) -> DomainSubmissionId:
    return DomainSubmissionId(
        run_id=run_id,
        semantic_operation_id=semantic_operation_id,
        generation=generation,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
        submission_key=_submission_key(
            run_id=run_id,
            semantic_operation_id=semantic_operation_id,
            generation=generation,
            invocation_id=intent.invocation_id,
            intent_fingerprint=intent.intent_fingerprint,
        ),
    )


def _submission_key(
    *,
    run_id: str,
    semantic_operation_id: str,
    generation: int,
    invocation_id: str,
    intent_fingerprint: str,
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.domain_submission_key.v1",
            "run_id": run_id,
            "semantic_operation_id": semantic_operation_id,
            "generation": generation,
            "invocation_id": invocation_id,
            "intent_fingerprint": intent_fingerprint,
        }
    )


def _validate_submission_id(
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
) -> None:
    if (
        attempt.invocation_id != intent.invocation_id
        or attempt.intent_fingerprint != intent.intent_fingerprint
    ):
        msg = "domain invocation attempt does not belong to the selected intent"
        raise ValueError(msg)


def _validate_submit_authorization(
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
    *,
    retry_from: DomainSubmissionAbsence | None,
) -> None:
    _validate_submission_id(intent, attempt)
    if attempt.generation == 1:
        if retry_from is not None:
            msg = "initial domain attempts cannot consume absence evidence"
            raise ValueError(msg)
        return
    if retry_from is None:
        msg = "later domain attempts require sealed absence evidence"
        raise ProviderContractError(
            (
                runtime_problem(
                    "domain_retry_not_authorized",
                    msg,
                    run_id=attempt.run_id,
                    operation_id=attempt.submit_operation_id,
                    category=ProblemCategory.CONFLICT,
                ),
            )
        )
    _require_absence(intent, retry_from)
    expected = plan_domain_submission_retry(intent, retry_from)
    if attempt != expected:
        msg = "domain retry attempt does not follow its absence evidence"
        raise ValueError(msg)


def _require_state_identity(
    attempt: DomainSubmissionId,
    identity: DomainReceiptIdentity,
) -> None:
    if (
        identity.submission_key != attempt.submission_key
        or identity.invocation_id != attempt.invocation_id
        or identity.intent_fingerprint != attempt.intent_fingerprint
    ):
        msg = "domain submission state does not belong to its attempt"
        raise ValueError(msg)


def _require_known_submission(
    intent: DomainInvocationIntent,
    submission: KnownDomainSubmission,
) -> None:
    _validate_submission_id(intent, submission.submission_id)
    _require_receipt_identity(
        submission.identity,
        expected=domain_receipt_identity(submission.submission_id, intent),
    )


def _require_absence(
    intent: DomainInvocationIntent,
    absence: DomainSubmissionAbsence,
) -> AbsentDomainSubmission:
    if not isinstance(cast("object", absence), AbsentDomainSubmission):
        msg = "domain retry requires an AbsentDomainSubmission"
        raise TypeError(msg)
    sealed_absence = cast("AbsentDomainSubmission", absence)
    _validate_submission_id(intent, sealed_absence.submission_id)
    _require_receipt_identity(
        sealed_absence.identity,
        expected=domain_receipt_identity(sealed_absence.submission_id, intent),
    )
    return sealed_absence


def _require_uncertainty(
    intent: DomainInvocationIntent,
    uncertainty: DomainSubmissionUncertainty,
) -> UncertainDomainSubmission:
    if not isinstance(cast("object", uncertainty), UncertainDomainSubmission):
        msg = "domain reconciliation requires an UncertainDomainSubmission"
        raise TypeError(msg)
    sealed_uncertainty = cast("UncertainDomainSubmission", uncertainty)
    _validate_submission_id(intent, sealed_uncertainty.submission_id)
    _require_receipt_identity(
        sealed_uncertainty.identity,
        expected=domain_receipt_identity(
            sealed_uncertainty.submission_id,
            intent,
        ),
    )
    return sealed_uncertainty


def _require_positive_attempt(value: int, *, label: str) -> None:
    if isinstance(value, bool) or value < 1:
        msg = f"{label} must be a positive integer"
        raise ValueError(msg)


def _normalize_submit_receipt(value: object) -> DomainSubmitReceipt:
    if not isinstance(value, DomainSubmitReceipt):
        msg = "domain runtime submit must return DomainSubmitReceipt"
        raise TypeError(msg)
    return DomainSubmitReceipt.model_validate(value.model_dump(mode="json"))


def _normalize_reconcile_receipt(value: object) -> DomainReconcileReceipt:
    if not isinstance(value, DomainReconcileReceipt):
        msg = "domain runtime reconcile must return DomainReconcileReceipt"
        raise TypeError(msg)
    return DomainReconcileReceipt.model_validate(value.model_dump(mode="json"))


def _normalize_fetch_candidate[ResultT](
    value: object,
) -> DomainFetchCandidate[ResultT]:
    if not isinstance(value, DomainFetchCandidate):
        msg = "domain runtime fetch must return DomainFetchCandidate"
        raise TypeError(msg)
    selected = cast("DomainFetchCandidate[ResultT]", value)
    receipt = DomainFetchReceipt.model_validate(
        selected.receipt.model_dump(mode="json")
    )
    return DomainFetchCandidate(receipt=receipt, result=selected.result)


def _require_receipt_identity(
    actual: DomainReceiptIdentity,
    *,
    expected: DomainReceiptIdentity,
) -> None:
    if actual != expected:
        msg = "domain runtime receipt does not echo the complete invocation identity"
        raise ValueError(msg)


def _transition(
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
    *,
    operation_id: str,
    stage: Literal["domain_submit", "domain_fetch", "domain_reconcile"],
    effect: Literal["acquisition", "read"],
    state: Literal["started", "completed", "failed", "unknown"],
    evidence: Mapping[str, JsonValue],
    transition_attempt: int | None = None,
) -> ExecutionTransition:
    _ = intent
    return ExecutionTransition(
        run_id=attempt.run_id,
        operation_id=operation_id,
        stage=stage,
        effect=effect,
        state=state,
        attempt=1 if transition_attempt is None else transition_attempt,
        evidence=dict(evidence),
    )


def _attempt_evidence(
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
) -> dict[str, JsonValue]:
    return {
        "invocation_intent": intent.model_dump(mode="json"),
        "invocation_intent_content_hash": model_wire_content_hash(intent),
        "semantic_operation_id": attempt.semantic_operation_id,
        "submission_key": attempt.submission_key,
        "submission_generation": attempt.generation,
    }


def _receipt_evidence(receipt: BaseModel) -> dict[str, JsonValue]:
    return {
        "receipt": receipt.model_dump(mode="json"),
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def _commit_transition(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
) -> ExecutionTransition:
    committed = journal.append(transition)
    if not isinstance(cast("object", committed), ExecutionTransition):
        msg = "execution journal returned no committed transition"
        raise TypeError(msg)
    normalized = ExecutionTransition.model_validate(committed.model_dump(mode="json"))
    if normalized.sequence is None:
        msg = "domain effects require a journal that assigns durable sequence identity"
        raise ValueError(msg)
    expected = transition.model_dump(
        mode="json",
        exclude={"sequence", "timestamp"},
    )
    actual = normalized.model_dump(
        mode="json",
        exclude={"sequence", "timestamp"},
    )
    if actual != expected:
        msg = "execution journal changed domain transition identity or evidence"
        raise ValueError(msg)
    return normalized


def _append_before_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    *,
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
    phase: Literal["submit", "fetch", "reconcile"],
    job_id: str | None,
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        problem = problem_from_exception(
            "domain_runtime_intent_persistence_failed",
            f"failed to persist domain {phase} intent before the runtime call",
            run_id=attempt.run_id,
            operation_id=transition.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
            category=ProblemCategory.STORAGE,
        )
        raise DomainRuntimePersistenceError(
            (problem,),
            run_id=attempt.run_id,
            operation_id=transition.operation_id,
            attempt=transition.attempt,
            invocation_id=intent.invocation_id,
            submission_key=attempt.submission_key,
            phase=phase,
            retry="safe",
            certainty="known",
            reconciliation="retry after operation intent can be durably committed",
            job_id=job_id,
        ) from error


def _append_after_effect(
    journal: ExecutionJournal,
    transition: ExecutionTransition,
    *,
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
    phase: Literal["submit", "fetch", "reconcile"],
    retry: Literal["safe", "after_reconciliation", "not_retryable"],
    certainty: Literal["known", "indeterminate"],
    reconciliation: str,
    job_id: str | None,
    prior_problems: Sequence[Problem],
    uncertainty: UncertainDomainSubmission | None = None,
) -> None:
    try:
        _commit_transition(journal, transition)
    except Exception as error:
        problem = problem_from_exception(
            "domain_runtime_receipt_persistence_failed",
            f"failed to persist domain {phase} result after the runtime call",
            run_id=attempt.run_id,
            operation_id=transition.operation_id,
            error=error,
            phase=ProblemPhase.PERSISTENCE,
            category=ProblemCategory.STORAGE,
        )
        selected_uncertainty = uncertainty
        if selected_uncertainty is None and phase == "submit":
            selected_uncertainty = _uncertain_submission(
                intent,
                attempt,
                reason="persistence",
                submit_call_attempt=transition.attempt,
                job_id_hint=job_id,
                problems=(*prior_problems, problem),
            )
        raise DomainRuntimePersistenceError(
            (*prior_problems, problem),
            run_id=attempt.run_id,
            operation_id=transition.operation_id,
            attempt=transition.attempt,
            invocation_id=intent.invocation_id,
            submission_key=attempt.submission_key,
            phase=phase,
            retry=retry,
            certainty=certainty,
            reconciliation=reconciliation,
            job_id=job_id,
            uncertainty=selected_uncertainty,
        ) from error


def _append_interruption_best_effort(
    journal: ExecutionJournal,
    started: ExecutionTransition,
    *,
    attempt: DomainSubmissionId,
) -> None:
    problem = runtime_problem(
        "domain_runtime_interrupted",
        "domain runtime call was interrupted before returning a receipt",
        run_id=attempt.run_id,
        operation_id=started.operation_id,
        category=ProblemCategory.INTERRUPTED,
    )
    try:
        _commit_transition(
            journal,
            started.model_copy(update={"state": "unknown", "problems": (problem,)}),
        )
    except BaseException:
        return


def _append_submit_resolution(
    journal: ExecutionJournal,
    *,
    intent: DomainInvocationIntent,
    uncertainty: UncertainDomainSubmission,
    receipt: DomainReconcileReceipt,
) -> None:
    attempt = uncertainty.submission_id
    problems: tuple[Problem, ...] = ()
    state: Literal["completed", "failed"]
    if receipt.status == "absent":
        state = "failed"
        problems = (
            runtime_problem(
                "domain_submission_absent",
                "reconciliation established that the invocation was not submitted",
                run_id=attempt.run_id,
                operation_id=attempt.submit_operation_id,
                details={"submission_key": attempt.submission_key},
            ),
        )
    else:
        state = "completed"
    resolution = _transition(
        intent,
        attempt,
        operation_id=attempt.submit_operation_id,
        stage="domain_submit",
        effect="acquisition",
        state=state,
        transition_attempt=uncertainty.submit_call_attempt,
        evidence={
            **_attempt_evidence(intent, attempt),
            "resolved_by_operation_id": attempt.reconcile_operation_id,
            "reconcile_receipt": receipt.model_dump(mode="json"),
            "reconcile_receipt_content_hash": model_wire_content_hash(receipt),
        },
    ).model_copy(update={"problems": problems})
    _append_after_effect(
        journal,
        resolution,
        intent=intent,
        attempt=attempt,
        phase="reconcile",
        retry="safe",
        certainty="indeterminate",
        reconciliation="retry reconciliation to replay submit resolution",
        job_id=receipt.job_id,
        prior_problems=problems,
        uncertainty=uncertainty,
    )


def _uncertain_submission(
    intent: DomainInvocationIntent,
    attempt: DomainSubmissionId,
    *,
    reason: Literal[
        "runtime_exception",
        "invalid_receipt",
        "unknown_receipt",
        "persistence",
    ],
    submit_call_attempt: int,
    job_id_hint: str | None,
    problems: Sequence[Problem],
) -> UncertainDomainSubmission:
    return UncertainDomainSubmission(
        attempt,
        domain_receipt_identity(attempt, intent),
        reason=reason,
        submit_call_attempt=submit_call_attempt,
        job_id_hint=job_id_hint,
        problems=problems,
    )


def _provider_problem(
    attempt: DomainSubmissionId,
    *,
    operation_id: str,
    code: str,
    message: str,
    error: Exception,
) -> Problem:
    return runtime_problem(
        code,
        message,
        run_id=attempt.run_id,
        operation_id=operation_id,
        category=ProblemCategory.PROVIDER_CONTRACT,
        details={"error_type": f"{type(error).__module__}.{type(error).__qualname__}"},
    )


__all__ = [
    "CorrelatedDomainFetch",
    "DomainFetchCandidate",
    "DomainFetchReceipt",
    "DomainFetchRequest",
    "DomainReceiptIdentity",
    "DomainReconcileReceipt",
    "DomainReconcileRequest",
    "DomainRuntime",
    "DomainSubmissionId",
    "DomainSubmitReceipt",
    "DomainSubmitRequest",
]
