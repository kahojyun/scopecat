# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Configured real and virtual instrument provider for Scopecat."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat_instruments.clients import (
        DCMonitorPatch,
        DCMonitorReadback,
        DCSourceClient,
        DCSourceCurrentPatch,
        DCSourcePatch,
        DCSourceVoltagePatch,
        NetworkSweepClient,
        NetworkSweepPatch,
        NetworkSweepReadback,
        RFOutputClient,
        RFOutputPatch,
        TemperatureReadback,
        TemperatureReadoutClient,
        dc_source,
        network_sweep,
        rf_output,
        temperature_readout,
    )
    from scopecat_instruments.provider import ConfiguredInstrumentProvider
    from scopecat_instruments.targets import (
        DCMonitorTarget,
        DCSourceCurrentTarget,
        DCSourceTarget,
        DCSourceVoltageTarget,
        Desired,
        NetworkSweepTarget,
        RFOutputTarget,
    )


_CLIENT_EXPORTS = {
    "DCMonitorPatch",
    "DCMonitorReadback",
    "DCSourceClient",
    "DCSourceCurrentPatch",
    "DCSourcePatch",
    "DCSourceVoltagePatch",
    "NetworkSweepClient",
    "NetworkSweepPatch",
    "NetworkSweepReadback",
    "RFOutputClient",
    "RFOutputPatch",
    "TemperatureReadback",
    "TemperatureReadoutClient",
    "dc_source",
    "network_sweep",
    "rf_output",
    "temperature_readout",
}

_TARGET_EXPORTS = {
    "DCMonitorTarget",
    "DCSourceCurrentTarget",
    "DCSourceTarget",
    "DCSourceVoltageTarget",
    "Desired",
    "NetworkSweepTarget",
    "RFOutputTarget",
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
    elif name in _TARGET_EXPORTS:
        value = cast(
            "object",
            getattr(import_module("scopecat_instruments.targets"), name),
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
            *_TARGET_EXPORTS,
        )
    )


__all__ = sorted(("ConfiguredInstrumentProvider", *_CLIENT_EXPORTS, *_TARGET_EXPORTS))
