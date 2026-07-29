"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceSpec,
    acquisition,
    acquisition_axis,
    acquisition_case,
    acquisition_result,
    bool_property,
    discriminated_state,
    enum_property,
    int_property,
    interface,
    quantity_property,
    state_case,
    state_discriminated_acquisition,
    state_discriminator_ref,
)

import scopecat_instruments.members as member_refs


def rf_output_interface() -> InterfaceSpec:
    return interface(
        member_refs.RF_OUTPUT.interface_id,
        label="RF output",
        description="Continuous-wave RF source controls independent of vendor syntax.",
        properties=[
            quantity_property(
                member_refs.RF_OUTPUT_FREQUENCY.property_id,
                unit="Hz",
                label="CW frequency",
                description="Continuous-wave carrier frequency.",
            ),
            quantity_property(
                member_refs.RF_OUTPUT_POWER.property_id,
                unit="dBm",
                label="Output power",
                description="Configured RF output level at the source connector.",
            ),
            bool_property(
                member_refs.RF_OUTPUT_ENABLED.property_id,
                label="RF output",
                description="Whether the RF output connector is enabled.",
            ),
            enum_property(
                member_refs.RF_OUTPUT_REFERENCE_SOURCE.property_id,
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
        member_refs.DC_SOURCE.interface_id,
        label="DC source",
        description=(
            "DC voltage/current source controls with mode-specific level and range "
            "state."
        ),
        properties=[
            enum_property(
                member_refs.DC_SOURCE_MODE.property_id,
                choices=("voltage", "current"),
                label="Source mode",
                description="Discriminator selecting voltage or current source state.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_VOLTAGE_RANGE.property_id,
                unit="V",
                label="Voltage range",
                description="Voltage-source range, available in voltage mode.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_CURRENT_RANGE.property_id,
                unit="A",
                label="Current range",
                description="Current-source range, available in current mode.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_VOLTAGE_LEVEL.property_id,
                unit="V",
                label="Voltage level",
                description="Voltage-source level, available in voltage mode.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_CURRENT_LEVEL.property_id,
                unit="A",
                label="Current level",
                description="Current-source level, available in current mode.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_VOLTAGE_PROTECTION.property_id,
                unit="V",
                label="Voltage protection",
                description="Absolute voltage limiter level.",
            ),
            quantity_property(
                member_refs.DC_SOURCE_CURRENT_PROTECTION.property_id,
                unit="A",
                label="Current protection",
                description="Absolute current limiter level.",
            ),
            bool_property(
                member_refs.DC_SOURCE_OUTPUT_ENABLED.property_id,
                label="DC output",
                description="Whether the source output is enabled.",
            ),
        ],
        state=discriminated_state(
            member_refs.DC_SOURCE_MODE.property_id,
            common_property_ids=(
                member_refs.DC_SOURCE_VOLTAGE_PROTECTION.property_id,
                member_refs.DC_SOURCE_CURRENT_PROTECTION.property_id,
                member_refs.DC_SOURCE_OUTPUT_ENABLED.property_id,
            ),
            cases=(
                state_case(
                    "voltage",
                    property_ids=(
                        member_refs.DC_SOURCE_VOLTAGE_RANGE.property_id,
                        member_refs.DC_SOURCE_VOLTAGE_LEVEL.property_id,
                    ),
                ),
                state_case(
                    "current",
                    property_ids=(
                        member_refs.DC_SOURCE_CURRENT_RANGE.property_id,
                        member_refs.DC_SOURCE_CURRENT_LEVEL.property_id,
                    ),
                ),
            ),
        ),
    )


def dc_monitor_interface() -> InterfaceSpec:
    return interface(
        member_refs.DC_MONITOR.interface_id,
        label="DC monitor",
        description="Single-value voltage or current monitoring for a DC source.",
        properties=[
            bool_property(
                member_refs.DC_MONITOR_MEASUREMENT_ENABLED.property_id,
                label="Measurement",
                description="Whether monitor measurements are enabled.",
            ),
            int_property(
                member_refs.DC_MONITOR_INTEGRATION_CYCLES.property_id,
                minimum=1,
                maximum=25,
                label="Integration cycles",
                description="Power-line cycles integrated for each measurement.",
            ),
            quantity_property(
                member_refs.DC_MONITOR_MEASUREMENT_DELAY.property_id,
                unit="s",
                minimum=0.0,
                maximum=999.999,
                label="Measurement delay",
                description="Delay between measurement trigger and sampling.",
            ),
        ],
        acquisitions=[
            state_discriminated_acquisition(
                member_refs.DC_MONITOR_ACQUISITION.acquisition_id,
                label="Monitor output",
                description="Read one monitor sample from the active source mode.",
                discriminator=state_discriminator_ref(
                    member_refs.DC_SOURCE_MODE.interface_id,
                    member_refs.DC_SOURCE_MODE.property_id,
                    component_path=member_refs.DC_SOURCE_MODE.component_path,
                ),
                cases=[
                    acquisition_case(
                        "voltage",
                        results=[
                            acquisition_result(
                                member_refs.DC_MONITOR_CURRENT_RESULT.result_id,
                                dtype="float64",
                                unit="A",
                                label="Monitored current",
                                description="One measurement while sourcing voltage.",
                            ),
                        ],
                    ),
                    acquisition_case(
                        "current",
                        results=[
                            acquisition_result(
                                member_refs.DC_MONITOR_VOLTAGE_RESULT.result_id,
                                dtype="float64",
                                unit="V",
                                label="Monitored voltage",
                                description="One measurement while sourcing current.",
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


def temperature_readout_interface() -> InterfaceSpec:
    return interface(
        member_refs.TEMPERATURE_READOUT.interface_id,
        label="Temperature readout",
        description=(
            "Read-only scanner state and settled temperature or resistance "
            "acquisition. Heater control belongs to a separate interface."
        ),
        properties=[
            int_property(
                member_refs.TEMPERATURE_READOUT_SCAN_CHANNEL.property_id,
                minimum=1,
                maximum=16,
                label="Scan channel",
                description="Sensor input currently selected by the scanner.",
                access="read_only",
            ),
            bool_property(
                member_refs.TEMPERATURE_READOUT_AUTOSCAN_ENABLED.property_id,
                label="Autoscan",
                description="Whether the input scanner is advancing automatically.",
                access="read_only",
            ),
        ],
        acquisitions=[
            acquisition(
                member_refs.TEMPERATURE_READOUT_SAMPLE.acquisition_id,
                label="Sample sensor",
                description="Read a settled sample from one coherent scan channel.",
                results=[
                    acquisition_result(
                        member_refs.TEMPERATURE_READOUT_TEMPERATURE_RESULT.result_id,
                        unit="K",
                        label="Temperature",
                        description="Current scan-channel temperature.",
                    ),
                    acquisition_result(
                        member_refs.TEMPERATURE_READOUT_RESISTANCE_RESULT.result_id,
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
        member_refs.NETWORK_SWEEP.interface_id,
        label="Network sweep",
        description="Linear, single-trigger complex S-parameter sweep.",
        properties=[
            quantity_property(
                member_refs.NETWORK_SWEEP_START_FREQUENCY.property_id,
                unit="Hz",
                label="Start frequency",
                description="First stimulus frequency in the linear sweep.",
            ),
            quantity_property(
                member_refs.NETWORK_SWEEP_STOP_FREQUENCY.property_id,
                unit="Hz",
                label="Stop frequency",
                description="Last stimulus frequency in the linear sweep.",
            ),
            int_property(
                member_refs.NETWORK_SWEEP_POINTS.property_id,
                minimum=2,
                label="Sweep points",
                description="Number of equally spaced frequency points.",
            ),
            quantity_property(
                member_refs.NETWORK_SWEEP_IF_BANDWIDTH.property_id,
                unit="Hz",
                label="IF bandwidth",
                description="Receiver intermediate-frequency bandwidth.",
            ),
            quantity_property(
                member_refs.NETWORK_SWEEP_SOURCE_POWER.property_id,
                unit="dBm",
                label="Source power",
                description="Stimulus power for the selected analyzer channel.",
            ),
            enum_property(
                member_refs.NETWORK_SWEEP_S_PARAMETER.property_id,
                choices=("S11", "S21", "S12", "S22"),
                label="S-parameter",
                description="Two-port S-parameter measured by the selected trace.",
            ),
        ],
        acquisitions=[
            acquisition(
                member_refs.NETWORK_SWEEP_ACQUISITION.acquisition_id,
                label="Acquire sweep",
                description="Trigger and read the configured network sweep.",
                results=[
                    acquisition_result(
                        member_refs.NETWORK_SWEEP_FREQUENCY_RESULT.result_id,
                        dtype="float64",
                        unit="Hz",
                        label="Frequency",
                        description="Stimulus frequency values for the acquired trace.",
                        axes=[frequency_axis],
                    ),
                    acquisition_result(
                        member_refs.NETWORK_SWEEP_S_PARAMETER_RESULT.result_id,
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
    "dc_monitor_interface",
    "dc_source_interface",
    "network_sweep_interface",
    "rf_output_interface",
    "temperature_readout_interface",
]
