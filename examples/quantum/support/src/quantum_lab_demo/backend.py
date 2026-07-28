"""Daemon-only instrument backend composition for the quantum demo."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import InstrumentBackend

PathInput = str | Path


def create_quantum_lab_backend(
    virtual_lab_profile: PathInput,
) -> InstrumentBackend:
    """Load concrete drivers only in the daemon process."""

    from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider

    return InstrumentBackend(
        provider=QuantumLabVirtualProvider(profile=virtual_lab_profile),
    )


__all__ = ["PathInput", "create_quantum_lab_backend"]
