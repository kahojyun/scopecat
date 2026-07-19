from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from scopecat.adapters.memory import MemoryExecutionJournal
from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainRuntimePersistenceError,
    DomainSubmissionFailed,
    DomainSubmissionIndeterminate,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainResultMappingContract,
    close_domain_invocation,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainReceiptIdentity,
    DomainSubmissionId,
    DomainSubmitReceipt,
    DomainSubmitRequest,
    KnownDomainSubmission,
    domain_receipt_identity,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)

type _Invocation = ClosedDomainInvocation[str, dict[str, str]]


@dataclass(frozen=True, slots=True)
class _RuntimeResultContract:
    contract_fingerprint: str = "runtime-result-contract"


def _problem(code: str = "domain_test_failure") -> Problem:
    return blocking_problem(
        code,
        "the test domain operation did not complete",
        category=ProblemCategory.OPERATION,
        phase=ProblemPhase.EXECUTION,
    )


def _identity() -> DomainReceiptIdentity:
    return DomainReceiptIdentity(
        submission_key="submission-key",
        invocation_id="invocation",
        intent_fingerprint="intent-fingerprint",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="capability-fingerprint",
        artifact_id="artifact",
        artifact_fingerprint="artifact-fingerprint",
    )


def _closed_invocation(*, target_intent: object | None = None) -> _Invocation:
    mapping = cast(
        "DomainResultMappingContract[str]",
        cast("object", _RuntimeResultContract()),
    )
    return close_domain_invocation(
        mapping,
        invocation_id="invocation",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="capability-fingerprint",
        artifact_id="artifact",
        artifact_fingerprint="artifact-fingerprint",
        target_intent={"realization": "iq"} if target_intent is None else target_intent,
        payload={"compiled": "payload"},
    )


def _submission_id(invocation: _Invocation) -> DomainSubmissionId:
    return plan_domain_submission(
        invocation,
        run_id="run-domain",
        semantic_operation_id="domain.batch",
    )


def test_receipts_encode_success_rejection_and_unknown_only() -> None:
    identity = _identity()
    blocking = (_problem(),)
    submitted = DomainSubmitReceipt(identity=identity, status="submitted", job_id="job")
    rejected = DomainSubmitReceipt(
        identity=identity, status="not_submitted", problems=blocking
    )
    unknown = DomainSubmitReceipt(
        identity=identity, status="unknown", problems=blocking
    )
    fetched = DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="fetched",
        result_fingerprint="result",
        result_count=1,
    )
    missing = DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="not_found",
        problems=blocking,
    )

    assert (submitted.status, rejected.status, unknown.status) == (
        "submitted",
        "not_submitted",
        "unknown",
    )
    assert DomainFetchCandidate(receipt=fetched, result="payload").result == "payload"
    assert DomainFetchCandidate[str](receipt=missing).result is None


@pytest.mark.parametrize(
    "receipt",
    [
        lambda: DomainSubmitReceipt(identity=_identity(), status="submitted"),
        lambda: DomainSubmitReceipt(identity=_identity(), status="unknown"),
        lambda: DomainFetchReceipt(
            identity=_identity(), job_id="job", status="fetched"
        ),
        lambda: DomainFetchReceipt(
            identity=_identity(), job_id="job", status="not_found"
        ),
    ],
)
def test_receipts_reject_contradictory_evidence(
    receipt: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        receipt()


def test_submission_identity_is_deterministic_and_covers_intent() -> None:
    invocation = _closed_invocation()
    changed = _closed_invocation(target_intent={"realization": "raw"})
    first = _submission_id(invocation)
    repeated = _submission_id(invocation)
    changed_id = plan_domain_submission(
        changed,
        run_id=first.run_id,
        semantic_operation_id=first.semantic_operation_id,
    )

    assert first == repeated
    assert first.submission_key != changed_id.submission_key
    assert first.submit_operation_id != first.fetch_operation_id
    forged = first.model_dump(mode="json")
    forged["submission_key"] = "forged"
    with pytest.raises(ValidationError, match="complete identity"):
        DomainSubmissionId.model_validate(forged)


@dataclass
class _Runtime:
    submit_status: Literal["submitted", "not_submitted", "unknown"] = "submitted"
    fetch_status: Literal["fetched", "not_found", "unknown"] = "fetched"
    submit_error: Exception | None = None
    fetch_error: Exception | None = None
    forge_submit_identity: bool = False
    forge_fetch_identity: bool = False
    submit_calls: int = 0
    fetch_calls: int = 0
    submit_requests: list[DomainSubmitRequest[dict[str, str]]] = field(
        default_factory=list
    )
    fetch_requests: list[DomainFetchRequest] = field(default_factory=list)

    def submit(
        self, request: DomainSubmitRequest[dict[str, str]]
    ) -> DomainSubmitReceipt:
        self.submit_calls += 1
        self.submit_requests.append(request)
        if self.submit_error is not None:
            raise self.submit_error
        identity = request.identity
        if self.forge_submit_identity:
            identity = identity.model_copy(update={"artifact_id": "forged"})
        if self.submit_status == "submitted":
            return DomainSubmitReceipt(
                identity=identity, status="submitted", job_id="job"
            )
        return DomainSubmitReceipt(
            identity=identity,
            status=self.submit_status,
            problems=(_problem(f"submit_{self.submit_status}"),),
        )

    def fetch(self, request: DomainFetchRequest) -> DomainFetchCandidate[str]:
        self.fetch_calls += 1
        self.fetch_requests.append(request)
        if self.fetch_error is not None:
            raise self.fetch_error
        identity = request.identity
        if self.forge_fetch_identity:
            identity = identity.model_copy(update={"artifact_id": "forged"})
        if self.fetch_status == "fetched":
            return DomainFetchCandidate(
                DomainFetchReceipt(
                    identity=identity,
                    job_id=request.job_id,
                    status="fetched",
                    result_fingerprint="result",
                    result_count=1,
                ),
                "payload",
            )
        return DomainFetchCandidate(
            DomainFetchReceipt(
                identity=identity,
                job_id=request.job_id,
                status=self.fetch_status,
                problems=(_problem(f"fetch_{self.fetch_status}"),),
            )
        )


def _submit(
    runtime: _Runtime, invocation: _Invocation, journal: MemoryExecutionJournal
) -> KnownDomainSubmission:
    return submit_domain_invocation(
        runtime,
        invocation,
        _submission_id(invocation),
        journal=journal,
    )


def test_synchronous_submit_and_fetch_commit_exact_journal_sequence() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()
    journal = MemoryExecutionJournal()

    known = _submit(runtime, invocation, journal)
    fetched = fetch_domain_invocation(
        runtime, invocation.intent, known, journal=journal
    )

    assert isinstance(fetched, CorrelatedDomainFetch)
    assert fetched.result == "payload"
    assert runtime.submit_requests[0].identity == domain_receipt_identity(
        known.submission_id, invocation.intent
    )
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_submit", "started"),
        ("domain_submit", "completed"),
        ("domain_fetch", "started"),
        ("domain_fetch", "completed"),
    ]


@pytest.mark.parametrize(
    ("status", "error_type", "state"),
    [
        ("not_submitted", DomainSubmissionFailed, "failed"),
        ("unknown", DomainSubmissionIndeterminate, "unknown"),
    ],
)
def test_submit_negative_outcomes_stop_without_fetch(
    status: Literal["not_submitted", "unknown"],
    error_type: type[Exception],
    state: str,
) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(submit_status=status)
    journal = MemoryExecutionJournal()

    with pytest.raises(error_type):
        _submit(runtime, invocation, journal)

    assert runtime.fetch_calls == 0
    assert journal.entries[-1].state == state


@pytest.mark.parametrize(
    ("status", "certainty", "state"),
    [("not_found", "known", "failed"), ("unknown", "indeterminate", "unknown")],
)
def test_fetch_negative_outcomes_preserve_certainty(
    status: Literal["not_found", "unknown"],
    certainty: str,
    state: str,
) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(fetch_status=status)
    journal = MemoryExecutionJournal()
    known = _submit(runtime, invocation, journal)

    with pytest.raises(DomainFetchFailed) as caught:
        fetch_domain_invocation(runtime, invocation.intent, known, journal=journal)

    assert caught.value.certainty == certainty
    assert journal.entries[-1].state == state


@pytest.mark.parametrize("phase", ["submit", "fetch"])
def test_provider_exceptions_are_classified_at_the_effect_boundary(phase: str) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(
        submit_error=RuntimeError("lost") if phase == "submit" else None,
        fetch_error=RuntimeError("failed") if phase == "fetch" else None,
    )
    journal = MemoryExecutionJournal()
    if phase == "submit":
        with pytest.raises(DomainSubmissionIndeterminate):
            _submit(runtime, invocation, journal)
        assert journal.entries[-1].state == "unknown"
    else:
        known = _submit(runtime, invocation, journal)
        with pytest.raises(DomainFetchFailed) as caught:
            fetch_domain_invocation(runtime, invocation.intent, known, journal=journal)
        assert caught.value.certainty == "known"


@pytest.mark.parametrize("phase", ["submit", "fetch"])
def test_forged_receipt_identity_is_indeterminate(phase: str) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(
        forge_submit_identity=phase == "submit",
        forge_fetch_identity=phase == "fetch",
    )
    journal = MemoryExecutionJournal()
    if phase == "submit":
        with pytest.raises(DomainSubmissionIndeterminate):
            _submit(runtime, invocation, journal)
    else:
        known = _submit(runtime, invocation, journal)
        with pytest.raises(DomainFetchFailed) as caught:
            fetch_domain_invocation(runtime, invocation.intent, known, journal=journal)
        assert caught.value.certainty == "indeterminate"


@dataclass
class _NoSequenceJournal:
    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        return entry.model_copy(deep=True)


def test_submit_intent_must_be_durable_before_provider_call() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()

    with pytest.raises(DomainRuntimePersistenceError) as caught:
        submit_domain_invocation(
            runtime,
            invocation,
            _submission_id(invocation),
            journal=_NoSequenceJournal(),
        )

    assert caught.value.certainty == "known"
    assert runtime.submit_calls == 0
