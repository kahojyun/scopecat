# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Configured real and virtual instrument provider for Scopecat."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat_instruments.clients import (
        DCMonitorProducts,
        DCMonitorReadback,
        DCSourceClient,
        DCSourceMonitorClient,
        NetworkSweepClient,
        NetworkSweepProducts,
        NetworkSweepReadback,
        RFOutputClient,
        SymbolicDCSourceClient,
        SymbolicDCSourceGroup,
        SymbolicDCSourceMonitorClient,
        SymbolicDCSourceMonitorGroup,
        SymbolicInstrumentRecorder,
        SymbolicNetworkSweepClient,
        SymbolicNetworkSweepGroup,
        SymbolicRFOutputClient,
        SymbolicRFOutputGroup,
        SymbolicTemperatureReadoutClient,
        SymbolicTemperatureReadoutGroup,
        TemperatureReadback,
        TemperatureReadoutClient,
        TemperatureReadoutObservation,
        TemperatureSampleProducts,
        dc_source,
        network_sweep,
        rf_output,
        temperature_readout,
    )
    from scopecat_instruments.provider import ConfiguredInstrumentProvider
    from scopecat_instruments.states import (
        DCMonitorState,
        DCSourceCurrent,
        DCSourceState,
        DCSourceVoltage,
        Desired,
        NetworkSweepState,
        ReferenceSource,
        RFOutputState,
        SParameter,
    )


_CLIENT_EXPORTS = {
    "DCMonitorProducts",
    "DCMonitorReadback",
    "DCSourceClient",
    "DCSourceMonitorClient",
    "NetworkSweepClient",
    "NetworkSweepProducts",
    "NetworkSweepReadback",
    "RFOutputClient",
    "SymbolicDCSourceClient",
    "SymbolicDCSourceGroup",
    "SymbolicDCSourceMonitorClient",
    "SymbolicDCSourceMonitorGroup",
    "SymbolicInstrumentRecorder",
    "SymbolicNetworkSweepClient",
    "SymbolicNetworkSweepGroup",
    "SymbolicRFOutputClient",
    "SymbolicRFOutputGroup",
    "SymbolicTemperatureReadoutClient",
    "SymbolicTemperatureReadoutGroup",
    "TemperatureReadback",
    "TemperatureReadoutClient",
    "TemperatureReadoutObservation",
    "TemperatureSampleProducts",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
}

_STATE_EXPORTS = {
    "DCMonitorState",
    "DCSourceCurrent",
    "DCSourceState",
    "DCSourceVoltage",
    "Desired",
    "NetworkSweepState",
    "RFOutputState",
    "ReferenceSource",
    "SParameter",
}


def __getattr__(name: str) -> object:
    if name == "ConfiguredInstrumentProvider":
        value = cast(
            "object",
            import_module("scopecat_instruments.provider").ConfiguredInstrumentProvider,
        )
    elif name in _CLIENT_EXPORTS:
        value = cast(
            "object",
            getattr(import_module("scopecat_instruments.clients"), name),
        )
    elif name in _STATE_EXPORTS:
        value = cast(
            "object",
            getattr(import_module("scopecat_instruments.states"), name),
        )
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(
        (
            *globals(),
            "ConfiguredInstrumentProvider",
            *_CLIENT_EXPORTS,
            *_STATE_EXPORTS,
        )
    )


__all__ = sorted(("ConfiguredInstrumentProvider", *_CLIENT_EXPORTS, *_STATE_EXPORTS))
