"""Demo quantum lab package used by the Scopecat examples."""

from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.fixtures import (
    DEFAULT_EXPERIMENT_WORKSPACE,
    DEFAULT_WORKSPACE_ROOT,
    EXPERIMENT_FIXTURE_DIR,
    EXPERIMENT_VIRTUAL_LAB_PROFILE,
    FIXTURES_DIR,
    NOTEBOOK_WORKSPACE_ROOT_ENV,
    REPO_ROOT,
    notebook_workspace,
)
from quantum_lab_demo.lab import (
    quantum_lab,
    quantum_lab_compiler,
    quantum_realtime_lab_compiler,
)
from quantum_lab_demo.trace import (
    QuantumLabPointValues,
    QuantumLabPreparationEvidence,
    QuantumLabTrace,
)

__all__ = [
    "DEFAULT_EXPERIMENT_WORKSPACE",
    "DEFAULT_WORKSPACE_ROOT",
    "EXPERIMENT_FIXTURE_DIR",
    "EXPERIMENT_VIRTUAL_LAB_PROFILE",
    "FIXTURES_DIR",
    "NOTEBOOK_WORKSPACE_ROOT_ENV",
    "REPO_ROOT",
    "QuantumLabCompiler",
    "QuantumLabPointValues",
    "QuantumLabPreparationEvidence",
    "QuantumLabTrace",
    "QuantumRealtimeLabCompiler",
    "__version__",
    "notebook_workspace",
    "quantum_lab",
    "quantum_lab_compiler",
    "quantum_realtime_lab_compiler",
]

__version__ = "0.1.0"
