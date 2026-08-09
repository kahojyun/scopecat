from __future__ import annotations

import pytest
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

from reference_lab.bench_devices import BenchSignalWorld
from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    AWG_SEQUENCER,
    DIGITIZER_CONTROL,
    DIGITIZER_INPUT,
)
from reference_lab.interfaces import CLOCK_REFERENCE
from reference_lab.payloads import DecodedTriggerEpoch
from reference_lab.provider import (
    MultiChannelVirtualDcSource,
    ReferenceLabProvider,
)
from reference_lab.targets.list_mode.iq_semantics import integrate_rectangular_iq


@pytest.mark.parametrize(
    ("trace", "start_sample", "sample_count", "sample_rate_hz", "if_hz", "expected"),
    (
        pytest.param(
            (10.0, 2.0, 4.0, 20.0), 1, 2, 8.0, 0.0, 3.0 + 0.0j, id="zero-if-average"
        ),
        pytest.param(
            (0.5,),
            0,
            1,
            4.0,
            1.0,
            0.7071067811865476 - 0.7071067811865475j,
            id="positive-if-negative-phase",
        ),
        pytest.param(
            (0.5,),
            0,
            1,
            4.0,
            -1.0,
            0.7071067811865476 + 0.7071067811865475j,
            id="negative-if-positive-phase",
        ),
        pytest.param(
            (99.0, 1.0, 1.0, 99.0),
            1,
            2,
            4.0,
            1.0,
            -1.4142135623730951 + 0.0j,
            id="offset-window-sample-centers",
        ),
    ),
)
def test_integrated_iq_semantics_match_literal_golden_vectors(
    trace: tuple[float, ...],
    start_sample: int,
    sample_count: int,
    sample_rate_hz: float,
    if_hz: float,
    expected: complex,
) -> None:
    """Fix convention values independently of either DSP implementation path."""

    actual = integrate_rectangular_iq(
        trace,
        start_sample=start_sample,
        sample_count=sample_count,
        sample_rate_hz=sample_rate_hz,
        demodulation_frequency_hz=if_hz,
    )

    assert actual == pytest.approx(expected, abs=1e-15)


def test_virtual_trigger_epochs_are_checked_and_idempotent() -> None:
    world = BenchSignalWorld()
    epoch = DecodedTriggerEpoch(
        epoch_id="run-1:shot-0:entry-0",
        awg_instrument_ids=("awg",),
        digitizer_instrument_ids=("digitizer",),
    )
    world.arm_awg("awg", ())
    world.arm_digitizer("digitizer", record_length=8)

    assert world.fire_epoch(epoch) == (1, 1, False)
    assert world.trigger_count == 1
    assert world.fire_epoch(epoch) == (1, 1, True)
    assert world.trigger_count == 1

    with pytest.raises(ValueError, match="different participants"):
        world.fire_epoch(
            DecodedTriggerEpoch(
                epoch_id=epoch.epoch_id,
                awg_instrument_ids=("other-awg",),
                digitizer_instrument_ids=("digitizer",),
            )
        )

    fire_only = BenchSignalWorld()
    fire_only.arm_awg("awg", ())
    fire_only.arm_digitizer("digitizer", record_length=8)
    assert fire_only.fire_once(epoch) == (1, 1, False)
    fire_only.arm_awg("awg", ())
    fire_only.arm_digitizer("digitizer", record_length=8)
    assert fire_only.fire_once(epoch) == (1, 1, False)
    assert fire_only.trigger_count == 2


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
