"""Vendor-neutral bench AWG and oscilloscope capability identities."""

from __future__ import annotations

from scopecat.kernel.value_types import Payload, Scalar
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
    AWG_PROGRAM_SCHEMA_ID,
    DIGITIZER_PROGRAM_SCHEMA_ID,
    SAMPLED_WAVEFORM_SCHEMA_ID,
    TRIGGER_PROGRAM_SCHEMA_ID,
)

AWG_SEQUENCER = InterfaceRef("reference_lab.awg_sequencer/v1")
AWG_SAMPLE_RATE = AWG_SEQUENCER.property("sample_rate")
AWG_RUN_MODE = AWG_SEQUENCER.property("run_mode")
AWG_LOAD_PROGRAM = AWG_SEQUENCER.operation("load_program")
AWG_PROGRAM = AWG_LOAD_PROGRAM.argument("program")
AWG_ARM_PROGRAM = AWG_SEQUENCER.operation("arm_program")

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
DIGITIZER_LOAD_PROGRAM = DIGITIZER_CONTROL.operation("load_program")
DIGITIZER_PROGRAM = DIGITIZER_LOAD_PROGRAM.argument("program")
DIGITIZER_ARM_PROGRAM = DIGITIZER_CONTROL.operation("arm_program")

DIGITIZER_INPUT = InterfaceRef("reference_lab.digitizer_input/v1")
DIGITIZER_INPUT_ENABLED = DIGITIZER_INPUT.property("input_enabled")
DIGITIZER_INPUT_RANGE = DIGITIZER_INPUT.property("input_range")
DIGITIZER_INPUT_COUPLING = DIGITIZER_INPUT.property("coupling")
DIGITIZER_FETCH_PROGRAM = DIGITIZER_INPUT.acquisition("fetch_program")
DIGITIZER_FETCH_PROGRAM_VALUE = DIGITIZER_FETCH_PROGRAM.result("value")
DIGITIZER_FETCH_PROGRAM_IQ = DIGITIZER_INPUT.acquisition("fetch_program_iq")
DIGITIZER_FETCH_PROGRAM_IQ_VALUE = DIGITIZER_FETCH_PROGRAM_IQ.result("value")

TRIGGER_COORDINATOR = InterfaceRef("reference_lab.trigger_coordinator/v2")
TRIGGER_LOAD_PROGRAM = TRIGGER_COORDINATOR.operation("load_program")
TRIGGER_PROGRAM = TRIGGER_LOAD_PROGRAM.argument("program")
TRIGGER_START_PROGRAM = TRIGGER_COORDINATOR.operation("start_program")
TRIGGER_START_PROGRAM_IDEMPOTENT = TRIGGER_COORDINATOR.operation(
    "start_program_idempotent"
)


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
                AWG_ARM_PROGRAM.operation_id,
                label="Arm the complete loaded list program",
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
                DIGITIZER_LOAD_PROGRAM.operation_id,
                label="Load a segmented acquisition program",
                arguments=(
                    operation_argument(
                        DIGITIZER_PROGRAM.argument_id,
                        value_type=Scalar(Payload(DIGITIZER_PROGRAM_SCHEMA_ID)),
                        label="Digitizer program",
                    ),
                ),
            ),
            operation(
                DIGITIZER_ARM_PROGRAM.operation_id,
                label="Arm the complete segmented program",
            ),
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
                DIGITIZER_FETCH_PROGRAM.acquisition_id,
                label="Fetch one flattened segmented raw-capture block",
                results=(
                    acquisition_result(
                        DIGITIZER_FETCH_PROGRAM_VALUE.result_id,
                        unit="V",
                        axes=(sample_axis,),
                    ),
                ),
            ),
            acquisition(
                DIGITIZER_FETCH_PROGRAM_IQ.acquisition_id,
                label="Fetch one flattened segmented integrated-IQ block",
                results=(
                    acquisition_result(
                        DIGITIZER_FETCH_PROGRAM_IQ_VALUE.result_id,
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
        description="Execute a shared multi-entry trigger program for armed devices.",
        operations=(
            operation(
                TRIGGER_LOAD_PROGRAM.operation_id,
                label="Load a multi-entry trigger program",
                arguments=(
                    operation_argument(
                        TRIGGER_PROGRAM.argument_id,
                        value_type=Scalar(Payload(TRIGGER_PROGRAM_SCHEMA_ID)),
                        label="Trigger program",
                    ),
                ),
            ),
            operation(
                TRIGGER_START_PROGRAM.operation_id,
                label="Start one non-idempotent loaded trigger program",
            ),
            operation(
                TRIGGER_START_PROGRAM_IDEMPOTENT.operation_id,
                label="Start one session-idempotent loaded trigger program",
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
    "AWG_ARM_PROGRAM",
    "AWG_RUN_MODE",
    "AWG_SAMPLE_RATE",
    "AWG_SEQUENCER",
    "DIGITIZER_ARM_PROGRAM",
    "DIGITIZER_CONTROL",
    "DIGITIZER_FETCH_PROGRAM",
    "DIGITIZER_FETCH_PROGRAM_IQ",
    "DIGITIZER_FETCH_PROGRAM_IQ_VALUE",
    "DIGITIZER_FETCH_PROGRAM_VALUE",
    "DIGITIZER_INPUT",
    "DIGITIZER_INPUT_COUPLING",
    "DIGITIZER_INPUT_ENABLED",
    "DIGITIZER_INPUT_RANGE",
    "DIGITIZER_LOAD_PROGRAM",
    "DIGITIZER_PROGRAM",
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
    "TRIGGER_LOAD_PROGRAM",
    "TRIGGER_PROGRAM",
    "TRIGGER_START_PROGRAM",
    "TRIGGER_START_PROGRAM_IDEMPOTENT",
    "analog_waveform_output_interface",
    "awg_sequencer_interface",
    "digitizer_control_interface",
    "digitizer_input_interface",
    "oscilloscope_control_interface",
    "oscilloscope_input_interface",
    "trigger_coordinator_interface",
]
