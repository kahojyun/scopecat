from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from scopecat.execution.effects.domain import _RequirementReconciledRuntime
from scopecat.kernel.errors import OperationFailure
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.sdk.domain.execution import (
    DomainStateAddress,
    DomainStateRequirement,
    ErasedDomainInvocation,
    ErasedDomainRealizer,
    ErasedDomainRuntime,
    ErasedDomainSetup,
    PreparedDomainExecution,
)
from scopecat.sdk.domain.runtime import DomainExecutionReceipt, DomainExecutionResult
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
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
    def realize(
        _result: DomainExecutionResult[object],
    ) -> tuple[MeasurementValueCandidate, ...]:
        return ()

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
        realize=cast("ErasedDomainRealizer", realize),
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
