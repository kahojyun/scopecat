from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from scopecat.execution.effect_interpreter import (
    _CancellationAwareDomainInstruments,
)
from scopecat.execution.effects.domain import (
    _RequirementReconciledRuntime,
    execute_domain_job_values,
)
from scopecat.kernel.errors import OperationFailure
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.domain.execution import (
    DomainStateAddress,
    DomainStateRequirement,
    ErasedDomainInvocation,
    ErasedDomainRealizer,
    ErasedDomainRuntime,
    ErasedDomainSetup,
    PreparedDomainExecution,
)
from scopecat.sdk.domain.invocation import close_domain_invocation
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainExecutionCancellationRequested,
    DomainExecutionReceipt,
    DomainExecutionResult,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareInvoke,
    RunInstrumentHost,
)


def _failure():
    return problem(
        "injected_setup_failure",
        "the injected setup operation was rejected",
        phase=ProblemPhase.EXECUTION,
    )


@dataclass
class _Setup:
    failure: OperationFailure | None = None
    calls: int = 0

    def prepare(
        self,
        execution_key: str,
        payload: object,
        *,
        instruments: object,
    ) -> None:
        del execution_key, payload, instruments
        self.calls += 1
        if self.failure is not None:
            raise self.failure


@dataclass
class _Realtime:
    calls: int = 0

    def execute(
        self,
        execution_key: str,
        payload: object,
        *,
        instruments: object,
    ) -> DomainExecutionReceipt:
        del execution_key, payload, instruments
        self.calls += 1
        raise AssertionError("realtime execution must not start after setup failure")


@dataclass
class _Executor:
    receipt: RunHardwareBatchReceipt
    batches: list[RunHardwareBatch] = field(default_factory=list)

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        self.batches.append(batch)
        return self.receipt


def _prepared(
    *,
    setup: _Setup,
    realtime: _Realtime,
    requirements: tuple[DomainStateRequirement, ...] = (),
) -> PreparedDomainExecution:
    def realize_into(
        _result: DomainExecutionResult[object],
        _accept: object,
    ) -> None:
        return None

    return PreparedDomainExecution(
        instrument_ids=("awg",),
        setup_write_footprint=(),
        setup_state_invalidations=(),
        state_requirements=requirements,
        realtime_write_footprint=(),
        realtime_state_invalidations=(),
        next_batch_max_points=1,
        invocation=cast("ErasedDomainInvocation", object()),
        setup=cast("ErasedDomainSetup", setup),
        runtime=cast("ErasedDomainRuntime", realtime),
        realize_into=cast("ErasedDomainRealizer", realize_into),
    )


def _requirement() -> DomainStateRequirement:
    return DomainStateRequirement(
        address=DomainStateAddress(
            instrument_id="awg",
            interface_id="test.output/v1",
            component_path=("outputs", "ch1"),
            property_id="offset",
        ),
        value=StateValue(Quantity(0.0, "V")),
    )


def test_known_setup_rejection_returns_not_executed() -> None:
    setup = _Setup(OperationFailure((_failure(),)))
    realtime = _Realtime()
    runtime = _RequirementReconciledRuntime(_prepared(setup=setup, realtime=realtime))

    receipt = runtime.execute(
        "execution-key",
        object(),
        instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
    )

    assert isinstance(receipt, DomainExecutionReceipt)
    assert receipt.status == "not_executed"
    assert receipt.problems == (_failure(),)
    assert setup.calls == 1
    assert realtime.calls == 0


def test_completion_is_observed_before_result_realization() -> None:
    @dataclass(frozen=True, slots=True)
    class ResultContract:
        contract_fingerprint: str = "test-result-contract"

    class Runtime:
        def execute(
            self,
            execution_key: str,
            payload: object,
            *,
            instruments: object,
        ) -> DomainExecutionResult[object]:
            del payload, instruments
            return DomainExecutionResult(
                DomainExecutionReceipt(
                    execution_key=execution_key,
                    status="completed",
                    result_fingerprint="result-fingerprint",
                    result_count=1,
                    execution_evidence={"selected_channel": "a"},
                ),
                object(),
            )

    invocation = close_domain_invocation(
        cast(
            "DomainResultMapping[str]",
            cast("object", ResultContract()),
        ),
        invocation_id="test-invocation",
        target_id="test-target",
        compiler_id="test-compiler",
        capability_fingerprint="test-capability",
        artifact_id="test-artifact",
        artifact_fingerprint="test-artifact-fingerprint",
        execution_summary={},
        target_intent={},
        payload=object(),
    )

    def fail_realization(
        _result: DomainExecutionResult[object],
        _accept: object,
    ) -> None:
        raise RuntimeError("result realization failed")

    prepared = PreparedDomainExecution(
        instrument_ids=(),
        setup_write_footprint=(),
        setup_state_invalidations=(),
        state_requirements=(),
        realtime_write_footprint=(),
        realtime_state_invalidations=(),
        next_batch_max_points=1,
        invocation=cast("ErasedDomainInvocation", invocation),
        setup=None,
        runtime=cast("ErasedDomainRuntime", Runtime()),
        realize_into=cast("ErasedDomainRealizer", fail_realization),
    )
    observed: list[DomainExecutionReceipt] = []

    with pytest.raises(RuntimeError, match="result realization failed"):
        execute_domain_job_values(
            prepared,
            logical_compute_node_id="test-node",
            run_id="test-run",
            instruments=_Executor(RunHardwareBatchReceipt(operation_id="unused")),
            accept=lambda _candidate: None,
            observe_completion=observed.append,
        )

    assert len(observed) == 1
    assert observed[0].execution_evidence == {"selected_channel": "a"}


def test_domain_instrument_batches_stop_at_the_next_cancellation_boundary() -> None:
    inner = _Executor(RunHardwareBatchReceipt(operation_id="first"))
    instruments = _CancellationAwareDomainInstruments(
        cast("RunInstrumentHost", cast("object", inner)),
        cancellation_requested=lambda: bool(inner.batches),
    )

    def batch(operation_id: str) -> RunHardwareBatch:
        return RunHardwareBatch(
            operation_id=operation_id,
            actions=(
                RunHardwareInvoke(
                    effect_id=operation_id,
                    instrument_id="awg",
                    resource_id="awg",
                    interface_id="test.noop/v1",
                    operation_id="noop",
                ),
            ),
        )

    first = instruments.execute(batch("first"))
    with pytest.raises(DomainExecutionCancellationRequested):
        instruments.execute(batch("second"))

    assert first.operation_id == "first"
    assert [batch.operation_id for batch in inner.batches] == ["first"]


def test_setup_success_then_requirement_rejection_skips_realtime() -> None:
    setup = _Setup()
    realtime = _Realtime()
    operation_id = "domain:execution-key:reconcile-requirements"
    instruments = _Executor(
        RunHardwareBatchReceipt(
            operation_id=operation_id,
            problems=(_failure(),),
        )
    )
    runtime = _RequirementReconciledRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            requirements=(_requirement(),),
        )
    )

    receipt = runtime.execute("execution-key", object(), instruments=instruments)

    assert isinstance(receipt, DomainExecutionReceipt)
    assert receipt.status == "not_executed"
    assert setup.calls == 1
    assert realtime.calls == 0
    assert [batch.operation_id for batch in instruments.batches] == [operation_id]


@pytest.mark.parametrize("receipt_kind", ["indeterminate", "mismatched"])
def test_uncertain_reconciliation_is_not_retried(
    receipt_kind: str,
) -> None:
    operation_id = "domain:execution-key:reconcile-requirements"
    receipt = RunHardwareBatchReceipt(
        operation_id=(
            "another-operation" if receipt_kind == "mismatched" else operation_id
        ),
        problems=(_failure(),) if receipt_kind == "indeterminate" else (),
        indeterminate=receipt_kind == "indeterminate",
    )
    setup = _Setup()
    realtime = _Realtime()
    instruments = _Executor(receipt)
    runtime = _RequirementReconciledRuntime(
        _prepared(
            setup=setup,
            realtime=realtime,
            requirements=(_requirement(),),
        )
    )

    with pytest.raises(RuntimeError):
        runtime.execute("execution-key", object(), instruments=instruments)

    assert setup.calls == 1
    assert realtime.calls == 0
    assert len(instruments.batches) == 1
