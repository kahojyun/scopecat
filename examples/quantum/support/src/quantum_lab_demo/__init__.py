"""Demo quantum lab package used by the Scopecat examples."""

from quantum_lab_demo.application import quantum_lab_application
from quantum_lab_demo.compiler import QuantumLabCompiler, QuantumRealtimeLabCompiler
from quantum_lab_demo.configuration import (
    DAEMON_URL_ENV,
    DEMO_CONFIG_DIR,
    DEMO_CONFIG_PROFILE,
    DEMO_VIRTUAL_LAB_PROFILE,
    EXAMPLE_ROOT,
)
from quantum_lab_demo.lab import (
    quantum_lab_compiler,
    quantum_lab_config_profile,
    quantum_lab_system,
    quantum_realtime_lab_compiler,
)
from quantum_lab_demo.trace import (
    QuantumLabPointValues,
    QuantumLabPreparationEvidence,
    QuantumLabTrace,
)

__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "DEMO_CONFIG_PROFILE",
    "DEMO_VIRTUAL_LAB_PROFILE",
    "EXAMPLE_ROOT",
    "QuantumLabCompiler",
    "QuantumLabPointValues",
    "QuantumLabPreparationEvidence",
    "QuantumLabTrace",
    "QuantumRealtimeLabCompiler",
    "__version__",
    "quantum_lab_application",
    "quantum_lab_compiler",
    "quantum_lab_config_profile",
    "quantum_lab_system",
    "quantum_realtime_lab_compiler",
]

__version__ = "0.1.0"
