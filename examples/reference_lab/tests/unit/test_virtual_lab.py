from __future__ import annotations

import scopecat as sc
from scopecat.records.config import InstrumentBindingSpec, VirtualInstrumentConnection
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments import (
    DriverStateEntry,
    DriverStatePatch,
    DriverSuccess,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InterfaceRef,
)
from scopecat_instruments.members import DC_BIAS_TARGET_VOLTAGE
from scopecat_instruments.virtual import VirtualLabWorld

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    AWG_SEQUENCER,
    DIGITIZER_CONTROL,
    DIGITIZER_INPUT,
)
from reference_lab.interfaces import CLOCK_REFERENCE
from reference_lab.provider import (
    MultiChannelVirtualDcSource,
    ReferenceLabProvider,
)


def test_virtual_provider_catalog_and_connection_use_exact_bindings() -> None:
    provider = ReferenceLabProvider()
    binding = InstrumentBindingSpec(
        id="drive-awg",
        driver_id="reference_lab.virtual.awg",
        connection=VirtualInstrumentConnection(),
    )

    described = provider.describe(InstrumentProviderContext(bindings=(binding,)))
    connected = provider.connect(InstrumentConnectionContext(binding=binding))

    assert [item.instrument_id for item in described.instruments] == ["drive-awg"]
    assert connected.instrument_id == "drive-awg"
    assert connected.implementation_id == binding.driver_id
    connected.disconnect()


def test_bare_control_devices_expose_physical_channel_interfaces() -> None:
    provider = ReferenceLabProvider()
    bindings = tuple(
        InstrumentBindingSpec(
            id=instrument_id,
            driver_id=driver_id,
            connection=VirtualInstrumentConnection(),
        )
        for instrument_id, driver_id in (
            ("drive-awg", "reference_lab.virtual.awg"),
            ("readout-digitizer", "reference_lab.virtual.digitizer"),
        )
    )

    described = provider.describe(InstrumentProviderContext(bindings=bindings))
    awg, digitizer = described.instruments

    assert {item.id for item in awg.interfaces} == {
        AWG_SEQUENCER.interface_id,
        ANALOG_WAVEFORM_OUTPUT.interface_id,
        CLOCK_REFERENCE.interface_id,
    }
    assert len(awg.interface_mounts) == 8
    assert {item.id for item in digitizer.interfaces} == {
        DIGITIZER_CONTROL.interface_id,
        DIGITIZER_INPUT.interface_id,
    }
    assert len(digitizer.interface_mounts) == 2


def test_multichannel_driver_dispatches_by_component_with_shared_provenance() -> None:
    world = VirtualLabWorld(seed=7)
    driver = MultiChannelVirtualDcSource("flux-dac", world)
    target = (
        InterfaceRef(DC_BIAS_TARGET_VOLTAGE.interface_id)
        .component("channels")
        .component("ch1")
        .property(DC_BIAS_TARGET_VOLTAGE.property_id)
    )
    bindings = (
        CommandChannelBinding(
            entity_id="q0",
            channel_id="flux.ch1.primary",
            interface_id=target.interface_id,
        ),
        CommandChannelBinding(
            entity_id="coupler0",
            channel_id="flux.ch1.secondary",
            interface_id=target.interface_id,
        ),
    )

    outcome = driver.apply_state(
        DriverStatePatch(
            scoped_values=(
                DriverStateEntry(
                    target=target,
                    value=sc.Quantity(0.125, "V"),
                    entity_ids=("q0", "coupler0"),
                    channel_bindings=bindings,
                ),
            )
        )
    )

    assert isinstance(outcome, DriverSuccess)
    assert world.dc_source("flux-dac:flux.ch1.primary").voltage_level_v == 0.125
    state_entry = next(
        entry for entry in driver.read_state().entries if entry.target == target
    )
    assert state_entry.entity_ids == ("q0", "coupler0")
    assert {binding.channel_id for binding in state_entry.channel_bindings} == {
        "flux.ch1.primary",
        "flux.ch1.secondary",
    }
