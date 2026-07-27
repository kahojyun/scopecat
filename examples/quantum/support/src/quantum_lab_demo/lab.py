"""Quantum demo configuration, compiler, and experiment-system composition."""

from __future__ import annotations

from pathlib import Path

from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.configuration import DEMO_VIRTUAL_LAB_PROFILE
from quantum_lab_demo.targets.fake_list_mode import configured_fake_list_target
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider

PathInput = str | Path


def quantum_lab_system(
    *,
    config: ConfigProfileSnapshot,
    virtual_lab_profile: PathInput = DEMO_VIRTUAL_LAB_PROFILE,
) -> ExperimentSystem:
    """Compose one process-local system for notebook execution.

    Keeping domain dispatch at this single boundary gives every example the
    same routing, resource model, and target pipeline while each operation
    still specializes its own accepted parameter snapshot.
    """

    provider = QuantumLabVirtualProvider(profile=virtual_lab_profile)
    return ExperimentSystem(
        provider=provider,
        domain_compiler=QuantumLabCompiler(
            target=configured_fake_list_target(config),
        ),
    )


__all__ = [
    "PathInput",
    "quantum_lab_system",
]
