from __future__ import annotations

from demo_lab_test_paths import (
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
)
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile

from quantum_lab_demo.virtual_lab.provider import ReadoutFrequencyVirtualProvider


def config_profile_snapshot() -> ConfigProfileSnapshot:
    return load_config_profile(READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json")


def readout_frequency_experiment() -> ExperimentSpec:
    return ExperimentSpec.model_validate_json(
        (READOUT_FREQUENCY_FIXTURE_DIR / "experiment.json").read_text()
    )


def readout_frequency_provider() -> ReadoutFrequencyVirtualProvider:
    return ReadoutFrequencyVirtualProvider(
        profile=READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE
    )
