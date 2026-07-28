"""Demo provider composition with an interface-level bias safety policy."""

from __future__ import annotations

from dataclasses import replace

from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectReceipt,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverInvokeRequest,
    DriverPropertyWrite,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentStateSnapshot,
    InvokeReceipt,
    StateValue,
)
from scopecat_instruments import ConfiguredInstrumentProvider
from scopecat_instruments.members import DC_SOURCE_OUTPUT_ENABLED
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

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        driver = self._configured.connect(context)
        return (
            _BiasSafeDriver(driver)
            if driver.instrument_id == FLUX_SOURCE_ID
            else driver
        )


class _BiasSafeDriver:
    """Forward one driver while enforcing interface-based output shutdown."""

    def __init__(self, driver: InstrumentDriver) -> None:
        self._driver = driver
        self.implementation_id = driver.implementation_id
        self.implementation_version = driver.implementation_version

    @property
    def instrument_id(self) -> str:
        return self._driver.instrument_id

    def describe(self) -> InstrumentDescription:
        return self._driver.describe()

    def read_state(self) -> InstrumentStateSnapshot:
        return self._driver.read_state()

    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        return self._driver.apply_state(request)

    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        return self._driver.invoke(request)

    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        return self._driver.collect(request)

    def abort(self) -> None:
        try:
            self._disable_bias("abort")
        finally:
            self._driver.abort()

    def disconnect(self) -> None:
        self._driver.disconnect()

    def _disable_bias(self, phase: str) -> None:
        receipt = self._driver.apply_state(
            DriverApplyRequest(
                assignments=(
                    DriverPropertyWrite(
                        interface_id=DC_SOURCE_OUTPUT_ENABLED.interface_id,
                        component_path=DC_SOURCE_OUTPUT_ENABLED.component_path,
                        property_id=DC_SOURCE_OUTPUT_ENABLED.property_id,
                        value=StateValue(False),
                    ),
                ),
            )
        )
        if receipt.status != "applied":
            raise RuntimeError(
                f"{self.instrument_id} did not confirm bias-off during {phase}"
            )


__all__ = ["FLUX_SOURCE_ID", "InstrumentDemoProvider"]
