"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceSpec,
    acquisition,
    acquisition_result,
    bool_property,
    int_property,
    interface,
)

import scopecat_instruments.members as member_refs
from scopecat_instruments.interface_declarations import (
    DC_MONITOR_DECLARATION,
    DC_SOURCE_DECLARATION,
    NETWORK_SWEEP_DECLARATION,
    RF_OUTPUT_DECLARATION,
)


def rf_output_interface() -> InterfaceSpec:
    return RF_OUTPUT_DECLARATION.fresh_spec()


def dc_source_interface() -> InterfaceSpec:
    return DC_SOURCE_DECLARATION.fresh_spec()


def dc_monitor_interface() -> InterfaceSpec:
    return DC_MONITOR_DECLARATION.fresh_spec()


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
