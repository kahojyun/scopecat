"""Vendor-neutral bench AWG and oscilloscope capability identities."""

from __future__ import annotations

from scopecat.kernel.value_types import Int, Payload, Scalar
from scopecat.sdk.instruments import (
    InterfaceRef,
    InterfaceSpec,
    acquisition,
    acquisition_axis,
    acquisition_result,
    bool_property,
    enum_property,
    int_property,
    interface,
    operation,
    operation_argument,
    quantity_property,
)

from reference_lab.payloads import (
    AWG_ENTRY_SCHEMA_ID,
    AWG_PROGRAM_SCHEMA_ID,
    DIGITIZER_DSP_PROGRAM_SCHEMA_ID,
    SAMPLED_WAVEFORM_SCHEMA_ID,
    TRIGGER_EPOCH_SCHEMA_ID,
)

AWG_SEQUENCER = InterfaceRef("reference_lab.awg_sequencer/v1")
AWG_SAMPLE_RATE = AWG_SEQUENCER.property("sample_rate")
AWG_RUN_MODE = AWG_SEQUENCER.property("run_mode")
AWG_PLAY_ENTRY = AWG_SEQUENCER.operation("play_entry")
AWG_ENTRY = AWG_PLAY_ENTRY.argument("entry")
AWG_LOAD_PROGRAM = AWG_SEQUENCER.operation("load_program")
AWG_PROGRAM = AWG_LOAD_PROGRAM.argument("program")
AWG_ARM_ENTRY = AWG_SEQUENCER.operation("arm_entry")
AWG_ENTRY_INDEX = AWG_ARM_ENTRY.argument("entry_index")
AWG_START = AWG_SEQUENCER.operation("start")

ANALOG_WAVEFORM_OUTPUT = InterfaceRef("reference_lab.analog_waveform_output/v1")
ANALOG_WAVEFORM_OUTPUT_AMPLITUDE = ANALOG_WAVEFORM_OUTPUT.property("amplitude")
ANALOG_WAVEFORM_OUTPUT_OFFSET = ANALOG_WAVEFORM_OUTPUT.property("offset")
ANALOG_WAVEFORM_OUTPUT_ENABLED = ANALOG_WAVEFORM_OUTPUT.property("output_enabled")
ANALOG_WAVEFORM_OUTPUT_PLAY = ANALOG_WAVEFORM_OUTPUT.operation("play")
ANALOG_WAVEFORM_OUTPUT_WAVEFORM = ANALOG_WAVEFORM_OUTPUT_PLAY.argument("waveform")
ANALOG_WAVEFORM_OUTPUT_RESET = ANALOG_WAVEFORM_OUTPUT.operation("reset")

OSCILLOSCOPE_CONTROL = InterfaceRef("reference_lab.oscilloscope_control/v1")
OSCILLOSCOPE_SAMPLE_RATE = OSCILLOSCOPE_CONTROL.property("sample_rate")
OSCILLOSCOPE_RECORD_LENGTH = OSCILLOSCOPE_CONTROL.property("record_length")
OSCILLOSCOPE_TRIGGER_SOURCE = OSCILLOSCOPE_CONTROL.property("trigger_source")
OSCILLOSCOPE_TRIGGER_LEVEL = OSCILLOSCOPE_CONTROL.property("trigger_level")
OSCILLOSCOPE_ARMED = OSCILLOSCOPE_CONTROL.property("armed")
OSCILLOSCOPE_ARM = OSCILLOSCOPE_CONTROL.operation("arm")

OSCILLOSCOPE_INPUT = InterfaceRef("reference_lab.oscilloscope_input/v1")
OSCILLOSCOPE_INPUT_ENABLED = OSCILLOSCOPE_INPUT.property("input_enabled")
OSCILLOSCOPE_VERTICAL_SCALE = OSCILLOSCOPE_INPUT.property("vertical_scale")
OSCILLOSCOPE_VERTICAL_OFFSET = OSCILLOSCOPE_INPUT.property("vertical_offset")
OSCILLOSCOPE_COUPLING = OSCILLOSCOPE_INPUT.property("coupling")
OSCILLOSCOPE_IMPEDANCE = OSCILLOSCOPE_INPUT.property("impedance")
OSCILLOSCOPE_BANDWIDTH_LIMIT = OSCILLOSCOPE_INPUT.property("bandwidth_limit")
OSCILLOSCOPE_FETCH = OSCILLOSCOPE_INPUT.acquisition("fetch")
OSCILLOSCOPE_FETCH_TIME = OSCILLOSCOPE_FETCH.result("time")
OSCILLOSCOPE_FETCH_VOLTAGE = OSCILLOSCOPE_FETCH.result("voltage")

DIGITIZER_CONTROL = InterfaceRef("reference_lab.digitizer_control/v1")
DIGITIZER_SAMPLE_RATE = DIGITIZER_CONTROL.property("sample_rate")
DIGITIZER_RECORD_LENGTH = DIGITIZER_CONTROL.property("record_length")
DIGITIZER_TRIGGER_SOURCE = DIGITIZER_CONTROL.property("trigger_source")
DIGITIZER_CONFIGURE_DSP = DIGITIZER_CONTROL.operation("configure_dsp")
DIGITIZER_DSP_PROGRAM = DIGITIZER_CONFIGURE_DSP.argument("program")
DIGITIZER_ARM = DIGITIZER_CONTROL.operation("arm")

DIGITIZER_INPUT = InterfaceRef("reference_lab.digitizer_input/v1")
DIGITIZER_INPUT_ENABLED = DIGITIZER_INPUT.property("input_enabled")
DIGITIZER_INPUT_RANGE = DIGITIZER_INPUT.property("input_range")
DIGITIZER_INPUT_COUPLING = DIGITIZER_INPUT.property("coupling")
DIGITIZER_FETCH = DIGITIZER_INPUT.acquisition("fetch")
DIGITIZER_FETCH_TIME = DIGITIZER_FETCH.result("time")
DIGITIZER_FETCH_VOLTAGE = DIGITIZER_FETCH.result("voltage")
DIGITIZER_FETCH_IQ = DIGITIZER_INPUT.acquisition("fetch_integrated_iq")
DIGITIZER_FETCH_IQ_VALUE = DIGITIZER_FETCH_IQ.result("value")

TRIGGER_COORDINATOR = InterfaceRef("reference_lab.trigger_coordinator/v2")
TRIGGER_FIRE = TRIGGER_COORDINATOR.operation("fire")
TRIGGER_EPOCH = TRIGGER_FIRE.argument("epoch")
TRIGGER_FIRE_EPOCH = TRIGGER_COORDINATOR.operation("fire_epoch")
TRIGGER_IDEMPOTENT_EPOCH = TRIGGER_FIRE_EPOCH.argument("epoch")


def awg_sequencer_interface() -> InterfaceSpec:
    return interface(
        AWG_SEQUENCER.interface_id,
        label="AWG sequencer",
        description="Instrument-wide sampling and sequence execution configuration.",
        properties=(
            quantity_property(
                AWG_SAMPLE_RATE.property_id,
                unit="Hz",
                minimum=1.0,
                label="Sample rate",
            ),
            enum_property(
                AWG_RUN_MODE.property_id,
                choices=("once", "continuous"),
                label="Run mode",
            ),
        ),
        operations=(
            operation(
                AWG_LOAD_PROGRAM.operation_id,
                label="Load a synchronized multi-channel program",
                arguments=(
                    operation_argument(
                        AWG_PROGRAM.argument_id,
                        value_type=Scalar(Payload(AWG_PROGRAM_SCHEMA_ID)),
                        label="AWG program",
                    ),
                ),
            ),
            operation(
                AWG_ARM_ENTRY.operation_id,
                label="Arm one loaded entry",
                arguments=(
                    operation_argument(
                        AWG_ENTRY_INDEX.argument_id,
                        value_type=Scalar(Int(minimum=0)),
                        label="Entry index",
                    ),
                ),
            ),
            operation(AWG_START.operation_id, label="Start the armed entry"),
            operation(
                AWG_PLAY_ENTRY.operation_id,
                label="Play one synchronized multi-channel entry",
                arguments=(
                    operation_argument(
                        AWG_ENTRY.argument_id,
                        value_type=Scalar(Payload(AWG_ENTRY_SCHEMA_ID)),
                        label="AWG entry",
                    ),
                ),
            ),
        ),
    )


def analog_waveform_output_interface() -> InterfaceSpec:
    return interface(
        ANALOG_WAVEFORM_OUTPUT.interface_id,
        label="Analog waveform output",
        description="One real-valued DAC output driven by normalized samples.",
        properties=(
            quantity_property(
                ANALOG_WAVEFORM_OUTPUT_AMPLITUDE.property_id,
                unit="V",
                minimum=0.0,
                label="Peak amplitude",
            ),
            quantity_property(
                ANALOG_WAVEFORM_OUTPUT_OFFSET.property_id,
                unit="V",
                label="DC offset",
            ),
            bool_property(
                ANALOG_WAVEFORM_OUTPUT_ENABLED.property_id,
                label="Output enabled",
            ),
        ),
        operations=(
            operation(
                ANALOG_WAVEFORM_OUTPUT_PLAY.operation_id,
                label="Play waveform",
                arguments=(
                    operation_argument(
                        ANALOG_WAVEFORM_OUTPUT_WAVEFORM.argument_id,
                        value_type=Scalar(Payload(SAMPLED_WAVEFORM_SCHEMA_ID)),
                        label="Sampled waveform",
                    ),
                ),
            ),
            operation(
                ANALOG_WAVEFORM_OUTPUT_RESET.operation_id,
                label="Reset output settings",
                invalidates=(
                    ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
                    ANALOG_WAVEFORM_OUTPUT_OFFSET,
                    ANALOG_WAVEFORM_OUTPUT_ENABLED,
                ),
            ),
        ),
    )


def oscilloscope_control_interface() -> InterfaceSpec:
    return interface(
        OSCILLOSCOPE_CONTROL.interface_id,
        label="Oscilloscope acquisition control",
        description="Instrument-wide timebase, trigger, and acquisition arming.",
        properties=(
            quantity_property(
                OSCILLOSCOPE_SAMPLE_RATE.property_id,
                unit="Hz",
                minimum=1.0,
                label="Sample rate",
            ),
            int_property(
                OSCILLOSCOPE_RECORD_LENGTH.property_id,
                minimum=1,
                label="Record length",
            ),
            enum_property(
                OSCILLOSCOPE_TRIGGER_SOURCE.property_id,
                choices=("external",),
                label="Trigger source",
            ),
            quantity_property(
                OSCILLOSCOPE_TRIGGER_LEVEL.property_id,
                unit="V",
                label="Trigger level",
            ),
            bool_property(
                OSCILLOSCOPE_ARMED.property_id,
                access="read_only",
                label="Armed",
            ),
        ),
        operations=(operation(OSCILLOSCOPE_ARM.operation_id, label="Arm"),),
    )


def oscilloscope_input_interface() -> InterfaceSpec:
    sample_axis = acquisition_axis(
        "sample",
        size=None,
        kind="time",
        unit="s",
        description=(
            "Actual extent comes from the waveform preamble; requested record "
            "length remains instrument state."
        ),
    )
    return interface(
        OSCILLOSCOPE_INPUT.interface_id,
        label="Oscilloscope analog input",
        description="One physical analog input and its captured voltage trace.",
        properties=(
            bool_property(
                OSCILLOSCOPE_INPUT_ENABLED.property_id,
                label="Input enabled",
            ),
            quantity_property(
                OSCILLOSCOPE_VERTICAL_SCALE.property_id,
                unit="V",
                minimum=1e-6,
                label="Vertical scale",
                description="Volts per division.",
            ),
            quantity_property(
                OSCILLOSCOPE_VERTICAL_OFFSET.property_id,
                unit="V",
                label="Vertical offset",
            ),
            enum_property(
                OSCILLOSCOPE_COUPLING.property_id,
                choices=("dc", "ac"),
                label="Coupling",
            ),
            enum_property(
                OSCILLOSCOPE_IMPEDANCE.property_id,
                choices=("50_ohm", "1_megohm"),
                label="Input impedance",
            ),
            quantity_property(
                OSCILLOSCOPE_BANDWIDTH_LIMIT.property_id,
                unit="Hz",
                minimum=1.0,
                label="Bandwidth limit",
            ),
        ),
        acquisitions=(
            acquisition(
                OSCILLOSCOPE_FETCH.acquisition_id,
                label="Fetch captured waveform",
                results=(
                    acquisition_result(
                        OSCILLOSCOPE_FETCH_TIME.result_id,
                        role="coordinate",
                        unit="s",
                        axes=(sample_axis,),
                    ),
                    acquisition_result(
                        OSCILLOSCOPE_FETCH_VOLTAGE.result_id,
                        unit="V",
                        axes=(sample_axis,),
                    ),
                ),
            ),
        ),
    )


def digitizer_control_interface() -> InterfaceSpec:
    return interface(
        DIGITIZER_CONTROL.interface_id,
        label="Digitizer acquisition control",
        description="Instrument-wide sample clock, trigger, and record memory.",
        properties=(
            quantity_property(
                DIGITIZER_SAMPLE_RATE.property_id,
                unit="Hz",
                minimum=1.0,
                label="Sample rate",
            ),
            int_property(
                DIGITIZER_RECORD_LENGTH.property_id,
                minimum=1,
                label="Record length",
            ),
            enum_property(
                DIGITIZER_TRIGGER_SOURCE.property_id,
                choices=("external", "software"),
                label="Trigger source",
            ),
        ),
        operations=(
            operation(
                DIGITIZER_CONFIGURE_DSP.operation_id,
                label="Configure onboard demodulation and integration",
                arguments=(
                    operation_argument(
                        DIGITIZER_DSP_PROGRAM.argument_id,
                        value_type=Scalar(Payload(DIGITIZER_DSP_PROGRAM_SCHEMA_ID)),
                        label="DSP program",
                    ),
                ),
            ),
            operation(DIGITIZER_ARM.operation_id, label="Arm"),
        ),
    )


def digitizer_input_interface() -> InterfaceSpec:
    sample_axis = acquisition_axis(
        "sample",
        size=None,
        kind="time",
        unit="s",
    )
    demodulator_axis = acquisition_axis(
        "demodulator",
        size=None,
        kind="index",
    )
    return interface(
        DIGITIZER_INPUT.interface_id,
        label="Digitizer analog input",
        description=(
            "One physical ADC input. Target-owned demodulation slots are named "
            "by routing channel IDs rather than mounted as separate instruments."
        ),
        properties=(
            bool_property(
                DIGITIZER_INPUT_ENABLED.property_id,
                label="Input enabled",
            ),
            quantity_property(
                DIGITIZER_INPUT_RANGE.property_id,
                unit="V",
                minimum=1e-6,
                label="Input range",
            ),
            enum_property(
                DIGITIZER_INPUT_COUPLING.property_id,
                choices=("dc", "ac"),
                label="Coupling",
            ),
        ),
        acquisitions=(
            acquisition(
                DIGITIZER_FETCH.acquisition_id,
                label="Fetch raw capture",
                results=(
                    acquisition_result(
                        DIGITIZER_FETCH_TIME.result_id,
                        role="coordinate",
                        unit="s",
                        axes=(sample_axis,),
                    ),
                    acquisition_result(
                        DIGITIZER_FETCH_VOLTAGE.result_id,
                        unit="V",
                        axes=(sample_axis,),
                    ),
                ),
            ),
            acquisition(
                DIGITIZER_FETCH_IQ.acquisition_id,
                label="Fetch onboard integrated IQ",
                results=(
                    acquisition_result(
                        DIGITIZER_FETCH_IQ_VALUE.result_id,
                        dtype="complex128",
                        unit="V",
                        axes=(demodulator_axis,),
                    ),
                ),
            ),
        ),
    )


def trigger_coordinator_interface() -> InterfaceSpec:
    return interface(
        TRIGGER_COORDINATOR.interface_id,
        label="Trigger coordinator",
        description="Emit one shared edge after every participating device is armed.",
        operations=(
            operation(
                TRIGGER_FIRE.operation_id,
                label="Fire one non-idempotent trigger intent",
                arguments=(
                    operation_argument(
                        TRIGGER_EPOCH.argument_id,
                        value_type=Scalar(Payload(TRIGGER_EPOCH_SCHEMA_ID)),
                        label="Trigger epoch",
                    ),
                ),
            ),
            operation(
                TRIGGER_FIRE_EPOCH.operation_id,
                label="Fire one session-idempotent trigger epoch",
                arguments=(
                    operation_argument(
                        TRIGGER_IDEMPOTENT_EPOCH.argument_id,
                        value_type=Scalar(Payload(TRIGGER_EPOCH_SCHEMA_ID)),
                        label="Trigger epoch",
                    ),
                ),
            ),
        ),
    )


__all__ = [
    "ANALOG_WAVEFORM_OUTPUT",
    "ANALOG_WAVEFORM_OUTPUT_AMPLITUDE",
    "ANALOG_WAVEFORM_OUTPUT_ENABLED",
    "ANALOG_WAVEFORM_OUTPUT_OFFSET",
    "ANALOG_WAVEFORM_OUTPUT_PLAY",
    "ANALOG_WAVEFORM_OUTPUT_RESET",
    "ANALOG_WAVEFORM_OUTPUT_WAVEFORM",
    "AWG_ENTRY",
    "AWG_PLAY_ENTRY",
    "AWG_RUN_MODE",
    "AWG_SAMPLE_RATE",
    "AWG_SEQUENCER",
    "DIGITIZER_ARM",
    "DIGITIZER_CONFIGURE_DSP",
    "DIGITIZER_CONTROL",
    "DIGITIZER_DSP_PROGRAM",
    "DIGITIZER_FETCH",
    "DIGITIZER_FETCH_IQ",
    "DIGITIZER_FETCH_IQ_VALUE",
    "DIGITIZER_FETCH_TIME",
    "DIGITIZER_FETCH_VOLTAGE",
    "DIGITIZER_INPUT",
    "DIGITIZER_INPUT_COUPLING",
    "DIGITIZER_INPUT_ENABLED",
    "DIGITIZER_INPUT_RANGE",
    "DIGITIZER_RECORD_LENGTH",
    "DIGITIZER_SAMPLE_RATE",
    "DIGITIZER_TRIGGER_SOURCE",
    "OSCILLOSCOPE_ARM",
    "OSCILLOSCOPE_ARMED",
    "OSCILLOSCOPE_BANDWIDTH_LIMIT",
    "OSCILLOSCOPE_CONTROL",
    "OSCILLOSCOPE_COUPLING",
    "OSCILLOSCOPE_FETCH",
    "OSCILLOSCOPE_FETCH_TIME",
    "OSCILLOSCOPE_FETCH_VOLTAGE",
    "OSCILLOSCOPE_IMPEDANCE",
    "OSCILLOSCOPE_INPUT",
    "OSCILLOSCOPE_INPUT_ENABLED",
    "OSCILLOSCOPE_RECORD_LENGTH",
    "OSCILLOSCOPE_SAMPLE_RATE",
    "OSCILLOSCOPE_TRIGGER_LEVEL",
    "OSCILLOSCOPE_TRIGGER_SOURCE",
    "OSCILLOSCOPE_VERTICAL_OFFSET",
    "OSCILLOSCOPE_VERTICAL_SCALE",
    "TRIGGER_COORDINATOR",
    "TRIGGER_EPOCH",
    "TRIGGER_FIRE",
    "TRIGGER_FIRE_EPOCH",
    "TRIGGER_IDEMPOTENT_EPOCH",
    "analog_waveform_output_interface",
    "awg_sequencer_interface",
    "digitizer_control_interface",
    "digitizer_input_interface",
    "oscilloscope_control_interface",
    "oscilloscope_input_interface",
    "trigger_coordinator_interface",
]
