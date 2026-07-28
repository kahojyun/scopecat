"""Demo provider composition with a capability-level bias safety policy."""

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
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    StateValue,
)
from scopecat_instruments import ConfiguredInstrumentProvider
from scopecat_instruments.virtual import VirtualLabWorld

FLUX_SOURCE_ID = "flux-source"
DC_OUTPUT_CAPABILITY = "dc_output"


class InstrumentDemoProvider:
    """Use the stock configured drivers and guarantee bias-off finalization."""

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
    """Forward one driver while enforcing capability-based output shutdown."""

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

    def collect(self, command: CollectCommand) -> CollectReceipt:
        return self._driver.collect(command)

    def cleanup(self) -> None:
        try:
            self._disable_bias("cleanup")
        finally:
            self._driver.cleanup()

    def abort(self) -> None:
        try:
            self._disable_bias("abort")
        finally:
            self._driver.abort()

    def close(self) -> None:
        self._driver.close()

    def _disable_bias(self, phase: str) -> None:
        receipt = self._driver.apply_state(
            InstrumentStateCommand(
                operation_id=f"instrument-demo.{phase}.bias-off",
                instrument_id=self.instrument_id,
                fields=[
                    InstrumentStateCommandField(
                        resource_id=self.instrument_id,
                        capability_id=DC_OUTPUT_CAPABILITY,
                        field_path="output_enabled",
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
