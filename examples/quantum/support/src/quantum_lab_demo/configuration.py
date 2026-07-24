"""Paths and connection defaults owned by the runnable quantum demo."""

from __future__ import annotations

from pathlib import Path

from scopecat.records.config import (
    ConfigProfileSnapshot,
    EnvironmentSpec,
    SystemSpec,
    snapshot_config_profile,
)

from quantum_lab_demo.parameters import quantum_lab_parameter_snapshot

EXAMPLE_ROOT = Path(__file__).resolve().parents[3]
DEMO_CONFIG_DIR = EXAMPLE_ROOT / "config"
DEMO_VIRTUAL_LAB_PROFILE = DEMO_CONFIG_DIR / "virtual-lab.json"

DAEMON_URL_ENV = "SCOPECAT_DAEMON_URL"


def quantum_lab_bootstrap_config(
    config_dir: str | Path = DEMO_CONFIG_DIR,
) -> ConfigProfileSnapshot:
    """Combine schema-checked infrastructure with Python-owned table values."""

    root = Path(config_dir)
    system = SystemSpec.model_validate_json(
        (root / "system-spec.json").read_text(encoding="utf-8")
    )
    environment = EnvironmentSpec.model_validate_json(
        (root / "environment-spec.json").read_text(encoding="utf-8")
    )
    return snapshot_config_profile(
        profile_id="templates-profile",
        system=system,
        environment=environment,
        parameter_snapshot=quantum_lab_parameter_snapshot(),
    )


__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "DEMO_VIRTUAL_LAB_PROFILE",
    "EXAMPLE_ROOT",
    "quantum_lab_bootstrap_config",
]
