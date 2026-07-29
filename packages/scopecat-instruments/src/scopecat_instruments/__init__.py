"""Configured real and virtual instrument provider for Scopecat."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat_instruments.provider import ConfiguredInstrumentProvider


def __getattr__(name: str) -> object:
    if name != "ConfiguredInstrumentProvider":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = cast(
        "object",
        import_module("scopecat_instruments.provider").ConfiguredInstrumentProvider,
    )
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), "ConfiguredInstrumentProvider"))


__all__ = ["ConfiguredInstrumentProvider"]
