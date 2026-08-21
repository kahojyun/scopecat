from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from scopecat.kernel.errors import DomainExecutionFailed
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem, ProblemPhase, problem
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
    close_domain_invocation,
)
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainExecutionCancellationRequested,
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


def _closed_invocation(
    *,
    target_intent: Mapping[str, JsonValue] | None = None,
) -> _Invocation:
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


def test_invocation_intent_retains_structured_target_context() -> None:
    intent = _closed_invocation().intent
    document = intent.model_dump(mode="json")

    assert document["target_intent"] == {"realization": "iq"}
    assert "target_intent_fingerprint" not in document
    with pytest.raises(
        ValidationError,
        match="fingerprint does not cover its complete intent",
    ):
        DomainInvocationIntent.model_validate(
            {**document, "target_intent": {"realization": "raw"}}
        )


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
) -> DomainExecutionResult[str]:
    return execute_domain_invocation(
        runtime,
        invocation,
        _execution_id(invocation),
        instruments=_NoopInstrumentExecutor(),
    )


def test_synchronous_execution_returns_correlated_result() -> None:
    invocation = _closed_invocation()
    runtime = _Runtime()

    result = _execute(runtime, invocation)

    assert result.result == "payload"
    assert runtime.execution_keys == [_execution_id(invocation).execution_key]


@pytest.mark.parametrize(
    ("status", "certainty"),
    [
        ("not_executed", "known"),
        ("unknown", "indeterminate"),
    ],
)
def test_negative_outcomes_preserve_certainty(
    status: Literal["not_executed", "unknown"],
    certainty: str,
) -> None:
    invocation = _closed_invocation()
    runtime = _Runtime(status=status)
    with pytest.raises(DomainExecutionFailed) as caught:
        _execute(runtime, invocation)

    assert caught.value.certainty == certainty


def test_runtime_exception_and_forged_receipt_are_indeterminate() -> None:
    invocation = _closed_invocation()
    for runtime in (_Runtime(error=RuntimeError("lost")), _Runtime(forge_key=True)):
        with pytest.raises(DomainExecutionFailed) as caught:
            _execute(runtime, invocation)
        assert caught.value.certainty == "indeterminate"


def test_cancellation_control_flow_is_not_normalized_as_domain_failure() -> None:
    invocation = _closed_invocation()
    cancellation = DomainExecutionCancellationRequested()

    with pytest.raises(DomainExecutionCancellationRequested) as caught:
        _execute(_Runtime(error=cancellation), invocation)

    assert caught.value is cancellation
