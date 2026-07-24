"""Paths and connection defaults owned by the runnable quantum demo."""

from __future__ import annotations

from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[3]
DEMO_CONFIG_DIR = EXAMPLE_ROOT / "config"
DEMO_CONFIG_PROFILE = DEMO_CONFIG_DIR / "config-profile.json"
DEMO_VIRTUAL_LAB_PROFILE = DEMO_CONFIG_DIR / "virtual-lab.json"

DAEMON_URL_ENV = "SCOPECAT_DAEMON_URL"

__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "DEMO_CONFIG_PROFILE",
    "DEMO_VIRTUAL_LAB_PROFILE",
    "EXAMPLE_ROOT",
]
