from __future__ import annotations

import numpy as np
import pytest
from scopecat.records.config import InstrumentBindingSpec, VirtualInstrumentConnection
from scopecat.sdk.instruments import (
    DriverOperation,
    DriverPayload,
    DriverState,
    DriverSuccess,
    InstrumentProviderContext,
)

from reference_lab.bench_devices import (
    ArmedAwgWaveform,
    BenchSignalWorld,
    VirtualTimingController,
)
from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    AWG_SEQUENCER,
    DIGITIZER_CONTROL,
    DIGITIZER_INPUT,
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
)
from reference_lab.interfaces import CLOCK_REFERENCE
from reference_lab.payloads import (
    DecodedDigitizerProgram,
    DecodedDigitizerProgramEntry,
    DecodedTriggerProgram,
    DecodedTriggerProgramEntry,
)
from reference_lab.provider import ReferenceLabProvider


def test_virtual_trigger_programs_execute_complete_device_programs() -> None:
    world = BenchSignalWorld()
    awg_entries = (
        (
            ArmedAwgWaveform(
                component_path=("outputs", "ch1"),
                normalized_samples=(0.0, 1.0),
                sample_rate_hz=1.0e9,
                amplitude_v=0.25,
                offset_v=0.0,
                output_enabled=True,
                repeat=False,
            ),
        ),
    )
    digitizer = DecodedDigitizerProgram(
        entries=(
            DecodedDigitizerProgramEntry(
                sample_count=2,
                input_component_paths=(("inputs", "ch1"),),
                windows=(),
            ),
        )
    )
    program = DecodedTriggerProgram(
        program_id="run-1",
        repetitions=2,
        entries=(
            DecodedTriggerProgramEntry(
                awg_instrument_ids=("awg",),
                digitizer_instrument_ids=("digitizer",),
            ),
        ),
    )
    world.arm_awg_program("awg", awg_entries)
    world.arm_digitizer_program("digitizer", digitizer)

    assert world.run_program(program) == (1, 1)
    assert world.trigger_count == 2
    segments = world.digitizer_program_segments(
        "digitizer",
        ("inputs", "ch1"),
    )
    assert tuple(entry_index for entry_index, _trace in segments) == (0, 0)
    for _entry_index, trace in segments:
        np.testing.assert_array_equal(trace, np.zeros(2, dtype=np.float64))

    world.arm_awg_program("awg", awg_entries)
    world.arm_digitizer_program("digitizer", digitizer)
    assert world.run_program(program) == (1, 1)
    assert world.trigger_count == 4


def test_virtual_trigger_idempotency_is_scoped_to_driver_session() -> None:
    world = BenchSignalWorld()
    program = DecodedTriggerProgram(
        program_id="run-1",
        repetitions=1,
        entries=(DecodedTriggerProgramEntry((), ()),),
    )

    def load_and_start(
        controller: VirtualTimingController,
        loaded: DecodedTriggerProgram,
    ) -> DriverSuccess[DriverState | None]:
        controller.invoke(
            DriverOperation(
                target=TRIGGER_LOAD_PROGRAM,
                arguments={
                    TRIGGER_PROGRAM.argument_id: DriverPayload(
                        schema_id="reference_lab.trigger_program.v1",
                        value=loaded,
                    )
                },
            )
        )
        outcome = controller.invoke(
            DriverOperation(target=TRIGGER_START_PROGRAM_IDEMPOTENT)
        )
        assert isinstance(outcome, DriverSuccess)
        return outcome

    first_session = VirtualTimingController("timing", world)
    assert load_and_start(first_session, program).metadata["replayed"] is False
    assert load_and_start(first_session, program).metadata["replayed"] is True
    assert world.trigger_count == 1

    second_session = VirtualTimingController("timing", world)
    assert load_and_start(second_session, program).metadata["replayed"] is False
    assert world.trigger_count == 2

    changed = DecodedTriggerProgram(
        program_id=program.program_id,
        repetitions=2,
        entries=program.entries,
    )
    with pytest.raises(ValueError, match="different contents"):
        load_and_start(first_session, changed)


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
