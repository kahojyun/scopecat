"""Worker-only instrument backend composition for the reference lab."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import InstrumentBackend

PathInput = str | Path


def create_backend_from_profile(
    virtual_lab_profile: PathInput,
) -> InstrumentBackend:
    """Load concrete drivers only in the instrument worker."""

    from reference_lab.payloads import quantum_lab_payload_codecs
    from reference_lab.provider import ReferenceLabProvider

    provider = ReferenceLabProvider(profile=virtual_lab_profile)
    return InstrumentBackend(
        provider=provider,
        driver_catalog=provider.driver_catalog,
        payload_codecs=quantum_lab_payload_codecs(),
    )


def create_backend(project_root: Path) -> InstrumentBackend:
    """Create the project backend inside its instrument worker."""

    return create_backend_from_profile(project_root / "config" / "virtual-lab.json")


__all__ = [
    "PathInput",
    "create_backend",
    "create_backend_from_profile",
]
