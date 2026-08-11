from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from pydantic import ValidationError
from scopecat_testkit.execution_fakes import FakeExecutionJournal

from scopecat.kernel.errors import (
    DomainExecutionFailed,
    DomainRuntimePersistenceError,
)
from scopecat.kernel.problems import Problem, ProblemPhase, problem
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    close_domain_invocation,
)
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainExecutionResult,
    execute_domain_invocation,
    plan_domain_execution,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
)

type _Invocation = ClosedDomainInvocation[str, dict[str, str]]


class _NoopInstrumentExecutor:
    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        del batch
        raise AssertionError("runtime test must not execute instrument work")


@dataclass(frozen=True, slots=True)
class _RuntimeResultContract:
    contract_fingerprint: str = "runtime-result-contract"


def _problem(code: str = "domain_test_failure") -> Problem:
    return problem(
        code,
        "the test domain operation did not complete",
        phase=ProblemPhase.EXECUTION,
    )


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
        execution_summary={"instruments": ["instrument-a"]},
        target_intent={"realization": "iq"} if target_intent is None else target_intent,
        payload={"compiled": "payload"},
    )


def _execution_id(invocation: _Invocation) -> DomainExecutionId:
    return plan_domain_execution(
        invocation,
        run_id="run-domain",
        logical_compute_node_id="domain.batch",
    )


def test_receipts_encode_success_rejection_and_unknown_only() -> None:
    completed = DomainExecutionReceipt(
        execution_key="execution-key",
        status="completed",
        result_fingerprint="result",
        result_count=1,
    )
    rejected = DomainExecutionReceipt(
        execution_key="execution-key",
        status="not_executed",
        problems=(_problem(),),
    )
    unknown = DomainExecutionReceipt(
        execution_key="execution-key",
        status="unknown",
        problems=(_problem(),),
    )

    assert DomainExecutionResult(completed, "payload").result == "payload"
    assert rejected.status == "not_executed"
    assert unknown.status == "unknown"


@pytest.mark.parametrize(
    "receipt",
    [
        lambda: DomainExecutionReceipt(
            execution_key="execution-key", status="completed"
        ),
        lambda: DomainExecutionReceipt(execution_key="execution-key", status="unknown"),
        lambda: DomainExecutionReceipt(
            execution_key="execution-key",
            status="not_executed",
            result_fingerprint="result",
            result_count=1,
            problems=(_problem(),),
        ),
    ],
)
def test_receipts_reject_contradictory_evidence(
    receipt: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        receipt()


def test_execution_identity_is_deterministic_and_covers_intent() -> None:
    invocation = _closed_invocation()
    changed = _closed_invocation(target_intent={"realization": "raw"})
    first = _execution_id(invocation)
    repeated = _execution_id(invocation)
    changed_id = plan_domain_execution(
        changed,
        run_id=first.run_id,
        logical_compute_node_id=first.logical_compute_node_id,
    )

    assert first == repeated
    assert first.execution_key != changed_id.execution_key
    assert "execution_key" not in first.model_dump(mode="json")


@dataclass
class _Runtime:
    status: Literal["completed", "not_executed", "unknown"] = "completed"
    error: Exception | None = None
    forge_key: bool = False
    execute_calls: int = 0
    execution_keys: list[str] = field(default_factory=list)

    def execute(
        self,
        execution_key: str,
        payload: dict[str, str],
        *,
        instruments: object,
    ) -> DomainExecutionReceipt | DomainExecutionResult[str]:
        del payload, instruments
        self.execute_calls += 1
        self.execution_keys.append(execution_key)
        if self.error is not None:
            raise self.error
        receipt_key = "forged" if self.forge_key else execution_key
        if self.status == "completed":
            return DomainExecutionResult(
                DomainExecutionReceipt(
                    execution_key=receipt_key,
                    status="completed",
                    result_fingerprint="result",
                    result_count=1,
                ),
                "payload",
            )
        return DomainExecutionReceipt(
            execution_key=receipt_key,
            status=self.status,
            problems=(_problem(f"execute_{self.status}"),),
        )


def _execute(
    runtime: _Runtime,
    invocation: _Invocation,
    journal: FakeExecutionJournal,
) -> DomainExecutionResult[str]:
    return execute_domain_invocation(
        runtime,
        invocation,
        _execution_id(invocation),
        instruments=_NoopInstrumentExecutor(),
        journal=journal,
    )


def test_synchronous_execution_commits_one_exact_journal_boundary() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()
    journal = FakeExecutionJournal()

    result = _execute(runtime, invocation, journal)

    assert result.result == "payload"
    assert runtime.execution_keys == [_execution_id(invocation).execution_key]
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("domain_execute", "started"),
        ("domain_execute", "completed"),
    ]
    evidence = journal.entries[0].evidence["invocation_intent"]
    assert isinstance(evidence, dict)
    assert evidence["execution_summary"] == {"instruments": ["instrument-a"]}
    assert "invocation_intent" not in journal.entries[1].evidence
    assert journal.entries[1].evidence["intent_fingerprint"] == (
        invocation.intent.intent_fingerprint
    )
    assert journal.entries[1].evidence["receipt"] == result.receipt.model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    ("status", "certainty", "state"),
    [
        ("not_executed", "known", "failed"),
        ("unknown", "indeterminate", "unknown"),
    ],
)
def test_negative_outcomes_preserve_certainty(
    status: Literal["not_executed", "unknown"],
    certainty: str,
    state: str,
) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(status=status)
    journal = FakeExecutionJournal()

    with pytest.raises(DomainExecutionFailed) as caught:
        _execute(runtime, invocation, journal)

    assert caught.value.certainty == certainty
    assert journal.entries[-1].state == state


def test_runtime_exception_and_forged_receipt_are_indeterminate() -> None:
    invocation = _closed_invocation()
    for runtime in (_Runtime(error=RuntimeError("lost")), _Runtime(forge_key=True)):
        journal = FakeExecutionJournal()
        with pytest.raises(DomainExecutionFailed) as caught:
            _execute(runtime, invocation, journal)
        assert caught.value.certainty == "indeterminate"
        assert journal.entries[-1].state == "unknown"


@dataclass
class _NoSequenceJournal:
    def claim(self, entry: ExecutionTransition) -> ExecutionTransition:
        return entry.model_copy(deep=True)

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        return entry.model_copy(deep=True)


def test_execution_intent_must_be_durable_before_provider_call() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()

    with pytest.raises(DomainRuntimePersistenceError) as caught:
        execute_domain_invocation(
            runtime,
            invocation,
            _execution_id(invocation),
            instruments=_NoopInstrumentExecutor(),
            journal=_NoSequenceJournal(),
        )

    assert caught.value.certainty == "known"
    assert runtime.execute_calls == 0


def test_unknown_execution_key_cannot_reenter_the_runtime() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(error=RuntimeError("receipt lost"))
    journal = FakeExecutionJournal()

    with pytest.raises(DomainExecutionFailed) as first:
        _execute(runtime, invocation, journal)
    assert first.value.certainty == "indeterminate"
    assert runtime.execute_calls == 1

    runtime.error = None
    with pytest.raises(DomainRuntimePersistenceError) as repeated:
        _execute(runtime, invocation, journal)

    assert repeated.value.certainty == "known"
    assert runtime.execute_calls == 1
