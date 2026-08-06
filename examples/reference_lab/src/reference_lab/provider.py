"""One provider for every virtual instrument in the reference laboratory."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverCatalog,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from scopecat_instruments import ConfiguredInstrumentProvider
from scopecat_instruments.members import DC_SOURCE_OUTPUT_ENABLED
from scopecat_instruments.virtual import VirtualLabWorld

from reference_lab.virtual_lab.provider import QuantumLabVirtualProvider
from reference_lab.workflows.event_capture import (
    EVENT_CAPTURE_DRIVER_ID,
    EVENT_CAPTURE_DRIVER_SPEC,
    VirtualEventDigitizer,
)

FLUX_SOURCE_ID = "flux-source"


class ReferenceLabProvider:
    """Combine stock coupled instruments and the lab's quantum stacks."""

    provider_id = "reference_lab.virtual_lab.provider"

    def __init__(self, *, profile: str | Path, seed: int = 7) -> None:
        self._instruments = ConfiguredInstrumentProvider(seed=seed)
        self._quantum = QuantumLabVirtualProvider(profile=profile)
        self.driver_catalog = DriverCatalog(
            provider_id=self.provider_id,
            drivers=(
                *self._instruments.driver_catalog.drivers,
                *self._quantum.driver_catalog.drivers,
                EVENT_CAPTURE_DRIVER_SPEC,
            ),
        )

    @property
    def world(self) -> VirtualLabWorld:
        """Expose the coupled instrument world for gallery verification."""

        return self._instruments.world

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        instrument_driver_ids = {
            spec.driver_id for spec in self._instruments.driver_catalog.drivers
        }
        instrument_bindings = tuple(
            binding
            for binding in context.bindings
            if binding.driver_id in instrument_driver_ids
        )
        quantum_bindings = tuple(
            binding
            for binding in context.bindings
            if binding.driver_id not in instrument_driver_ids
            and binding.driver_id != EVENT_CAPTURE_DRIVER_ID
        )
        descriptions = (
            self._instruments.describe(InstrumentProviderContext(instrument_bindings)),
            self._quantum.describe(InstrumentProviderContext(quantum_bindings)),
        )
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(
                *tuple(
                    instrument
                    for description in descriptions
                    for instrument in description.instruments
                ),
                *tuple(
                    VirtualEventDigitizer(binding.id).describe()
                    for binding in context.bindings
                    if binding.driver_id == EVENT_CAPTURE_DRIVER_ID
                ),
            ),
            problems=tuple(
                problem
                for description in descriptions
                for problem in description.problems
            ),
        )

    def connect(self, context: InstrumentConnectionContext) -> InstrumentDriver:
        instrument_driver_ids = {
            spec.driver_id for spec in self._instruments.driver_catalog.drivers
        }
        if context.binding.driver_id in instrument_driver_ids:
            driver = self._instruments.connect(context)
            return (
                _BiasSafeDriver(driver)
                if driver.instrument_id == FLUX_SOURCE_ID
                else driver
            )
        if context.binding.driver_id == EVENT_CAPTURE_DRIVER_ID:
            return VirtualEventDigitizer(context.binding.id)
        return self._quantum.connect(context)


class _BiasSafeDriver:
    """Forward the flux source while guaranteeing bias-off during abort."""

    def __init__(self, driver: InstrumentDriver) -> None:
        self._driver = driver
        self.implementation_id = driver.implementation_id
        self.implementation_version = driver.implementation_version

    @property
    def instrument_id(self) -> str:
        return self._driver.instrument_id

    def describe(self) -> InstrumentDescription:
        return self._driver.describe()

    def read_state(self) -> DriverState:
        return self._driver.read_state()

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        return self._driver.apply_state(request)

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        return self._driver.invoke(request)

    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        return self._driver.collect(request)

    def abort(self) -> None:
        try:
            receipt = self._driver.apply_state(
                DriverStatePatch(values={DC_SOURCE_OUTPUT_ENABLED: False})
            )
            if not isinstance(receipt, DriverSuccess):
                raise RuntimeError(
                    f"{self.instrument_id} did not confirm bias-off during abort"
                )
        finally:
            self._driver.abort()

    def disconnect(self) -> None:
        self._driver.disconnect()


__all__ = ["FLUX_SOURCE_ID", "ReferenceLabProvider"]
