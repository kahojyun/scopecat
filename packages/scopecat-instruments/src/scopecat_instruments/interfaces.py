"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceSpec,
    acquisition,
    acquisition_axis,
    acquisition_result,
    bool_property,
    enum_property,
    float_property,
    int_property,
    interface,
    quantity_property,
)

RF_OUTPUT = "scopecat.rf_output/v1"
DC_SOURCE = "scopecat.dc_source/v1"
DC_MONITOR = "scopecat.dc_monitor/v1"
TEMPERATURE_READOUT = "scopecat.temperature_readout/v1"
NETWORK_SWEEP = "scopecat.network_sweep/v1"


def rf_output_interface() -> InterfaceSpec:
    return interface(
        RF_OUTPUT,
        label="RF output",
        description="Continuous-wave RF source controls independent of vendor syntax.",
        properties=[
            quantity_property(
                "frequency",
                unit="Hz",
                label="CW frequency",
                description="Continuous-wave carrier frequency.",
            ),
            quantity_property(
                "power",
                unit="dBm",
                label="Output power",
                description="Configured RF output level at the source connector.",
            ),
            bool_property(
                "output_enabled",
                label="RF output",
                description="Whether the RF output connector is enabled.",
            ),
            enum_property(
                "reference_source",
                choices=("internal", "external"),
                label="Reference source",
                description=(
                    "Reference oscillator source; external frequency is not set."
                ),
            ),
        ],
    )


def dc_source_interface() -> InterfaceSpec:
    return interface(
        DC_SOURCE,
        label="DC source",
        description=(
            "DC voltage/current source controls. Voltage and current level/range "
            "properties are explicit so their units remain stable."
        ),
        properties=[
            enum_property(
                "source_mode",
                choices=("voltage", "current"),
                label="Source mode",
                description="Select voltage or current sourcing.",
            ),
            quantity_property(
                "voltage_range",
                unit="V",
                label="Voltage range",
                description="Selecting this property also selects voltage source mode.",
            ),
            quantity_property(
                "current_range",
                unit="A",
                label="Current range",
                description="Selecting this property also selects current source mode.",
            ),
            quantity_property(
                "voltage_level",
                unit="V",
                label="Voltage level",
                description="Selecting this property also selects voltage source mode.",
            ),
            quantity_property(
                "current_level",
                unit="A",
                label="Current level",
                description="Selecting this property also selects current source mode.",
            ),
            quantity_property(
                "voltage_protection",
                unit="V",
                label="Voltage protection",
                description="Absolute voltage limiter level.",
            ),
            quantity_property(
                "current_protection",
                unit="A",
                label="Current protection",
                description="Absolute current limiter level.",
            ),
            bool_property(
                "output_enabled",
                label="DC output",
                description="Whether the source output is enabled.",
            ),
        ],
    )


def dc_monitor_interface() -> InterfaceSpec:
    return interface(
        DC_MONITOR,
        label="DC monitor",
        description="Single-value voltage or current monitoring for a DC source.",
        acquisitions=[
            acquisition(
                "monitor",
                label="Monitor output",
                description="Read one monitor sample from the active source mode.",
                results=[
                    acquisition_result(
                        "monitored_voltage",
                        dtype="float64",
                        unit="V",
                        label="Monitored voltage",
                        description="One measurement while sourcing current.",
                    ),
                    acquisition_result(
                        "monitored_current",
                        dtype="float64",
                        unit="A",
                        label="Monitored current",
                        description="One measurement while sourcing voltage.",
                    ),
                ],
            )
        ],
    )


def temperature_readout_interface() -> InterfaceSpec:
    return interface(
        TEMPERATURE_READOUT,
        label="Temperature readout",
        description=(
            "Read-only sensor, scanner, and sample-heater telemetry. No heater "
            "control commands are exposed by the first driver version."
        ),
        properties=[
            int_property(
                "scan_channel",
                minimum=1,
                maximum=16,
                label="Scan channel",
                description="Sensor input currently selected by the scanner.",
                access="read_only",
            ),
            bool_property(
                "autoscan_enabled",
                label="Autoscan",
                description="Whether the input scanner is advancing automatically.",
                access="read_only",
            ),
            quantity_property(
                "temperature",
                unit="K",
                label="Temperature",
                description="Temperature reading for the active scan channel.",
                access="read_only",
            ),
            quantity_property(
                "resistance",
                unit="Ohm",
                label="Sensor resistance",
                description="Resistance reading for the active scan channel.",
                access="read_only",
            ),
            int_property(
                "reading_status",
                minimum=0,
                maximum=255,
                label="Reading status bits",
                description="Lake Shore RDGST bit-weighted status value.",
                access="read_only",
            ),
            float_property(
                "heater_output",
                label="Sample heater output",
                description="Instrument-reported sample-heater telemetry value.",
                access="read_only",
            ),
            int_property(
                "heater_range",
                minimum=0,
                maximum=8,
                label="Sample heater range",
                description="Instrument-reported sample-heater range code.",
                access="read_only",
            ),
            int_property(
                "heater_status",
                minimum=0,
                maximum=3,
                label="Sample heater status",
                description="0 OK, 1 open, 2 short, 3 voltage compliance.",
                access="read_only",
            ),
        ],
        acquisitions=[
            acquisition(
                "sample",
                label="Sample telemetry",
                description="Read telemetry for the active scan channel.",
                results=[
                    acquisition_result(
                        "temperature",
                        unit="K",
                        label="Temperature",
                        description="Current scan-channel temperature.",
                    ),
                    acquisition_result(
                        "resistance",
                        unit="Ohm",
                        label="Resistance",
                        description="Current scan-channel sensor resistance.",
                    ),
                ],
            ),
        ],
    )


def network_sweep_interface() -> InterfaceSpec:
    frequency_axis = acquisition_axis(
        "frequency",
        kind="frequency",
        unit="Hz",
        label="Frequency",
        description="Linear VNA stimulus frequency.",
    )
    return interface(
        NETWORK_SWEEP,
        label="Network sweep",
        description="Linear, single-trigger complex S-parameter sweep.",
        properties=[
            quantity_property(
                "start_frequency",
                unit="Hz",
                label="Start frequency",
                description="First stimulus frequency in the linear sweep.",
            ),
            quantity_property(
                "stop_frequency",
                unit="Hz",
                label="Stop frequency",
                description="Last stimulus frequency in the linear sweep.",
            ),
            int_property(
                "points",
                minimum=2,
                label="Sweep points",
                description="Number of equally spaced frequency points.",
            ),
            quantity_property(
                "if_bandwidth",
                unit="Hz",
                label="IF bandwidth",
                description="Receiver intermediate-frequency bandwidth.",
            ),
            quantity_property(
                "source_power",
                unit="dBm",
                label="Source power",
                description="Stimulus power for the selected analyzer channel.",
            ),
            enum_property(
                "s_parameter",
                choices=("S11", "S21", "S12", "S22"),
                label="S-parameter",
                description="Two-port S-parameter measured by the selected trace.",
            ),
        ],
        acquisitions=[
            acquisition(
                "sweep",
                label="Acquire sweep",
                description="Trigger and read the configured network sweep.",
                results=[
                    acquisition_result(
                        "frequency",
                        dtype="float64",
                        unit="Hz",
                        label="Frequency",
                        description="Stimulus frequency values for the acquired trace.",
                        axes=[frequency_axis],
                    ),
                    acquisition_result(
                        "s_parameter",
                        dtype="complex128",
                        unit="ratio",
                        label="Complex S-parameter",
                        description=(
                            "Complex response values for the configured S-parameter."
                        ),
                        axes=[frequency_axis],
                    ),
                ],
            ),
        ],
    )


__all__ = [
    "DC_MONITOR",
    "DC_SOURCE",
    "NETWORK_SWEEP",
    "RF_OUTPUT",
    "TEMPERATURE_READOUT",
    "dc_monitor_interface",
    "dc_source_interface",
    "network_sweep_interface",
    "rf_output_interface",
    "temperature_readout_interface",
]
