"""Daemon application factory for the runnable quantum lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication

from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.lab import quantum_lab_system


def quantum_lab_application(project_root: Path) -> LabApplication:
    """Compose the daemon from configuration owned by the selected project."""

    config_dir = project_root / "config"

    return LabApplication(
        bootstrap_config=lambda: quantum_lab_bootstrap_config(config_dir),
        build_experiment_system=lambda config, instrument_catalog: quantum_lab_system(
            config=config,
            instrument_catalog=instrument_catalog,
        ),
    )


__all__ = ["quantum_lab_application"]
