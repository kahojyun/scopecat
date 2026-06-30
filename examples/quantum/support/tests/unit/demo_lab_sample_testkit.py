from __future__ import annotations

from demo_lab_test_paths import SAMPLE_TEMPLATES_FIXTURE_DIR
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.parameter import ParameterBuildSnapshot


def load_sample_config() -> ConfigProfileSnapshot:
    return load_config_profile(SAMPLE_TEMPLATES_FIXTURE_DIR / "config-profile.json")


def sample_parameter_build() -> ParameterBuildSnapshot:
    parameter_build = load_sample_config().parameter_build
    assert parameter_build is not None
    return parameter_build
