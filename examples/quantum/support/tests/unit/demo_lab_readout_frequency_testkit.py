from __future__ import annotations

from demo_lab_records import read_model
from demo_lab_test_paths import (
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_RESPONSE_FIXTURE,
)
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile

from quantum_lab_demo.readout.frequency_adapter import (
    ReadoutFrequencyCalibrationAdapter,
)
from quantum_lab_demo.readout.responses import load_readout_response_model


def config_profile_snapshot() -> ConfigProfileSnapshot:
    return load_config_profile(READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json")


def readout_frequency_experiment() -> ExperimentSpec:
    return read_model(
        READOUT_FREQUENCY_FIXTURE_DIR / "experiment.json",
        ExperimentSpec,
    )


def readout_frequency_adapter() -> ReadoutFrequencyCalibrationAdapter:
    return ReadoutFrequencyCalibrationAdapter(
        response_model=load_readout_response_model(READOUT_FREQUENCY_RESPONSE_FIXTURE)
    )
