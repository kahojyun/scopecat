"""Daemon composition for the virtual instrument lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication
from scopecat.records.config import ConfigProfileSnapshot


def _bootstrap_config() -> ConfigProfileSnapshot:
    from .configuration import bootstrap_config

    return bootstrap_config()


def create_application(_project_root: Path) -> LabApplication:
    """Compose planning and bootstrap behavior for the virtual lab."""

    return LabApplication(bootstrap_config=_bootstrap_config)


__all__ = ["create_application"]
