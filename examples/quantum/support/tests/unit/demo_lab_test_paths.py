from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2]
REPO_ROOT = Path(__file__).parents[5]

EXPERIMENT_VIRTUAL_LAB_PROFILE = (
    REPO_ROOT / "examples" / "quantum" / "config" / "virtual-lab.json"
)
