"""Test-only in-process adapter for the daemon instrument-host port."""

from __future__ import annotations

from collections.abc import Iterable

from scopecat.execution.ports.instruments import (
    InstrumentLifecycleAction,
)
from scopecat.kernel.problems import Problem
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateCommand,
)


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

    def read_state(
        self,
        instrument_id: str,
        *,
        operation_id: str,
    ) -> InstrumentStateSnapshot:
        del operation_id
        return self._drivers[instrument_id].read_state()

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        return self._drivers[command.instrument_id].apply_state(command)

    def collect(self, command: CollectCommand) -> CollectReceipt:
        return self._drivers[command.instrument_id].collect(command)

    def lifecycle(
        self,
        instrument_id: str,
        *,
        operation_id: str,
        action: InstrumentLifecycleAction,
    ) -> None:
        del operation_id
        driver = self._drivers[instrument_id]
        if action == "cleanup":
            driver.cleanup()
        elif action == "abort":
            driver.abort()
        else:
            driver.close()


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
