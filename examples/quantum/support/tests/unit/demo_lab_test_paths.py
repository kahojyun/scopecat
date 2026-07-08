from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2]
REPO_ROOT = Path(__file__).parents[5]
QUANTUM_FIXTURE_DIR = REPO_ROOT / "fixtures" / "quantum"

EXPERIMENT_FIXTURE_DIR = QUANTUM_FIXTURE_DIR / "experiment_system"
EXPERIMENT_VIRTUAL_LAB_PROFILE = EXPERIMENT_FIXTURE_DIR / "virtual-lab.json"
