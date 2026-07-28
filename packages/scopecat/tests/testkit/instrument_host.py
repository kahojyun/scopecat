"""Test-only in-process adapter for the daemon instrument-host port."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat.execution.ports.instruments import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareCollect,
    RunHardwareFinalizationReceipt,
    RunHardwareValue,
)
from scopecat.kernel.problems import Problem
from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    state_target_identity,
)
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    apply_state_command_to_snapshot,
)
from scopecat.sdk.runtime_problems import runtime_problem


class TestRunInstrumentHost:
    """Adapt explicit fixture drivers without entering production execution code."""

    __test__ = False

    def __init__(
        self,
        drivers: Iterable[InstrumentDriver] = (),
        *,
        provider_id: str | None = None,
        ready: bool = True,
        setup_problems: tuple[Problem, ...] = (),
    ) -> None:
        selected = tuple(drivers)
        self._drivers = {driver.instrument_id: driver for driver in selected}
        self._descriptions = tuple(driver.describe() for driver in selected)
        self._provider_id = provider_id
        self._ready = ready
        self._setup_problems = setup_problems
        self._initial_state = tuple(driver.read_state() for driver in selected)
        self._current_states = {
            state.instrument_id: state for state in self._initial_state
        }
        self._finished: RunHardwareFinalizationReceipt | None = None

    @property
    def provider_id(self) -> str | None:
        return self._provider_id

    @property
    def descriptions(self) -> tuple[InstrumentDescription, ...]:
        return self._descriptions

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def setup_problems(self) -> tuple[Problem, ...]:
        return self._setup_problems

    @property
    def initial_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._initial_state

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        values: list[RunHardwareValue] = []
        problems: list[Problem] = []
        indeterminate = False
        for action in batch.actions:
            driver = self._drivers[action.instrument_id]
            if isinstance(action, RunHardwareApply):
                current = self._current_states[action.instrument_id]
                fields = [
                    field
                    for field in action.fields
                    if _state_value(current, field) != field.value
                ]
                if not fields:
                    continue
                command = InstrumentStateCommand(
                    operation_id=action.operation_id,
                    instrument_id=action.instrument_id,
                    fields=fields,
                    payloads=action.payloads,
                )
                receipt = driver.apply_state(command)
                problems.extend(receipt.problems)
                if receipt.status != "applied":
                    indeterminate = receipt.status == "unknown"
                    break
                self._current_states[action.instrument_id] = (
                    receipt.state or apply_state_command_to_snapshot(current, command)
                )
                continue
            assert isinstance(action, RunHardwareCollect)
            receipt = driver.collect(
                CollectCommand(
                    operation_id=action.operation_id,
                    instrument_id=action.instrument_id,
                    point_index=action.point_index,
                    point_count=action.point_count,
                    requests=list(action.requests),
                )
            )
            problems.extend(receipt.problems)
            if receipt.status != "collected" or receipt.readback is None:
                indeterminate = receipt.status == "unknown"
                break
            bindings = {
                binding.provider_key: binding.product_use_ids
                for binding in action.bindings
            }
            if set(receipt.readback.values) != set(bindings):
                problems.append(
                    runtime_problem(
                        "instrument_unexpected_product",
                        "instrument readback does not match requested products",
                        run_id="test-run",
                    )
                )
                break
            values.extend(
                RunHardwareValue(
                    point_index=action.point_index,
                    product_use_id=product_use_id,
                    value=value,
                )
                for provider_key, value in receipt.readback.values.items()
                for product_use_id in bindings[provider_key]
            )
        return RunHardwareBatchReceipt(
            operation_id=batch.operation_id,
            values=tuple(values),
            problems=tuple(problems),
            indeterminate=indeterminate,
        )

    def finish(
        self,
        *,
        operation_id: str,
        failed: bool,
    ) -> RunHardwareFinalizationReceipt:
        if self._finished is not None:
            return self._finished
        for driver in reversed(tuple(self._drivers.values())):
            driver.abort() if failed else driver.cleanup()
        final_state = tuple(driver.read_state() for driver in self._drivers.values())
        for driver in reversed(tuple(self._drivers.values())):
            driver.close()
        self._finished = RunHardwareFinalizationReceipt(
            operation_id=operation_id,
            final_state=final_state,
        )
        return self._finished


def _state_value(
    current: InstrumentStateSnapshot,
    target: InstrumentStateCommandField,
) -> object:
    identity = state_target_identity(
        target.capability_id,
        target.field_path,
        target.entity_ids,
        target.channel_bindings,
    )
    return next(
        (
            field.value
            for field in current.fields
            if state_target_identity(
                field.capability_id,
                field.field_path,
                field.entity_ids,
                field.channel_bindings,
            )
            == identity
        ),
        None,
    )


def provision_test_instrument_host(
    provider: InstrumentProvider | None,
    *,
    context: InstrumentProviderContext,
) -> TestRunInstrumentHost:
    """Provision fixture drivers outside the production Notebook executor."""

    if not context.instrument_ids:
        return TestRunInstrumentHost()
    if provider is None:
        raise ValueError("instrument claims require a test instrument provider")
    result = provider.provide(context)
    if result.problems:
        for driver in reversed(result.drivers):
            driver.close()
        return TestRunInstrumentHost(
            provider_id=provider.provider_id,
            ready=False,
            setup_problems=result.problems,
        )
    return TestRunInstrumentHost(
        result.drivers,
        provider_id=provider.provider_id,
    )


__all__ = ["TestRunInstrumentHost", "provision_test_instrument_host"]
