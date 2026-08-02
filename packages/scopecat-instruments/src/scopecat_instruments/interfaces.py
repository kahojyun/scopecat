"""Vendor-neutral interface contracts shared by real and virtual drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import InterfaceSpec
from scopecat.sdk.instruments.declarations import compile_interface

from scopecat_instruments.interface_declarations import (
    DCMonitorInterface,
    DCSourceInterface,
    NetworkSweepInterface,
    RFOutputInterface,
    TemperatureReadoutInterface,
)


def rf_output_interface() -> InterfaceSpec:
    return compile_interface(RFOutputInterface).fresh_spec()


def dc_source_interface() -> InterfaceSpec:
    return compile_interface(DCSourceInterface).fresh_spec()


def dc_monitor_interface() -> InterfaceSpec:
    return compile_interface(DCMonitorInterface).fresh_spec()


def temperature_readout_interface() -> InterfaceSpec:
    return compile_interface(TemperatureReadoutInterface).fresh_spec()


def network_sweep_interface() -> InterfaceSpec:
    return compile_interface(NetworkSweepInterface).fresh_spec()


__all__ = [
    "dc_monitor_interface",
    "dc_source_interface",
    "network_sweep_interface",
    "rf_output_interface",
    "temperature_readout_interface",
]
