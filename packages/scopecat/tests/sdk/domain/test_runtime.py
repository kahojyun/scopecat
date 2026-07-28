from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    DomainSubmissionFailed,
    DomainSubmissionIndeterminate,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    problem,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    close_domain_invocation,
)
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainFetchReceipt,
    DomainFetchResult,
    DomainSubmissionId,
    DomainSubmitReceipt,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)
from tests.testkit.runtime import FakeExecutionJournal

type _Invocation = ClosedDomainInvocation[str, dict[str, str]]


@dataclass(frozen=True, slots=True)
class _RuntimeResultContract:
    contract_fingerprint: str = "runtime-result-contract"


def _problem(code: str = "domain_test_failure") -> Problem:
    return problem(
        code,
        "the test domain operation did not complete",
        phase=ProblemPhase.EXECUTION,
    )


def _submission_key() -> str:
    return "submission-key"


def _closed_invocation(*, target_intent: object | None = None) -> _Invocation:
    mapping = cast(
        "DomainResultMapping[str]",
        cast("object", _RuntimeResultContract()),
    )
    return close_domain_invocation(
        mapping,
        invocation_id="invocation",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="interface-fingerprint",
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
    submission_key = _submission_key()
    blocking = (_problem(),)
    submitted = DomainSubmitReceipt(
        submission_key=submission_key, status="submitted", job_id="job"
    )
    rejected = DomainSubmitReceipt(
        submission_key=submission_key, status="not_submitted", problems=blocking
    )
    unknown = DomainSubmitReceipt(
        submission_key=submission_key, status="unknown", problems=blocking
    )
    fetched = DomainFetchReceipt(
        submission_key=submission_key,
        job_id="job",
        status="fetched",
        result_fingerprint="result",
        result_count=1,
    )
    missing = DomainFetchReceipt(
        submission_key=submission_key,
        job_id="job",
        status="not_found",
        problems=blocking,
    )

    assert (submitted.status, rejected.status, unknown.status) == (
        "submitted",
        "not_submitted",
        "unknown",
    )
    assert DomainFetchResult(receipt=fetched, result="payload").result == "payload"
    assert missing.status == "not_found"


@pytest.mark.parametrize(
    "receipt",
    [
        lambda: DomainSubmitReceipt(
            submission_key=_submission_key(), status="submitted"
        ),
        lambda: DomainSubmitReceipt(submission_key=_submission_key(), status="unknown"),
        lambda: DomainFetchReceipt(
            submission_key=_submission_key(), job_id="job", status="fetched"
        ),
        lambda: DomainFetchReceipt(
            submission_key=_submission_key(), job_id="job", status="not_found"
        ),
    ],
)
def test_receipts_reject_contradictory_evidence(
    receipt: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        receipt()


def test_domain_result_requires_successful_fetch_evidence() -> None:
    receipt = DomainFetchReceipt(
        submission_key=_submission_key(),
        job_id="job",
        status="not_found",
        problems=(_problem(),),
    )

    with pytest.raises(ValueError, match="fetched receipt evidence"):
        DomainFetchResult(receipt=receipt, result="payload")


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
    assert "submission_key" not in first.model_dump(mode="json")


@dataclass
class _Runtime:
    submit_status: Literal["submitted", "not_submitted", "unknown"] = "submitted"
    fetch_status: Literal["fetched", "not_found", "unknown"] = "fetched"
    submit_error: Exception | None = None
    fetch_error: Exception | None = None
    forge_submit_key: bool = False
    forge_fetch_key: bool = False
    submit_calls: int = 0
    fetch_calls: int = 0
    submit_keys: list[str] = field(default_factory=list)
    fetch_keys: list[str] = field(default_factory=list)

    def submit(
        self,
        submission_key: str,
        payload: dict[str, str],
    ) -> DomainSubmitReceipt:
        del payload
        self.submit_calls += 1
        self.submit_keys.append(submission_key)
        if self.submit_error is not None:
            raise self.submit_error
        receipt_key = "forged" if self.forge_submit_key else submission_key
        if self.submit_status == "submitted":
            return DomainSubmitReceipt(
                submission_key=receipt_key, status="submitted", job_id="job"
            )
        return DomainSubmitReceipt(
            submission_key=receipt_key,
            status=self.submit_status,
            problems=(_problem(f"submit_{self.submit_status}"),),
        )

    def fetch(
        self,
        submission_key: str,
        job_id: str,
    ) -> DomainFetchReceipt | DomainFetchResult[str]:
        self.fetch_calls += 1
        self.fetch_keys.append(submission_key)
        if self.fetch_error is not None:
            raise self.fetch_error
        receipt_key = "forged" if self.forge_fetch_key else submission_key
        if self.fetch_status == "fetched":
            return DomainFetchResult(
                DomainFetchReceipt(
                    submission_key=receipt_key,
                    job_id=job_id,
                    status="fetched",
                    result_fingerprint="result",
                    result_count=1,
                ),
                "payload",
            )
        return DomainFetchReceipt(
            submission_key=receipt_key,
            job_id=job_id,
            status=self.fetch_status,
            problems=(_problem(f"fetch_{self.fetch_status}"),),
        )


def _submit(
    runtime: _Runtime, invocation: _Invocation, journal: FakeExecutionJournal
) -> tuple[DomainSubmissionId, str]:
    submission_id = _submission_id(invocation)
    job_id = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )
    return submission_id, job_id


def test_synchronous_submit_and_fetch_commit_exact_journal_sequence() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()
    journal = FakeExecutionJournal()

    submission_id, job_id = _submit(runtime, invocation, journal)
    fetched = fetch_domain_invocation(
        runtime,
        invocation.intent,
        submission_id,
        job_id,
        journal=journal,
    )

    assert isinstance(fetched, DomainFetchResult)
    assert fetched.result == "payload"
    assert runtime.submit_keys == [submission_id.submission_key]
    assert runtime.fetch_keys == [submission_id.submission_key]
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_submit", "started"),
        ("domain_submit", "completed"),
        ("domain_fetch", "started"),
        ("domain_fetch", "completed"),
    ]


@pytest.mark.parametrize(
    ("status", "error_type", "certainty", "state"),
    [
        ("not_submitted", DomainSubmissionFailed, "known", "failed"),
        ("unknown", DomainSubmissionIndeterminate, "indeterminate", "unknown"),
    ],
)
def test_submit_negative_outcomes_stop_without_fetch(
    status: Literal["not_submitted", "unknown"],
    error_type: type[DomainRuntimeFailure],
    certainty: str,
    state: str,
) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(submit_status=status)
    journal = FakeExecutionJournal()

    with pytest.raises(error_type) as caught:
        _submit(runtime, invocation, journal)

    assert caught.value.certainty == certainty
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
    journal = FakeExecutionJournal()
    submission_id, job_id = _submit(runtime, invocation, journal)

    with pytest.raises(DomainFetchFailed) as caught:
        fetch_domain_invocation(
            runtime,
            invocation.intent,
            submission_id,
            job_id,
            journal=journal,
        )

    assert caught.value.certainty == certainty
    assert journal.entries[-1].state == state


@pytest.mark.parametrize("phase", ["submit", "fetch"])
def test_provider_exceptions_are_classified_at_the_effect_boundary(phase: str) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(
        submit_error=RuntimeError("lost") if phase == "submit" else None,
        fetch_error=RuntimeError("failed") if phase == "fetch" else None,
    )
    journal = FakeExecutionJournal()
    if phase == "submit":
        with pytest.raises(DomainSubmissionIndeterminate):
            _submit(runtime, invocation, journal)
        assert journal.entries[-1].state == "unknown"
    else:
        submission_id, job_id = _submit(runtime, invocation, journal)
        with pytest.raises(DomainFetchFailed) as caught:
            fetch_domain_invocation(
                runtime,
                invocation.intent,
                submission_id,
                job_id,
                journal=journal,
            )
        assert caught.value.certainty == "known"


@pytest.mark.parametrize("phase", ["submit", "fetch"])
def test_forged_receipt_submission_key_is_indeterminate(phase: str) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(
        forge_submit_key=phase == "submit",
        forge_fetch_key=phase == "fetch",
    )
    journal = FakeExecutionJournal()
    if phase == "submit":
        with pytest.raises(DomainSubmissionIndeterminate):
            _submit(runtime, invocation, journal)
    else:
        submission_id, job_id = _submit(runtime, invocation, journal)
        with pytest.raises(DomainFetchFailed) as caught:
            fetch_domain_invocation(
                runtime,
                invocation.intent,
                submission_id,
                job_id,
                journal=journal,
            )
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
