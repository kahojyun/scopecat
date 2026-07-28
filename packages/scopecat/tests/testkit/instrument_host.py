"""Test-only in-process adapter for the daemon instrument-host port."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from scopecat.execution.ports.instruments import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareCollect,
    RunHardwareFinalizationReceipt,
    RunHardwareInvoke,
    RunHardwareValue,
)
from scopecat.kernel.problems import Problem
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    property_target_identity,
)
from scopecat.sdk.domain.compiler import DomainCompiler
from scopecat.sdk.instruments import InstrumentBackend
from scopecat.sdk.instruments.contracts import (
    CollectCommand,
    InstrumentConnectionContext,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InvokeCommand,
    apply_state_command_to_snapshot,
)
from scopecat.sdk.payloads import EMPTY_PAYLOAD_CODECS, PayloadCodecRegistry
from scopecat.sdk.runtime_problems import runtime_problem


@dataclass(frozen=True, slots=True)
class TestInstrumentComposition:
    """Explicit planning and execution faces for an in-process test provider."""

    system: ExperimentSystem
    backend: InstrumentBackend


def compose_test_instruments(
    *,
    config: ConfigProfileSnapshot,
    provider: InstrumentProvider,
    domain_compiler: DomainCompiler | None = None,
    payload_codecs: PayloadCodecRegistry = EMPTY_PAYLOAD_CODECS,
) -> TestInstrumentComposition:
    backend = InstrumentBackend(
        provider=provider,
        payload_codecs=payload_codecs,
    )
    return TestInstrumentComposition(
        system=ExperimentSystem(
            instrument_catalog=resolve_instrument_contract_catalog(
                config=config,
                instrument_provider=provider,
            ),
            domain_compiler=domain_compiler,
            payload_codecs=payload_codecs,
        ),
        backend=backend,
    )


class TestRunInstrumentHost:
    """Adapt explicit fixture drivers without entering production execution code."""

    __test__ = False

    def __init__(
        self,
        drivers: Iterable[InstrumentDriver] = (),
        *,
        ready: bool = True,
        setup_problems: tuple[Problem, ...] = (),
    ) -> None:
        selected = tuple(drivers)
        self._drivers = {driver.instrument_id: driver for driver in selected}
        self._descriptions = {
            driver.instrument_id: driver.describe() for driver in selected
        }
        self._ready = ready
        self._setup_problems = setup_problems
        self._observed_state = tuple(driver.read_state() for driver in selected)
        self._prepared_state = self._observed_state
        self._assumed_states = {
            state.instrument_id: state for state in self._prepared_state
        }
        self._finished: RunHardwareFinalizationReceipt | None = None

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def setup_problems(self) -> tuple[Problem, ...]:
        return self._setup_problems

    @property
    def observed_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._observed_state

    @property
    def prepared_state(self) -> tuple[InstrumentStateSnapshot, ...]:
        return self._prepared_state

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        values: list[RunHardwareValue] = []
        problems: list[Problem] = []
        indeterminate = False
        for action in batch.actions:
            driver = self._drivers[action.instrument_id]
            if isinstance(action, RunHardwareApply):
                current = self._assumed_states[action.instrument_id]
                assignments = [
                    assignment
                    for assignment in action.assignments
                    if _state_value(current, assignment) != assignment.value
                ]
                if not assignments:
                    continue
                command = InstrumentStateCommand(
                    command_id=action.effect_id,
                    instrument_id=action.instrument_id,
                    assignments=assignments,
                )
                receipt = driver.apply_state(command)
                problems.extend(receipt.problems)
                if receipt.status != "applied":
                    indeterminate = receipt.status == "unknown"
                    break
                self._assumed_states[action.instrument_id] = (
                    receipt.state
                    or apply_state_command_to_snapshot(
                        current,
                        command,
                        description=self._descriptions[action.instrument_id],
                    )
                )
                continue
            if isinstance(action, RunHardwareInvoke):
                receipt = driver.invoke(
                    InvokeCommand(
                        command_id=action.effect_id,
                        instrument_id=action.instrument_id,
                        resource_id=action.resource_id,
                        interface_id=action.interface_id,
                        component_path=list(action.component_path),
                        operation_id=action.operation_id,
                        arguments=list(action.arguments),
                        payloads=action.payloads,
                        entity_ids=list(action.entity_ids),
                        channel_bindings=list(action.channel_bindings),
                    )
                )
                problems.extend(receipt.problems)
                if receipt.status != "invoked":
                    indeterminate = receipt.status == "unknown"
                    break
                self._assumed_states[action.instrument_id] = (
                    receipt.state or driver.read_state()
                )
                continue
            assert isinstance(action, RunHardwareCollect)
            receipt = driver.collect(
                CollectCommand(
                    command_id=action.effect_id,
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
                binding.request_id: binding.product_use_ids
                for binding in action.bindings
            }
            if set(receipt.readback.values) != set(bindings):
                problems.append(
                    runtime_problem(
                        "instrument_unexpected_product",
                        "instrument readback does not match requested results",
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
                for request_id, value in receipt.readback.values.items()
                for product_use_id in bindings[request_id]
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
        try:
            if failed:
                for driver in reversed(tuple(self._drivers.values())):
                    driver.abort()
            final_state = tuple(
                driver.read_state() for driver in self._drivers.values()
            )
        finally:
            for driver in reversed(tuple(self._drivers.values())):
                driver.disconnect()
        self._finished = RunHardwareFinalizationReceipt(
            operation_id=operation_id,
            final_state=final_state,
        )
        return self._finished


def _state_value(
    current: InstrumentStateSnapshot,
    target: InstrumentStateAssignment,
) -> object:
    identity = property_target_identity(
        target.interface_id,
        target.component_path,
        target.property_id,
        target.entity_ids,
        target.channel_bindings,
    )
    return next(
        (
            property.value
            for property in current.properties
            if property_target_identity(
                property.interface_id,
                property.component_path,
                property.property_id,
                property.entity_ids,
                property.channel_bindings,
            )
            == identity
        ),
        None,
    )


def provision_test_instrument_host(
    provider: InstrumentProvider | None,
    *,
    context: InstrumentProviderContext,
    instrument_ids: Sequence[str],
) -> TestRunInstrumentHost:
    """Provision fixture drivers outside the production Notebook executor."""

    if not instrument_ids:
        return TestRunInstrumentHost()
    if provider is None:
        raise ValueError("instrument claims require a test instrument provider")
    drivers: list[InstrumentDriver] = []
    try:
        for instrument_id in instrument_ids:
            drivers.append(
                provider.connect(
                    InstrumentConnectionContext(
                        config=context.config,
                        instrument_id=instrument_id,
                    )
                )
            )
    except Exception:
        for driver in reversed(drivers):
            driver.disconnect()
        raise
    return TestRunInstrumentHost(drivers)


__all__ = ["TestRunInstrumentHost", "provision_test_instrument_host"]
