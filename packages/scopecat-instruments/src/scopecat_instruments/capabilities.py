"""Vendor-neutral capability contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    CapabilityDescription,
    bool_field,
    capability,
    enum_field,
    float_field,
    int_field,
    product,
    product_axis,
    quantity_field,
)

RF_OUTPUT = "rf_output"
DC_OUTPUT = "dc_output"
TEMPERATURE_READOUT = "temperature_readout"
NETWORK_SWEEP = "network_sweep"


def rf_output_capability() -> CapabilityDescription:
    return capability(
        RF_OUTPUT,
        label="RF output",
        description="Continuous-wave RF source controls independent of vendor syntax.",
        fields=[
            quantity_field(
                "frequency",
                unit="Hz",
                label="CW frequency",
                description="Continuous-wave carrier frequency.",
            ),
            quantity_field(
                "power",
                unit="dBm",
                label="Output power",
                description="Configured RF output level at the source connector.",
            ),
            bool_field(
                "output_enabled",
                label="RF output",
                description="Whether the RF output connector is enabled.",
            ),
            enum_field(
                "reference_source",
                choices=("internal", "external"),
                label="Reference source",
                description=(
                    "Reference oscillator source; external frequency is not set."
                ),
            ),
        ],
    )


def dc_output_capability(*, monitor: bool = False) -> CapabilityDescription:
    products = (
        [
            product(
                "monitored_voltage",
                dtype="float64",
                unit="V",
                label="Monitored voltage",
                description="One /MON measurement while sourcing current.",
            ),
            product(
                "monitored_current",
                dtype="float64",
                unit="A",
                label="Monitored current",
                description="One /MON measurement while sourcing voltage.",
            ),
        ]
        if monitor
        else []
    )
    return capability(
        DC_OUTPUT,
        label="DC output",
        description=(
            "DC voltage/current source controls. Voltage and current level/range "
            "fields are explicit so their units remain stable."
        ),
        fields=[
            enum_field(
                "source_mode",
                choices=("voltage", "current"),
                label="Source mode",
                description="Select voltage or current sourcing.",
            ),
            quantity_field(
                "voltage_range",
                unit="V",
                label="Voltage range",
                description="Selecting this field also selects voltage source mode.",
            ),
            quantity_field(
                "current_range",
                unit="A",
                label="Current range",
                description="Selecting this field also selects current source mode.",
            ),
            quantity_field(
                "voltage_level",
                unit="V",
                label="Voltage level",
                description="Selecting this field also selects voltage source mode.",
            ),
            quantity_field(
                "current_level",
                unit="A",
                label="Current level",
                description="Selecting this field also selects current source mode.",
            ),
            quantity_field(
                "voltage_protection",
                unit="V",
                label="Voltage protection",
                description="Absolute voltage limiter level.",
            ),
            quantity_field(
                "current_protection",
                unit="A",
                label="Current protection",
                description="Absolute current limiter level.",
            ),
            bool_field(
                "output_enabled",
                label="DC output",
                description="Whether the source output is enabled.",
            ),
        ],
        products=products,
    )


def temperature_readout_capability() -> CapabilityDescription:
    return capability(
        TEMPERATURE_READOUT,
        label="Temperature readout",
        description=(
            "Read-only sensor, scanner, and sample-heater telemetry. No heater "
            "control commands are exposed by the first driver version."
        ),
        fields=[
            int_field(
                "scan_channel",
                minimum=1,
                maximum=16,
                label="Scan channel",
                description="Sensor input currently selected by the scanner.",
                access="read_only",
            ),
            bool_field(
                "autoscan_enabled",
                label="Autoscan",
                description="Whether the input scanner is advancing automatically.",
                access="read_only",
            ),
            quantity_field(
                "temperature",
                unit="K",
                label="Temperature",
                description="Temperature reading for the active scan channel.",
                access="read_only",
            ),
            quantity_field(
                "resistance",
                unit="Ohm",
                label="Sensor resistance",
                description="Resistance reading for the active scan channel.",
                access="read_only",
            ),
            int_field(
                "reading_status",
                minimum=0,
                maximum=255,
                label="Reading status bits",
                description="Lake Shore RDGST bit-weighted status value.",
                access="read_only",
            ),
            float_field(
                "heater_output",
                label="Sample heater output",
                description="Instrument-reported sample-heater telemetry value.",
                access="read_only",
            ),
            int_field(
                "heater_range",
                minimum=0,
                maximum=8,
                label="Sample heater range",
                description="Instrument-reported sample-heater range code.",
                access="read_only",
            ),
            int_field(
                "heater_status",
                minimum=0,
                maximum=3,
                label="Sample heater status",
                description="0 OK, 1 open, 2 short, 3 voltage compliance.",
                access="read_only",
            ),
        ],
        products=[
            product(
                "temperature",
                unit="K",
                label="Temperature",
                description="Current scan-channel temperature.",
            ),
            product(
                "resistance",
                unit="Ohm",
                label="Resistance",
                description="Current scan-channel sensor resistance.",
            ),
        ],
    )


def network_sweep_capability() -> CapabilityDescription:
    frequency_axis = product_axis(
        "frequency",
        kind="frequency",
        unit="Hz",
        label="Frequency",
        description="Linear VNA stimulus frequency.",
    )
    return capability(
        NETWORK_SWEEP,
        label="Network sweep",
        description="Linear, single-trigger complex S-parameter sweep.",
        fields=[
            quantity_field(
                "start_frequency",
                unit="Hz",
                label="Start frequency",
                description="First stimulus frequency in the linear sweep.",
            ),
            quantity_field(
                "stop_frequency",
                unit="Hz",
                label="Stop frequency",
                description="Last stimulus frequency in the linear sweep.",
            ),
            int_field(
                "points",
                minimum=2,
                label="Sweep points",
                description="Number of equally spaced frequency points.",
            ),
            quantity_field(
                "if_bandwidth",
                unit="Hz",
                label="IF bandwidth",
                description="Receiver intermediate-frequency bandwidth.",
            ),
            quantity_field(
                "source_power",
                unit="dBm",
                label="Source power",
                description="Stimulus power for the selected analyzer channel.",
            ),
            enum_field(
                "s_parameter",
                choices=("S11", "S21", "S12", "S22"),
                label="S-parameter",
                description="Two-port S-parameter measured by the selected trace.",
            ),
        ],
        products=[
            product(
                "frequency",
                dtype="float64",
                unit="Hz",
                label="Frequency",
                description="Stimulus frequency values for the acquired trace.",
                axes=[frequency_axis],
            ),
            product(
                "s_parameter",
                dtype="complex128",
                unit="ratio",
                label="Complex S-parameter",
                description="Complex response values for the configured S-parameter.",
                axes=[frequency_axis],
            ),
        ],
    )


__all__ = [
    "DC_OUTPUT",
    "NETWORK_SWEEP",
    "RF_OUTPUT",
    "TEMPERATURE_READOUT",
    "dc_output_capability",
    "network_sweep_capability",
    "rf_output_capability",
    "temperature_readout_capability",
]
