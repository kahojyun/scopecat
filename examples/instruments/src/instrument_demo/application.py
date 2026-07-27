"""Daemon composition for the virtual instrument lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication
from scopecat.planning.system import ExperimentSystem
from scopecat_instruments import ConfiguredInstrumentProvider

from .configuration import bootstrap_config


def create_application(_project_root: Path) -> LabApplication:
    """Keep one virtual world alive for all daemon-owned device sessions."""

    provider = ConfiguredInstrumentProvider(seed=7)
    return LabApplication(
        bootstrap_config=bootstrap_config,
        build_system=lambda _config: ExperimentSystem(provider=provider),
    )


__all__ = ["create_application"]
