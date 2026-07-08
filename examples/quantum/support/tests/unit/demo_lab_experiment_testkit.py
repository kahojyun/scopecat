from __future__ import annotations

from demo_lab_test_paths import EXPERIMENT_FIXTURE_DIR
from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot


def load_experiment_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")
