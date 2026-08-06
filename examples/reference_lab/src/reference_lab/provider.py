"""One provider for every virtual instrument in the reference laboratory."""

from __future__ import annotations

from pathlib import Path

from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverCatalog,
    DriverConnectionSpec,
    DriverOperation,
    DriverOutcome,
    DriverReadback,
    DriverSpec,
    DriverState,
    DriverStateEntry,
    DriverStatePatch,
    DriverSuccess,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)
from scopecat_instruments import ConfiguredInstrumentProvider
from scopecat_instruments.interfaces import dc_monitor_interface, dc_source_interface
from scopecat_instruments.members import DC_SOURCE_OUTPUT_ENABLED
from scopecat_instruments.virtual import VirtualDcSource, VirtualLabWorld

from reference_lab.virtual_lab.provider import QuantumLabVirtualProvider
from reference_lab.workflows.event_capture import (
    EVENT_CAPTURE_DRIVER_ID,
    EVENT_CAPTURE_DRIVER_SPEC,
    VirtualEventDigitizer,
)

FLUX_SOURCE_IDS = ("flux-dac-a", "flux-dac-b")
FLUX_SOURCE_ID = FLUX_SOURCE_IDS[0]
MULTICHANNEL_DC_DRIVER_ID = "reference_lab.virtual.multichannel_dc_source"
MULTICHANNEL_DC_DRIVER_SPEC = DriverSpec(
    driver_id=MULTICHANNEL_DC_DRIVER_ID,
    implementation_version="v1",
    label="Virtual two-channel DC source",
    connections=(
        DriverConnectionSpec(
            kind="virtual",
            options_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ),
)


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
                MULTICHANNEL_DC_DRIVER_SPEC,
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
            and binding.driver_id != MULTICHANNEL_DC_DRIVER_ID
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
                    MultiChannelVirtualDcSource(
                        binding.id,
                        self.world,
                    ).describe()
                    for binding in context.bindings
                    if binding.driver_id == MULTICHANNEL_DC_DRIVER_ID
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
            return self._instruments.connect(context)
        if context.binding.driver_id == MULTICHANNEL_DC_DRIVER_ID:
            return MultiChannelVirtualDcSource(
                context.binding.id,
                self.world,
            )
        if context.binding.driver_id == EVENT_CAPTURE_DRIVER_ID:
            return VirtualEventDigitizer(context.binding.id)
        return self._quantum.connect(context)


class MultiChannelVirtualDcSource:
    """One physical DC source with independently routed virtual channels."""

    implementation_id = MULTICHANNEL_DC_DRIVER_ID
    implementation_version = "v1"

    def __init__(
        self,
        instrument_id: str,
        world: VirtualLabWorld,
    ) -> None:
        self.instrument_id = instrument_id
        self._world = world
        self._unrouted = VirtualDcSource(f"{instrument_id}:unrouted", world)
        self._drivers: dict[str, VirtualDcSource] = {}
        self._bindings: dict[str, CommandChannelBinding] = {}

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            label="Virtual multi-channel DC source",
            description=(
                "Independently routed DC source/monitor channels in one physical "
                "instrument."
            ),
            interfaces=[dc_source_interface(), dc_monitor_interface()],
        )

    def read_state(self) -> DriverState:
        if not self._drivers:
            return self._unrouted.read_state()
        entries: list[DriverStateEntry] = []
        for channel_id, binding in self._bindings.items():
            for entry in self._drivers[channel_id].read_state().entries:
                entries.append(
                    DriverStateEntry(
                        target=entry.target,
                        value=entry.value,
                        entity_ids=(binding.entity_id,),
                        channel_bindings=(
                            binding.model_copy(
                                update={"interface_id": entry.target.interface_id}
                            ),
                        ),
                    )
                )
        return DriverState(
            scoped_values=tuple(entries),
            metadata={"mode": "virtual", "channel_count": len(self._drivers)},
        )

    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        grouped: dict[str, list[DriverStateEntry]] = {}
        for entry in request.scoped_values:
            channel_id = self._channel_id(
                entry.target.interface_id,
                entry.channel_bindings,
            )
            grouped.setdefault(channel_id, []).append(
                DriverStateEntry(target=entry.target, value=entry.value)
            )
        for channel_id, entries in grouped.items():
            outcome = self._drivers[channel_id].apply_state(
                DriverStatePatch(
                    values={entry.target: entry.value for entry in entries}
                )
            )
            if not isinstance(outcome, DriverSuccess):
                return outcome
        return DriverSuccess(self.read_state())

    def invoke(
        self,
        request: DriverOperation,
    ) -> DriverOutcome[DriverState | None]:
        channel_id = self._channel_id(
            request.target.interface_id,
            request.channel_bindings,
        )
        outcome = self._drivers[channel_id].invoke(
            DriverOperation(target=request.target, arguments=request.arguments)
        )
        if isinstance(outcome, DriverSuccess):
            return DriverSuccess(self.read_state(), metadata=outcome.metadata)
        return outcome

    def collect(self, request: DriverAcquisition) -> DriverOutcome[DriverReadback]:
        channel_id = self._channel_id(
            request.target.interface_id,
            request.channel_bindings,
        )
        return self._drivers[channel_id].collect(
            DriverAcquisition(target=request.target, results=request.results)
        )

    def disconnect(self) -> None:
        for driver in self._drivers.values():
            driver.disconnect()

    def abort(self) -> None:
        for driver in self._drivers.values():
            outcome = driver.apply_state(
                DriverStatePatch(values={DC_SOURCE_OUTPUT_ENABLED: False})
            )
            if not isinstance(outcome, DriverSuccess):
                raise RuntimeError(
                    f"{self.instrument_id} did not confirm channel bias-off"
                )
            driver.abort()

    def _channel_id(
        self,
        interface_id: str,
        bindings: tuple[CommandChannelBinding, ...],
    ) -> str:
        matches = tuple(
            binding.channel_id
            for binding in bindings
            if binding.interface_id in {None, interface_id}
        )
        if len(matches) == 1:
            binding = next(
                binding
                for binding in bindings
                if binding.channel_id == matches[0]
                and binding.interface_id in {None, interface_id}
            )
            self._bindings.setdefault(binding.channel_id, binding)
            if binding.channel_id not in self._drivers:
                self._drivers[binding.channel_id] = VirtualDcSource(
                    f"{self.instrument_id}:{binding.channel_id}",
                    self._world,
                )
            return binding.channel_id
        raise ValueError(f"{self.instrument_id} requires exactly one routed DC channel")


__all__ = ["FLUX_SOURCE_ID", "FLUX_SOURCE_IDS", "ReferenceLabProvider"]
