"""Workspace factories for the demo quantum lab workflows."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.models.config import ConfigProfileSnapshot

from quantum_lab_demo.fixtures import (
    DEFAULT_EXPERIMENT_WORKSPACE,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
)
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile

PathInput = str | Path
ConfigProfileInput = PathInput | ConfigProfileSnapshot


def quantum_lab(
    *,
    workspace: PathInput = DEFAULT_EXPERIMENT_WORKSPACE,
    config_profile: ConfigProfileInput | None = None,
    virtual_lab_profile: PathInput = EXPERIMENT_VIRTUAL_LAB_PROFILE,
) -> sc.Workspace:
    return sc.open(
        workspace,
        config_profile=config_profile or quantum_wiring_config_profile(),
        execution_backend=sc.PointInstrumentBackend(
            QuantumLabVirtualProvider(profile=virtual_lab_profile)
        ),
    )


__all__ = [
    "ConfigProfileInput",
    "PathInput",
    "quantum_lab",
]
