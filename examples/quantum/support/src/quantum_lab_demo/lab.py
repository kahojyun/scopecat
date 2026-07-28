"""Notebook-side compiler and experiment-system composition."""

from __future__ import annotations

from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot

from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.targets.fake_list_mode import configured_fake_list_target


def quantum_lab_system(
    *,
    config: ConfigProfileSnapshot,
    instrument_catalog: InstrumentContractCatalog,
) -> ExperimentSystem:
    """Compose one process-local system for notebook execution.

    Keeping domain dispatch at this single boundary gives every example the
    same routing, resource model, and target pipeline while each operation
    still specializes its own accepted parameter snapshot.
    """

    return ExperimentSystem(
        instrument_catalog=instrument_catalog,
        domain_compiler=QuantumLabCompiler(
            target=configured_fake_list_target(config),
        ),
    )


__all__ = [
    "quantum_lab_system",
]
