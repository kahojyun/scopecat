"""Paths and version-controlled bootstrap config for the reference lab."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scopecat.records.config import (
    ConfigProfileSnapshot,
    SystemSpec,
    snapshot_config_profile,
)

from reference_lab.parameters import (
    REFERENCE_PARAMETER_CATALOG,
    reference_lab_parameter_snapshot,
)

EXAMPLE_ROOT = Path(__file__).resolve().parents[2]
DEMO_CONFIG_DIR = EXAMPLE_ROOT / "config"
DAEMON_URL_ENV = "SCOPECAT_DAEMON_URL"


def bootstrap_config(
    config_dir: str | Path = DEMO_CONFIG_DIR,
) -> ConfigProfileSnapshot:
    """Combine infrastructure with the Python-owned parameter system."""

    root = Path(config_dir)
    document = cast(
        "dict[str, object]",
        json.loads((root / "system-infrastructure.json").read_text(encoding="utf-8")),
    )
    document["parameter_catalog"] = REFERENCE_PARAMETER_CATALOG
    system = SystemSpec.model_validate(document)
    return snapshot_config_profile(
        profile_id="reference-lab-profile",
        system=system,
        parameter_snapshot=reference_lab_parameter_snapshot(),
    )


__all__ = [
    "DAEMON_URL_ENV",
    "DEMO_CONFIG_DIR",
    "EXAMPLE_ROOT",
    "bootstrap_config",
]
