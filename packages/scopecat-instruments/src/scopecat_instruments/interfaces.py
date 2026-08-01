"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import InterfaceSpec

from scopecat_instruments.interface_declarations import (
    DC_MONITOR_DECLARATION,
    DC_SOURCE_DECLARATION,
    NETWORK_SWEEP_DECLARATION,
    RF_OUTPUT_DECLARATION,
    TEMPERATURE_READOUT_DECLARATION,
)


def rf_output_interface() -> InterfaceSpec:
    return RF_OUTPUT_DECLARATION.fresh_spec()


def dc_source_interface() -> InterfaceSpec:
    return DC_SOURCE_DECLARATION.fresh_spec()


def dc_monitor_interface() -> InterfaceSpec:
    return DC_MONITOR_DECLARATION.fresh_spec()


def temperature_readout_interface() -> InterfaceSpec:
    return TEMPERATURE_READOUT_DECLARATION.fresh_spec()


def network_sweep_interface() -> InterfaceSpec:
    return NETWORK_SWEEP_DECLARATION.fresh_spec()


__all__ = [
    "dc_monitor_interface",
    "dc_source_interface",
    "network_sweep_interface",
    "rf_output_interface",
    "temperature_readout_interface",
]
