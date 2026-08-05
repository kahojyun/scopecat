"""Paths and connection defaults owned by the runnable quantum demo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scopecat.records.config import (
    ConfigProfileSnapshot,
    SystemSpec,
    snapshot_config_profile,
)

from quantum_lab_demo.parameters import (
    QUANTUM_PARAMETER_CATALOG,
    quantum_lab_parameter_snapshot,
)

EXAMPLE_ROOT = Path(__file__).resolve().parents[3]
DEMO_CONFIG_DIR = EXAMPLE_ROOT / "config"
DEMO_VIRTUAL_LAB_PROFILE = DEMO_CONFIG_DIR / "virtual-lab.json"

DAEMON_URL_ENV = "SCOPECAT_DAEMON_URL"


def quantum_lab_bootstrap_config(
    config_dir: str | Path = DEMO_CONFIG_DIR,
) -> ConfigProfileSnapshot:
    """Combine infrastructure with the Python-owned parameter system."""

    root = Path(config_dir)
    document = cast(
        "dict[str, object]",
        json.loads((root / "system-infrastructure.json").read_text(encoding="utf-8")),
    )
    document["parameter_catalog"] = QUANTUM_PARAMETER_CATALOG
    system = SystemSpec.model_validate(document)
    return snapshot_config_profile(
        profile_id="quantum-demo-profile",
        system=system,
        parameter_snapshot=quantum_lab_parameter_snapshot(),
    )


__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "DEMO_VIRTUAL_LAB_PROFILE",
    "EXAMPLE_ROOT",
    "quantum_lab_bootstrap_config",
]
