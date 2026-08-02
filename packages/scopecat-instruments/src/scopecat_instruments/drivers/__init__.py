# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Minimal transcript-tested real instrument drivers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

from scopecat_instruments.package_manifest import PACKAGE_MANIFEST

if TYPE_CHECKING:
    from scopecat_instruments.drivers.e5080b import KeysightE5080B
    from scopecat_instruments.drivers.gs200 import YokogawaGS200
    from scopecat_instruments.drivers.lakeshore372 import LakeShore372
    from scopecat_instruments.drivers.sgs100a import RohdeSchwarzSGS100A


_EXPORTS = {
    registration.implementation.qualname: registration.implementation.module
    for registration in PACKAGE_MANIFEST.drivers
    if registration.implementation.module.startswith(f"{__name__}.")
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
