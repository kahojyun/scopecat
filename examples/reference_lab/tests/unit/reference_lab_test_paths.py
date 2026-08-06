from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2]
REPO_ROOT = Path(__file__).parents[4]

EXPERIMENT_VIRTUAL_LAB_PROFILE = (
    REPO_ROOT / "examples" / "reference_lab" / "config" / "virtual-lab.json"
)
