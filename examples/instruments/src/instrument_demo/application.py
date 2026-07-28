"""Daemon composition for the virtual instrument lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication
from scopecat.planning.system import ExperimentSystem

from .configuration import bootstrap_config
from .provider import InstrumentDemoProvider


def create_application(_project_root: Path) -> LabApplication:
    """Keep one virtual world alive for all daemon-owned device sessions."""

    provider = InstrumentDemoProvider(seed=7)
    return LabApplication(
        bootstrap_config=bootstrap_config,
        build_system=lambda _config: ExperimentSystem(provider=provider),
    )


__all__ = ["create_application"]
