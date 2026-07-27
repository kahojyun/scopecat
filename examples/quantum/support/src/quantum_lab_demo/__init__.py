"""Demo quantum lab package used by the Scopecat examples."""

from quantum_lab_demo.application import quantum_lab_application
from quantum_lab_demo.compiler import QuantumLabCompiler
from quantum_lab_demo.configuration import (
    DAEMON_URL_ENV,
    DEMO_CONFIG_DIR,
    DEMO_VIRTUAL_LAB_PROFILE,
    EXAMPLE_ROOT,
    quantum_lab_bootstrap_config,
)
from quantum_lab_demo.lab import quantum_lab_system
from quantum_lab_demo.point_values import QuantumLabPointValues

__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "DEMO_VIRTUAL_LAB_PROFILE",
    "EXAMPLE_ROOT",
    "QuantumLabCompiler",
    "QuantumLabPointValues",
    "__version__",
    "quantum_lab_application",
    "quantum_lab_bootstrap_config",
    "quantum_lab_system",
]

__version__ = "0.1.0"
