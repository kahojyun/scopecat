"""Daemon composition for the virtual instrument lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments import InstrumentBackend


def _bootstrap_config() -> ConfigProfileSnapshot:
    from .configuration import bootstrap_config

    return bootstrap_config()


def _create_instrument_backend() -> InstrumentBackend:
    from .provider import InstrumentDemoProvider

    return InstrumentBackend(provider=InstrumentDemoProvider(seed=7))


def create_application(_project_root: Path) -> LabApplication:
    """Keep one virtual world alive for all daemon-owned device sessions."""

    return LabApplication(
        bootstrap_config=_bootstrap_config,
        create_instrument_backend=_create_instrument_backend,
    )


__all__ = ["create_application"]
