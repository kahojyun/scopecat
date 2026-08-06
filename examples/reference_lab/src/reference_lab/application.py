"""Daemon application factory for the runnable reference lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication

from reference_lab.configuration import bootstrap_config
from reference_lab.lab import reference_lab_system


def create_application(project_root: Path) -> LabApplication:
    """Compose the daemon from configuration owned by the selected project."""

    config_dir = project_root / "config"

    return LabApplication(
        bootstrap_config=lambda: bootstrap_config(config_dir),
        build_experiment_system=lambda config, instrument_catalog: reference_lab_system(
            config=config,
            instrument_catalog=instrument_catalog,
        ),
    )


__all__ = ["create_application"]
