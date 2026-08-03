# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Reusable deterministic virtual laboratory instruments."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

from scopecat_instruments.package_manifest import PACKAGE_MANIFEST

if TYPE_CHECKING:
    from scopecat_instruments.virtual.drivers import (
        VirtualDcSource,
        VirtualNetworkAnalyzer,
        VirtualRfSource,
        VirtualTemperatureMonitor,
    )
    from scopecat_instruments.virtual.world import VirtualLabWorld


_EXPORTS = {
    "VirtualLabWorld": "scopecat_instruments.virtual.world",
    **{
        registration.implementation.qualname: registration.implementation.module
        for registration in PACKAGE_MANIFEST.drivers
        if registration.implementation.module.startswith(f"{__name__}.")
    },
}


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = cast("object", getattr(import_module(module), name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))


__all__ = sorted(_EXPORTS)
