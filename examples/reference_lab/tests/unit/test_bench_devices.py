from __future__ import annotations

import pytest
from scopecat.records.config import InstrumentBindingSpec, VirtualInstrumentConnection
from scopecat.sdk.instruments import InstrumentProviderContext

from reference_lab.bench_devices import BenchSignalWorld
from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    AWG_SEQUENCER,
    DIGITIZER_CONTROL,
    DIGITIZER_INPUT,
)
from reference_lab.interfaces import CLOCK_REFERENCE
from reference_lab.payloads import DecodedTriggerEpoch
from reference_lab.provider import ReferenceLabProvider


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
