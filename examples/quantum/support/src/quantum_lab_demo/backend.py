"""Worker-only instrument backend composition for the quantum demo."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import InstrumentBackend

PathInput = str | Path


def create_quantum_lab_backend(
    virtual_lab_profile: PathInput,
) -> InstrumentBackend:
    """Load concrete drivers only in the instrument worker."""

    from quantum_lab_demo.payloads import quantum_lab_payload_codecs
    from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider

    return InstrumentBackend(
        provider=QuantumLabVirtualProvider(profile=virtual_lab_profile),
        payload_codecs=quantum_lab_payload_codecs(),
    )


def quantum_lab_backend(project_root: Path) -> InstrumentBackend:
    """Create the project backend inside its instrument worker."""

    return create_quantum_lab_backend(project_root / "config" / "virtual-lab.json")


__all__ = [
    "PathInput",
    "create_quantum_lab_backend",
    "quantum_lab_backend",
]
