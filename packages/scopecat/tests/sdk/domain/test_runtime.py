from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pytest
from pydantic import ValidationError

from scopecat.adapters.memory import MemoryExecutionJournal
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import TypedProgram, product_output, record_product
from scopecat.kernel.errors import (
    DomainFetchFailed,
    DomainReconciliationFailed,
    DomainRuntimePersistenceError,
    DomainSubmissionFailed,
    DomainSubmissionIndeterminate,
    ProviderContractError,
)
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
)
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    AdapterEntryResults,
    ClosedDomainInvocation,
    EntryPointBinding,
    ResultUseBinding,
    close_domain_invocation,
    materialize_linked_points,
    seal_domain_result_mapping,
)
from scopecat.sdk.domain.runtime import (
    AbsentDomainSubmission,
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainReceiptIdentity,
    DomainReconcileReceipt,
    DomainReconcileRequest,
    DomainSubmissionId,
    DomainSubmitReceipt,
    DomainSubmitRequest,
    KnownDomainSubmission,
    PendingDomainFetch,
    UncertainDomainSubmission,
    domain_receipt_identity,
    fetch_domain_invocation,
    plan_domain_submission,
    plan_domain_submission_retry,
    reconcile_domain_invocation,
    submit_domain_invocation,
)
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import table_value_expr

type _Invocation = ClosedDomainInvocation[str, str, dict[str, str]]
type _ReceiptFactory = Callable[
    [DomainReceiptIdentity, tuple[Problem, ...]],
    object,
]
type _SubmitStatus = Literal["submitted", "not_submitted", "unknown"]
type _FetchStatus = Literal["fetched", "pending", "not_found", "unknown"]
type _ReconcileStatus = Literal["absent", "submitted", "completed", "unknown"]


def _problem(code: str = "domain_test_failure") -> Problem:
    return blocking_problem(
        code,
        "the test domain operation did not complete",
        category=ProblemCategory.OPERATION,
        phase=ProblemPhase.EXECUTION,
    )


def _standalone_identity() -> DomainReceiptIdentity:
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


def _closed_invocation(
    *,
    adapter_intent: object | None = None,
) -> _Invocation:
    point_type = Table(
        columns=(TableColumn("x", Scalar(Float())),),
        min_rows=1,
        max_rows=1,
    )
    product = product_output(
        "signal",
        kind="observable",
        unit="ratio",
        dtype="float64",
    )
    product_use, record = record_product(product, record_id="signal-record")
    program = TypedProgram(
        id="domain-runtime-contract",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_rows(
                table_value_expr(
                    literal_rows([{"x": 0.0}]),
                    expected_type=point_type,
                )
            )
        ),
        product_defs=(product,),
        product_uses=(product_use,),
        record_uses=(record,),
    )
    linked_points = materialize_linked_points(
        link_program(
            program,
            validate_config_environment(load_config()),
        )
    )
    point = linked_points.point_domain.points[0]
    mapping = seal_domain_result_mapping(
        linked_points,
        (product_use.id,),
        (AdapterEntryResults("entry", ("result",)),),
        (EntryPointBinding("entry", point.logical_id),),
        (ResultUseBinding("entry", "result", product_use.id),),
    )
    return close_domain_invocation(
        mapping,
        invocation_id="invocation",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="capability-fingerprint",
        artifact_id="artifact",
        artifact_fingerprint="artifact-fingerprint",
        adapter_intent=(
            {"realization": "integrated-iq"}
            if adapter_intent is None
            else adapter_intent
        ),
        payload={"compiled": "payload"},
    )


def _submission_id(invocation: _Invocation) -> DomainSubmissionId:
    return plan_domain_submission(
        invocation,
        run_id="run-domain",
        semantic_operation_id="domain.batch",
    )


def test_domain_receipt_truth_tables_accept_valid_candidates() -> None:
    identity = _standalone_identity()
    blocking = (_problem(),)

    assert (
        DomainSubmitReceipt(
            identity=identity,
            status="submitted",
            job_id="job",
        ).status
        == "submitted"
    )
    assert (
        DomainSubmitReceipt(
            identity=identity,
            status="not_submitted",
            problems=blocking,
        ).status
        == "not_submitted"
    )
    assert (
        DomainSubmitReceipt(
            identity=identity,
            status="unknown",
            job_id="possibly-created-job",
            problems=blocking,
        ).status
        == "unknown"
    )

    fetched = DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="fetched",
        result_fingerprint="result-fingerprint",
        result_count=1,
    )
    pending = DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="pending",
    )
    assert DomainFetchCandidate(receipt=fetched, result="payload").result == "payload"
    assert DomainFetchCandidate[str](receipt=pending).result is None
    for status in ("not_found", "unknown"):
        assert (
            DomainFetchReceipt(
                identity=identity,
                job_id="job",
                status=status,
                problems=blocking,
            ).status
            == status
        )

    assert DomainReconcileReceipt(identity=identity, status="absent").job_id is None
    for status in ("submitted", "completed"):
        assert (
            DomainReconcileReceipt(
                identity=identity,
                status=status,
                job_id="job",
            ).status
            == status
        )
    assert (
        DomainReconcileReceipt(
            identity=identity,
            status="unknown",
            problems=blocking,
        ).status
        == "unknown"
    )


_CONTRADICTORY_RECEIPT_FACTORIES: list[_ReceiptFactory] = [
    lambda identity, _blocking: DomainSubmitReceipt(
        identity=identity,
        status="submitted",
    ),
    lambda identity, blocking: DomainSubmitReceipt(
        identity=identity,
        status="submitted",
        job_id="job",
        problems=blocking,
    ),
    lambda identity, _blocking: DomainSubmitReceipt(
        identity=identity,
        status="not_submitted",
    ),
    lambda identity, blocking: DomainSubmitReceipt(
        identity=identity,
        status="not_submitted",
        job_id="job",
        problems=blocking,
    ),
    lambda identity, _blocking: DomainSubmitReceipt(
        identity=identity,
        status="unknown",
    ),
    lambda identity, _blocking: DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="fetched",
    ),
    lambda identity, blocking: DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="fetched",
        result_fingerprint="result-fingerprint",
        result_count=1,
        problems=blocking,
    ),
    lambda identity, _blocking: DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="pending",
        result_fingerprint="result-fingerprint",
        result_count=1,
    ),
    lambda identity, blocking: DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="pending",
        problems=blocking,
    ),
    lambda identity, _blocking: DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="not_found",
    ),
    lambda identity, _blocking: DomainReconcileReceipt(
        identity=identity,
        status="absent",
        job_id="job",
    ),
    lambda identity, _blocking: DomainReconcileReceipt(
        identity=identity,
        status="submitted",
    ),
    lambda identity, blocking: DomainReconcileReceipt(
        identity=identity,
        status="completed",
        job_id="job",
        problems=blocking,
    ),
    lambda identity, _blocking: DomainReconcileReceipt(
        identity=identity,
        status="unknown",
    ),
]


@pytest.mark.parametrize(
    "factory",
    _CONTRADICTORY_RECEIPT_FACTORIES,
    ids=(
        "submitted-without-job",
        "submitted-with-blocking-problem",
        "not-submitted-without-problem",
        "not-submitted-with-job",
        "unknown-submit-without-problem",
        "fetched-without-evidence",
        "fetched-with-blocking-problem",
        "pending-with-evidence",
        "pending-with-blocking-problem",
        "not-found-without-problem",
        "absent-with-job",
        "known-reconcile-without-job",
        "known-reconcile-with-blocking-problem",
        "unknown-reconcile-without-problem",
    ),
)
def test_domain_receipt_truth_tables_reject_contradictions(
    factory: _ReceiptFactory,
) -> None:
    with pytest.raises(ValidationError):
        factory(_standalone_identity(), (_problem(),))


def test_fetch_candidates_keep_provider_payloads_outside_correlated_state() -> None:
    identity = _standalone_identity()
    fetched = DomainFetchReceipt(
        identity=identity,
        job_id="job",
        status="fetched",
        result_fingerprint="result-fingerprint",
        result_count=1,
    )
    pending = DomainFetchReceipt(identity=identity, job_id="job", status="pending")

    with pytest.raises(ValueError, match="requires its transient payload"):
        DomainFetchCandidate[str](receipt=fetched)
    with pytest.raises(ValueError, match="cannot contain a payload"):
        DomainFetchCandidate(receipt=pending, result="unexpected")


def test_intent_and_submission_ids_cover_generation_and_intent() -> None:
    invocation = _closed_invocation()
    same = close_domain_invocation(
        invocation.result_mapping,
        invocation_id="invocation",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="capability-fingerprint",
        artifact_id="artifact",
        artifact_fingerprint="artifact-fingerprint",
        adapter_intent={"realization": "integrated-iq"},
        payload={"compiled": "another-process-local-payload"},
    )
    changed = close_domain_invocation(
        invocation.result_mapping,
        invocation_id="invocation",
        target_id="target",
        compiler_id="compiler",
        capability_fingerprint="capability-fingerprint",
        artifact_id="artifact",
        artifact_fingerprint="artifact-fingerprint",
        adapter_intent={"realization": "raw-trace"},
        payload={"compiled": "payload"},
    )

    assert invocation.intent == same.intent
    assert invocation.intent.intent_fingerprint != changed.intent.intent_fingerprint
    first = _submission_id(invocation)
    repeated = _submission_id(invocation)
    changed_id = plan_domain_submission(
        changed,
        run_id=first.run_id,
        semantic_operation_id=first.semantic_operation_id,
    )
    assert first == repeated
    assert first.generation == 1
    assert first.submission_key != changed_id.submission_key
    assert first.submit_operation_id == f"domain:{first.submission_key}:submit"
    assert first.fetch_operation_id == f"domain:{first.submission_key}:fetch"
    assert first.reconcile_operation_id == f"domain:{first.submission_key}:reconcile"
    assert {
        first.submit_operation_id,
        first.fetch_operation_id,
        first.reconcile_operation_id,
    }.isdisjoint(
        {
            changed_id.submit_operation_id,
            changed_id.fetch_operation_id,
            changed_id.reconcile_operation_id,
        }
    )

    forged = first.model_dump(mode="json")
    forged["generation"] = 2
    with pytest.raises(ValidationError, match="complete generation"):
        DomainSubmissionId.model_validate(forged)


@dataclass
class _ScriptedRuntime:
    submit_status: _SubmitStatus = "submitted"
    submit_error: Exception | None = None
    fetch_statuses: list[_FetchStatus] = field(default_factory=lambda: ["fetched"])
    fetch_errors_remaining: int = 0
    reconcile_status: _ReconcileStatus = "completed"
    reconcile_errors_remaining: int = 0
    forge_submit_identity: bool = False
    forge_fetch_identity: bool = False
    forge_reconcile_identity: bool = False
    submit_calls: int = 0
    fetch_calls: int = 0
    reconcile_calls: int = 0
    submit_requests: list[DomainSubmitRequest[dict[str, str]]] = field(
        default_factory=list
    )
    fetch_requests: list[DomainFetchRequest] = field(default_factory=list)
    reconcile_requests: list[DomainReconcileRequest] = field(default_factory=list)

    def submit(
        self,
        request: DomainSubmitRequest[dict[str, str]],
    ) -> DomainSubmitReceipt:
        self.submit_calls += 1
        self.submit_requests.append(request)
        if self.submit_error is not None:
            raise self.submit_error
        submission_id = request.submission_id
        identity = request.identity
        if self.forge_submit_identity:
            identity = identity.model_copy(update={"artifact_id": "forged-artifact"})
        if self.submit_status == "submitted":
            return DomainSubmitReceipt(
                identity=identity,
                status="submitted",
                job_id=f"job-{submission_id.generation}",
            )
        if self.submit_status == "not_submitted":
            return DomainSubmitReceipt(
                identity=identity,
                status="not_submitted",
                problems=(_problem("domain_submit_not_submitted"),),
            )
        return DomainSubmitReceipt(
            identity=identity,
            status="unknown",
            job_id=f"possible-job-{submission_id.generation}",
            problems=(_problem("domain_submit_unknown"),),
        )

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[str]:
        self.fetch_calls += 1
        self.fetch_requests.append(request)
        if self.fetch_errors_remaining:
            self.fetch_errors_remaining -= 1
            msg = "injected repeatable fetch failure"
            raise RuntimeError(msg)
        identity = request.identity
        job_id = request.job_id
        if self.forge_fetch_identity:
            identity = identity.model_copy(update={"artifact_id": "forged-artifact"})
        status = self.fetch_statuses.pop(0)
        if status == "fetched":
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    identity=identity,
                    job_id=job_id,
                    status="fetched",
                    result_fingerprint="result-fingerprint",
                    result_count=1,
                ),
                result="accepted-payload",
            )
        if status == "pending":
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    identity=identity,
                    job_id=job_id,
                    status="pending",
                )
            )
        return DomainFetchCandidate(
            receipt=DomainFetchReceipt(
                identity=identity,
                job_id=job_id,
                status=status,
                problems=(_problem(f"domain_fetch_{status}"),),
            )
        )

    def reconcile(
        self,
        request: DomainReconcileRequest,
    ) -> DomainReconcileReceipt:
        self.reconcile_calls += 1
        self.reconcile_requests.append(request)
        if self.reconcile_errors_remaining:
            self.reconcile_errors_remaining -= 1
            msg = "injected repeatable reconciliation failure"
            raise RuntimeError(msg)
        submission_id = request.submission_id
        identity = request.identity
        if self.forge_reconcile_identity:
            identity = identity.model_copy(update={"artifact_id": "forged-artifact"})
        if self.reconcile_status == "absent":
            return DomainReconcileReceipt(identity=identity, status="absent")
        if self.reconcile_status == "unknown":
            return DomainReconcileReceipt(
                identity=identity,
                status="unknown",
                problems=(_problem("domain_reconcile_unknown"),),
            )
        return DomainReconcileReceipt(
            identity=identity,
            status=self.reconcile_status,
            job_id=f"job-{submission_id.generation}",
        )


def test_submit_returns_known_and_fetch_returns_correlated_with_durable_journal() -> (
    None
):
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime()
    journal = MemoryExecutionJournal()

    known = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
        submit_attempt=2,
    )
    accepted = fetch_domain_invocation(
        runtime,
        invocation.intent,
        known,
        journal=journal,
        fetch_attempt=3,
    )

    assert isinstance(known, KnownDomainSubmission)
    assert known.submission_id is submission_id
    assert known.origin == "submit"
    assert known.job_id == "job-1"
    assert isinstance(accepted, CorrelatedDomainFetch)
    assert accepted.result == "accepted-payload"
    assert runtime.submit_requests[0].submission_id is submission_id
    assert runtime.submit_requests[0].identity == domain_receipt_identity(
        submission_id,
        invocation.intent,
    )
    assert runtime.submit_requests[0].payload is invocation.payload
    assert len(runtime.fetch_requests) == 1
    assert runtime.fetch_requests[0].submission_id is submission_id
    assert runtime.fetch_requests[0].identity == runtime.submit_requests[0].identity
    assert runtime.fetch_requests[0].job_id == known.job_id
    assert [
        (entry.operation_id, entry.stage, entry.effect, entry.state, entry.attempt)
        for entry in journal.entries
    ] == [
        (
            submission_id.submit_operation_id,
            "domain_submit",
            "acquisition",
            "started",
            2,
        ),
        (
            submission_id.submit_operation_id,
            "domain_submit",
            "acquisition",
            "completed",
            2,
        ),
        (submission_id.fetch_operation_id, "domain_fetch", "read", "started", 3),
        (submission_id.fetch_operation_id, "domain_fetch", "read", "completed", 3),
    ]
    assert journal.entries[0].evidence["submission_generation"] == 1


def test_definitive_submit_absence_authorizes_exactly_one_new_generation() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(submit_status="not_submitted")
    journal = MemoryExecutionJournal()

    with pytest.raises(DomainSubmissionFailed) as captured:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=journal,
        )

    error = captured.value
    assert isinstance(error.absence, AbsentDomainSubmission)
    assert error.absence.submission_id == submission_id
    assert error.retry == "safe"
    retry = plan_domain_submission_retry(invocation.intent, error.absence)
    assert retry.generation == 2
    assert retry.semantic_operation_id == submission_id.semantic_operation_id
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_submit", "started"),
        ("domain_submit", "failed"),
    ]


def test_pending_fetch_can_repeat_without_resubmitting_or_payload_access() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(fetch_statuses=["pending", "fetched"])
    journal = MemoryExecutionJournal()
    known = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )

    pending = fetch_domain_invocation(
        runtime,
        invocation.intent,
        known,
        journal=journal,
    )
    accepted = fetch_domain_invocation(
        runtime,
        invocation.intent,
        known,
        journal=journal,
        fetch_attempt=2,
    )

    assert isinstance(pending, PendingDomainFetch)
    assert pending.submission is known
    assert isinstance(accepted, CorrelatedDomainFetch)
    assert runtime.submit_calls == 1
    assert runtime.fetch_calls == 2
    assert [request.identity for request in runtime.fetch_requests] == [
        domain_receipt_identity(submission_id, invocation.intent),
        domain_receipt_identity(submission_id, invocation.intent),
    ]
    fetch_entries = [
        entry for entry in journal.entries if entry.stage == "domain_fetch"
    ]
    assert [(entry.attempt, entry.state) for entry in fetch_entries] == [
        (1, "started"),
        (1, "completed"),
        (2, "started"),
        (2, "completed"),
    ]


def test_fetch_failure_retries_the_known_state_without_resubmitting() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(fetch_errors_remaining=1)
    journal = MemoryExecutionJournal()
    known = submit_domain_invocation(
        runtime,
        invocation,
        submission_id,
        journal=journal,
    )

    with pytest.raises(DomainFetchFailed) as captured:
        fetch_domain_invocation(
            runtime,
            invocation.intent,
            known,
            journal=journal,
        )
    accepted = fetch_domain_invocation(
        runtime,
        invocation.intent,
        known,
        journal=journal,
        fetch_attempt=2,
    )

    assert captured.value.retry == "safe"
    assert captured.value.certainty == "indeterminate"
    assert isinstance(accepted, CorrelatedDomainFetch)
    assert runtime.submit_calls == 1
    assert runtime.fetch_calls == 2


@pytest.mark.parametrize(
    ("status", "journal_state"),
    [("not_found", "failed"), ("unknown", "unknown")],
)
def test_negative_fetch_receipts_remain_repeatable_failures(
    status: Literal["not_found", "unknown"],
    journal_state: Literal["failed", "unknown"],
) -> None:
    invocation = _closed_invocation()
    runtime = _ScriptedRuntime(fetch_statuses=[status])
    journal = MemoryExecutionJournal()
    known = submit_domain_invocation(
        runtime,
        invocation,
        _submission_id(invocation),
        journal=journal,
    )

    with pytest.raises(DomainFetchFailed) as captured:
        fetch_domain_invocation(
            runtime,
            invocation.intent,
            known,
            journal=journal,
        )

    assert captured.value.retry == "safe"
    assert captured.value.certainty == (
        "indeterminate" if status == "unknown" else "known"
    )
    assert runtime.submit_calls == runtime.fetch_calls == 1
    assert journal.entries[-1].stage == "domain_fetch"
    assert journal.entries[-1].state == journal_state


def test_uncertain_submit_reconciles_to_known_and_fetches_without_payload() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(submit_error=RuntimeError("response lost"))
    journal = MemoryExecutionJournal()

    with pytest.raises(DomainSubmissionIndeterminate) as captured:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=journal,
            submit_attempt=2,
        )

    uncertainty = captured.value.uncertainty
    assert isinstance(uncertainty, UncertainDomainSubmission)
    assert uncertainty.submission_id is submission_id
    assert uncertainty.submit_call_attempt == 2
    known = reconcile_domain_invocation(
        runtime,
        invocation.intent,
        uncertainty,
        journal=journal,
    )
    assert isinstance(known, KnownDomainSubmission)
    accepted = fetch_domain_invocation(
        runtime,
        invocation.intent,
        known,
        journal=journal,
    )

    assert known.origin == "reconcile"
    assert known.status == "completed"
    assert isinstance(accepted, CorrelatedDomainFetch)
    assert runtime.submit_calls == runtime.reconcile_calls == runtime.fetch_calls == 1
    assert runtime.reconcile_requests[0].identity == domain_receipt_identity(
        submission_id,
        invocation.intent,
    )
    assert runtime.fetch_requests[0].identity == runtime.reconcile_requests[0].identity
    latest = {entry.operation_id: entry for entry in journal.entries}
    assert latest[submission_id.submit_operation_id].state == "completed"
    assert (
        latest[submission_id.submit_operation_id].evidence["resolved_by_operation_id"]
        == submission_id.reconcile_operation_id
    )
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_submit", "started"),
        ("domain_submit", "unknown"),
        ("domain_reconcile", "started"),
        ("domain_submit", "completed"),
        ("domain_reconcile", "completed"),
        ("domain_fetch", "started"),
        ("domain_fetch", "completed"),
    ]


@pytest.mark.parametrize("runtime_raises", [False, True])
def test_reconciliation_unknown_or_exception_preserves_recovery_authority(
    *,
    runtime_raises: bool,
) -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(
        submit_error=RuntimeError("response lost"),
        reconcile_status="unknown",
        reconcile_errors_remaining=int(runtime_raises),
    )
    journal = MemoryExecutionJournal()
    with pytest.raises(DomainSubmissionIndeterminate) as submit_error:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=journal,
        )

    uncertainty = submit_error.value.uncertainty
    with pytest.raises(DomainReconciliationFailed) as reconcile_error:
        reconcile_domain_invocation(
            runtime,
            invocation.intent,
            uncertainty,
            journal=journal,
        )

    assert reconcile_error.value.uncertainty is uncertainty
    assert reconcile_error.value.retry == "safe"
    assert runtime.reconcile_calls == 1
    assert journal.entries[-1].stage == "domain_reconcile"
    assert journal.entries[-1].state == "unknown"


def test_absence_is_the_only_authority_for_a_new_submission_generation() -> None:
    invocation = _closed_invocation()
    first_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(submit_error=RuntimeError("response lost"))
    journal = MemoryExecutionJournal()
    with pytest.raises(DomainSubmissionIndeterminate) as captured:
        submit_domain_invocation(runtime, invocation, first_id, journal=journal)
    runtime.submit_error = None
    runtime.reconcile_status = "absent"
    absence = reconcile_domain_invocation(
        runtime,
        invocation.intent,
        captured.value.uncertainty,
        journal=journal,
    )

    assert isinstance(absence, AbsentDomainSubmission)
    second_id = plan_domain_submission_retry(invocation.intent, absence)
    assert second_id.generation == 2
    assert second_id.submission_key != first_id.submission_key
    calls_before_rejected_retry = runtime.submit_calls
    with pytest.raises(ProviderContractError, match="domain_retry_not_authorized"):
        submit_domain_invocation(
            runtime,
            invocation,
            second_id,
            journal=journal,
        )
    assert runtime.submit_calls == calls_before_rejected_retry

    runtime.submit_status = "submitted"
    known = submit_domain_invocation(
        runtime,
        invocation,
        second_id,
        journal=journal,
        retry_from=absence,
        submit_attempt=2,
    )

    assert isinstance(known, KnownDomainSubmission)
    assert known.submission_id is second_id
    assert known.job_id == "job-2"
    assert first_id.submit_operation_id != second_id.submit_operation_id
    assert first_id.submission_key in first_id.submit_operation_id
    assert second_id.submission_key in second_id.submit_operation_id
    submit_operation_ids = {
        entry.operation_id
        for entry in journal.entries
        if entry.stage == "domain_submit"
    }
    assert first_id.submit_operation_id in submit_operation_ids
    assert second_id.submit_operation_id in submit_operation_ids


@dataclass
class _NoSequenceJournal:
    append_calls: int = 0

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self.append_calls += 1
        return entry.model_copy(deep=True)


@dataclass
class _FailSecondAppendJournal:
    committed: MemoryExecutionJournal = field(default_factory=MemoryExecutionJournal)
    append_calls: int = 0

    @property
    def entries(self) -> tuple[ExecutionTransition, ...]:
        return self.committed.entries

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self.append_calls += 1
        if self.append_calls == 2:
            raise RuntimeError("injected post-submit journal failure")
        return self.committed.append(entry)


@dataclass
class _FailOnAppendJournal:
    fail_calls: set[int]
    committed: MemoryExecutionJournal = field(default_factory=MemoryExecutionJournal)
    append_calls: int = 0

    @property
    def entries(self) -> tuple[ExecutionTransition, ...]:
        return self.committed.entries

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self.append_calls += 1
        if self.append_calls in self.fail_calls:
            raise RuntimeError(f"injected journal failure {self.append_calls}")
        return self.committed.append(entry)


def test_domain_effects_reject_non_committing_journals_before_runtime_calls() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)

    runtime = _ScriptedRuntime()
    with pytest.raises(DomainRuntimePersistenceError) as captured:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=_NoSequenceJournal(),
        )
    assert captured.value.retry == "safe"
    assert captured.value.certainty == "known"
    assert runtime.submit_calls == 0


def test_post_submit_persistence_failure_carries_reconciliation_authority() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime()
    journal = _FailSecondAppendJournal()

    with pytest.raises(DomainRuntimePersistenceError) as captured:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=journal,
            submit_attempt=2,
        )

    error = captured.value
    assert error.retry == "after_reconciliation"
    assert error.certainty == "indeterminate"
    assert error.job_id == "job-1"
    assert error.uncertainty is not None
    assert error.uncertainty.reason == "persistence"
    assert error.uncertainty.submit_call_attempt == 2
    assert runtime.submit_calls == 1
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_submit", "started")
    ]

    known = reconcile_domain_invocation(
        runtime,
        invocation.intent,
        error.uncertainty,
        journal=journal,
    )

    assert isinstance(known, KnownDomainSubmission)
    assert runtime.submit_calls == 1
    assert runtime.reconcile_calls == 1
    latest = {entry.operation_id: entry for entry in journal.entries}
    assert latest[submission_id.submit_operation_id].state == "completed"


def test_definitive_absence_is_not_exposed_when_final_journal_write_fails() -> None:
    invocation = _closed_invocation()
    runtime = _ScriptedRuntime(submit_status="not_submitted")
    journal = _FailOnAppendJournal({2})

    with pytest.raises(DomainRuntimePersistenceError) as captured:
        submit_domain_invocation(
            runtime,
            invocation,
            _submission_id(invocation),
            journal=journal,
        )

    error = captured.value
    assert error.retry == "after_reconciliation"
    assert error.certainty == "indeterminate"
    assert error.uncertainty is not None
    assert error.uncertainty.reason == "persistence"
    assert runtime.submit_calls == 1


def test_fetch_result_persistence_failure_is_safely_repeatable() -> None:
    invocation = _closed_invocation()
    runtime = _ScriptedRuntime()
    journal = _FailOnAppendJournal({4})
    known = submit_domain_invocation(
        runtime,
        invocation,
        _submission_id(invocation),
        journal=journal,
    )

    with pytest.raises(DomainRuntimePersistenceError) as captured:
        fetch_domain_invocation(
            runtime,
            invocation.intent,
            known,
            journal=journal,
        )

    error = captured.value
    assert error.phase == "fetch"
    assert error.retry == "safe"
    assert error.certainty == "known"
    assert error.uncertainty is None
    assert runtime.fetch_calls == 1


@pytest.mark.parametrize(
    ("failed_append", "submit_state", "certainty"),
    [(4, "unknown", "indeterminate"), (5, "completed", "known")],
)
def test_reconcile_journal_failures_preserve_safe_resolution_order(
    failed_append: int,
    submit_state: Literal["unknown", "completed"],
    certainty: Literal["indeterminate", "known"],
) -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime(submit_error=RuntimeError("response lost"))
    journal = _FailOnAppendJournal({failed_append})
    with pytest.raises(DomainSubmissionIndeterminate) as submit_error:
        submit_domain_invocation(
            runtime,
            invocation,
            submission_id,
            journal=journal,
        )

    with pytest.raises(DomainRuntimePersistenceError) as captured:
        reconcile_domain_invocation(
            runtime,
            invocation.intent,
            submit_error.value.uncertainty,
            journal=journal,
        )

    error = captured.value
    assert error.phase == "reconcile"
    assert error.retry == "safe"
    assert error.certainty == certainty
    latest = {entry.operation_id: entry for entry in journal.entries}
    assert latest[submission_id.submit_operation_id].state == submit_state
    assert runtime.submit_calls == runtime.reconcile_calls == 1


def test_runtime_state_constructors_establish_their_invariants() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    identity = domain_receipt_identity(submission_id, invocation.intent)
    submitted = DomainSubmitReceipt(
        identity=identity,
        status="submitted",
        job_id="job-1",
    )
    not_submitted = DomainSubmitReceipt(
        identity=identity,
        status="not_submitted",
        problems=(_problem("not_submitted"),),
    )
    fetched = DomainFetchReceipt(
        identity=identity,
        job_id="job-1",
        status="fetched",
        result_fingerprint="result-fingerprint",
        result_count=1,
    )
    pending = DomainFetchReceipt(
        identity=identity,
        job_id="job-1",
        status="pending",
    )

    known = KnownDomainSubmission(submission_id, submitted, "submit")
    absence = AbsentDomainSubmission(submission_id, not_submitted, "submit")
    uncertainty = UncertainDomainSubmission(
        submission_id,
        identity,
        reason="runtime_exception",
        submit_call_attempt=1,
        job_id_hint=None,
        problems=(_problem(),),
    )
    correlated = CorrelatedDomainFetch(receipt=fetched, result="payload")
    pending_fetch = PendingDomainFetch(known, pending)

    assert known.job_id == "job-1"
    assert absence.identity == identity
    assert uncertainty.identity == identity
    assert correlated.receipt is fetched
    assert correlated.result == "payload"
    assert pending_fetch.submission is known

    with pytest.raises(ValueError, match="known submit state"):
        KnownDomainSubmission(submission_id, not_submitted, "submit")
    with pytest.raises(ValueError, match="definitive negative evidence"):
        AbsentDomainSubmission(submission_id, submitted, "submit")
    with pytest.raises(ValueError, match="pending receipt"):
        PendingDomainFetch(known, fetched)


def test_fetch_requires_correlated_stage_values_before_runtime_calls() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)
    runtime = _ScriptedRuntime()

    foreign_invocation = _closed_invocation(adapter_intent={"different": True})
    foreign_submission_id = plan_domain_submission(
        foreign_invocation,
        run_id=submission_id.run_id,
        semantic_operation_id=submission_id.semantic_operation_id,
    )
    foreign_known = KnownDomainSubmission(
        foreign_submission_id,
        DomainSubmitReceipt(
            identity=domain_receipt_identity(
                foreign_submission_id,
                foreign_invocation.intent,
            ),
            status="submitted",
            job_id="foreign-job",
        ),
        "submit",
    )
    with pytest.raises(ValueError, match="does not belong"):
        fetch_domain_invocation(
            runtime,
            invocation.intent,
            foreign_known,
            journal=MemoryExecutionJournal(),
        )
    assert runtime.fetch_calls == 0


def test_provider_correlation_forgery_never_yields_sealed_state() -> None:
    invocation = _closed_invocation()
    submission_id = _submission_id(invocation)

    forged_submit = _ScriptedRuntime(forge_submit_identity=True)
    with pytest.raises(DomainSubmissionIndeterminate) as submit_error:
        submit_domain_invocation(
            forged_submit,
            invocation,
            submission_id,
            journal=MemoryExecutionJournal(),
        )
    assert submit_error.value.problems[0].code == "domain_submit_receipt_invalid"

    forged_fetch = _ScriptedRuntime(forge_fetch_identity=True)
    fetch_journal = MemoryExecutionJournal()
    known = submit_domain_invocation(
        forged_fetch,
        invocation,
        submission_id,
        journal=fetch_journal,
    )
    with pytest.raises(DomainFetchFailed) as fetch_error:
        fetch_domain_invocation(
            forged_fetch,
            invocation.intent,
            known,
            journal=fetch_journal,
        )
    assert fetch_error.value.problems[0].code == "domain_fetch_receipt_invalid"

    forged_reconcile = _ScriptedRuntime(
        submit_error=RuntimeError("response lost"),
        forge_reconcile_identity=True,
    )
    reconcile_journal = MemoryExecutionJournal()
    with pytest.raises(DomainSubmissionIndeterminate) as uncertain_error:
        submit_domain_invocation(
            forged_reconcile,
            invocation,
            submission_id,
            journal=reconcile_journal,
        )
    with pytest.raises(DomainReconciliationFailed) as reconcile_error:
        reconcile_domain_invocation(
            forged_reconcile,
            invocation.intent,
            uncertain_error.value.uncertainty,
            journal=reconcile_journal,
        )
    assert reconcile_error.value.problems[0].code == (
        "domain_reconcile_receipt_invalid"
    )
