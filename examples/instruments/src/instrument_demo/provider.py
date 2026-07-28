"""Demo provider composition with an interface-level bias safety policy."""

from __future__ import annotations

from dataclasses import replace

from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
    InvokeCommand,
    InvokeReceipt,
    StateValue,
)
from scopecat_instruments import ConfiguredInstrumentProvider
from scopecat_instruments.interfaces import DC_SOURCE
from scopecat_instruments.virtual import VirtualLabWorld

FLUX_SOURCE_ID = "flux-source"


class InstrumentDemoProvider:
    """Use the stock configured drivers and guarantee bias-off on abort."""

    provider_id = "instrument_demo.configured"

    def __init__(self, *, seed: int = 7) -> None:
        self._configured = ConfiguredInstrumentProvider(seed=seed)

    @property
    def world(self) -> VirtualLabWorld:
        """Expose the deterministic world for example-level verification."""

        return self._configured.world

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return replace(
            self._configured.describe(context),
            provider_id=self.provider_id,
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        result = self._configured.provide(context)
        return replace(
            result,
            drivers=tuple(
                _BiasSafeDriver(driver)
                if driver.instrument_id == FLUX_SOURCE_ID
                else driver
                for driver in result.drivers
            ),
            metadata={**result.metadata, "provider_id": self.provider_id},
        )


class _BiasSafeDriver:
    """Forward one driver while enforcing interface-based output shutdown."""

    def __init__(self, driver: InstrumentDriver) -> None:
        self._driver = driver

    @property
    def instrument_id(self) -> str:
        return self._driver.instrument_id

    @property
    def implementation_id(self) -> str:
        return self._driver.implementation_id

    @property
    def implementation_version(self) -> str:
        return self._driver.implementation_version

    def describe(self) -> InstrumentDescription:
        return self._driver.describe()

    def read_state(self) -> InstrumentStateSnapshot:
        return self._driver.read_state()

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        return self._driver.apply_state(command)

    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        return self._driver.invoke(command)

    def collect(self, command: CollectCommand) -> CollectReceipt:
        return self._driver.collect(command)

    def abort(self) -> None:
        try:
            self._disable_bias("abort")
        finally:
            self._driver.abort()

    def disconnect(self) -> None:
        self._driver.disconnect()

    def _disable_bias(self, phase: str) -> None:
        receipt = self._driver.apply_state(
            InstrumentStateCommand(
                command_id=f"instrument-demo.{phase}.bias-off",
                instrument_id=self.instrument_id,
                assignments=[
                    InstrumentStateAssignment(
                        resource_id=self.instrument_id,
                        interface_id=DC_SOURCE,
                        property_id="output_enabled",
                        value=StateValue(False),
                    )
                ],
            )
        )
        if receipt.status != "applied":
            raise RuntimeError(
                f"{self.instrument_id} did not confirm bias-off during {phase}"
            )


__all__ = ["FLUX_SOURCE_ID", "InstrumentDemoProvider"]
