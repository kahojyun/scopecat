"""Daemon application factory for the runnable quantum lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication

from quantum_lab_demo.lab import quantum_lab_system


def quantum_lab_application(project_root: Path) -> LabApplication:
    """Compose the daemon from configuration owned by the selected project."""

    virtual_lab_profile = project_root / "config" / "virtual-lab.json"
    return LabApplication(
        build_system=lambda config: quantum_lab_system(
            config=config,
            virtual_lab_profile=virtual_lab_profile,
        ),
    )


__all__ = ["quantum_lab_application"]
