"""Virtual-lab profile loading helpers."""

from __future__ import annotations

from pathlib import Path

from quantum_lab_demo.virtual_lab.models import VirtualLabProfile


def load_virtual_lab_profile(profile: str | Path) -> VirtualLabProfile:
    return VirtualLabProfile.model_validate_json(Path(profile).read_text())


__all__ = ["load_virtual_lab_profile"]
