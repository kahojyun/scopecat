"""Stable repository and fixture paths shared by workspace tests."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_FIXTURE_DIR = REPO_ROOT / "fixtures" / "core" / "simple_scan"

__all__ = ["CORE_FIXTURE_DIR", "REPO_ROOT"]
