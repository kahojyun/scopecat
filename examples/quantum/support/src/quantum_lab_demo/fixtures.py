"""Repository-local paths for example Scopecat adoption workflows."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "quantum"

EXPERIMENT_FIXTURE_DIR = FIXTURES_DIR / "experiment_system"

EXPERIMENT_VIRTUAL_LAB_PROFILE = EXPERIMENT_FIXTURE_DIR / "virtual-lab.json"

DEFAULT_WORKSPACE_ROOT = REPO_ROOT / ".scopecat-examples"
DEFAULT_EXPERIMENT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "experiment-system"

NOTEBOOK_WORKSPACE_ROOT_ENV = "QUANTUM_LAB_DEMO_NOTEBOOK_WORKSPACE_ROOT"


def notebook_workspace(name: str) -> Path:
    root = Path(os.environ.get(NOTEBOOK_WORKSPACE_ROOT_ENV, DEFAULT_WORKSPACE_ROOT))
    return root / "notebooks" / name


__all__ = [
    "DEFAULT_EXPERIMENT_WORKSPACE",
    "DEFAULT_WORKSPACE_ROOT",
    "EXPERIMENT_FIXTURE_DIR",
    "EXPERIMENT_VIRTUAL_LAB_PROFILE",
    "FIXTURES_DIR",
    "NOTEBOOK_WORKSPACE_ROOT_ENV",
    "REPO_ROOT",
    "notebook_workspace",
]
