"""Virtual-lab profile loading helpers."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo.virtual_lab.models import VirtualLabProfile

VirtualLabProfileInput = str | Path | VirtualLabProfile


def load_virtual_lab_profile(profile: VirtualLabProfileInput) -> VirtualLabProfile:
    if isinstance(profile, VirtualLabProfile):
        return profile
    return VirtualLabProfile.model_validate_json(Path(profile).read_text())


__all__ = ["VirtualLabProfileInput", "load_virtual_lab_profile"]
