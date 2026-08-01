"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceSpec,
    acquisition,
    acquisition_case,
    acquisition_precondition,
    acquisition_result,
    bool_property,
    discriminated_state,
    enum_property,
    int_property,
    interface,
    quantity_property,
    state_case,
    state_discriminated_acquisition,
)

import scopecat_instruments.members as member_refs
from scopecat_instruments.interface_declarations import (
    NETWORK_SWEEP_DECLARATION,
    RF_OUTPUT_DECLARATION,
)


def rf_output_interface() -> InterfaceSpec:
    return RF_OUTPUT_DECLARATION.fresh_spec()


def dc_source_interface() -> InterfaceSpec:
    return interface(
        member_refs.DC_SOURCE.interface_id,
        label="DC source",
        description=(
            "DC voltage/current source controls with mode-specific level and range "
            "state."
        ),
        state=discriminated_state(
            enum_property(
                member_refs.DC_SOURCE_MODE.property_id,
                choices=("voltage", "current"),
                label="Source mode",
                description="Discriminator selecting voltage or current source state.",
            ),
            common_properties=(
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
            ),
            cases=(
                state_case(
                    "voltage",
                    properties=(
                        quantity_property(
                            member_refs.DC_SOURCE_VOLTAGE_RANGE.property_id,
                            unit="V",
                            label="Voltage range",
                            description=(
                                "Voltage-source range, available in voltage mode."
                            ),
                        ),
                        quantity_property(
                            member_refs.DC_SOURCE_VOLTAGE_LEVEL.property_id,
                            unit="V",
                            label="Voltage level",
                            description=(
                                "Voltage-source level, available in voltage mode."
                            ),
                        ),
                    ),
                    required_on_entry_property_ids=(
                        member_refs.DC_SOURCE_VOLTAGE_RANGE.property_id,
                        member_refs.DC_SOURCE_VOLTAGE_LEVEL.property_id,
                    ),
                ),
                state_case(
                    "current",
                    properties=(
                        quantity_property(
                            member_refs.DC_SOURCE_CURRENT_RANGE.property_id,
                            unit="A",
                            label="Current range",
                            description=(
                                "Current-source range, available in current mode."
                            ),
                        ),
                        quantity_property(
                            member_refs.DC_SOURCE_CURRENT_LEVEL.property_id,
                            unit="A",
                            label="Current level",
                            description=(
                                "Current-source level, available in current mode."
                            ),
                        ),
                    ),
                    required_on_entry_property_ids=(
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
                discriminator=member_refs.DC_SOURCE_MODE,
                preconditions=[
                    acquisition_precondition(
                        member_refs.DC_SOURCE_OUTPUT_ENABLED,
                        value=True,
                        unavailable_reason="DC source output is disabled.",
                    ),
                    acquisition_precondition(
                        member_refs.DC_MONITOR_MEASUREMENT_ENABLED,
                        value=True,
                        unavailable_reason="DC monitor measurement is disabled.",
                    ),
                ],
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
    return NETWORK_SWEEP_DECLARATION.fresh_spec()


__all__ = [
    "dc_monitor_interface",
    "dc_source_interface",
    "network_sweep_interface",
    "rf_output_interface",
    "temperature_readout_interface",
]
