from __future__ import annotations

from pathlib import Path

from demo_lab_test_paths import (
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_RESPONSE_FIXTURE,
)
from scopecat.experiments import acquire, experiment, point
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.relations import grid, linspace
from scopecat.runner import execute_runner_adapter
from scopecat.runs import open_run_store, require_artifact

from quantum_lab_demo.readout.frequency_adapter import (
    ReadoutFrequencyCalibrationAdapter,
)
from quantum_lab_demo.readout.frequency_processing import (
    execute_readout_frequency_processing,
)
from quantum_lab_demo.readout.responses import load_readout_response_model


def config_profile_snapshot() -> ConfigProfileSnapshot:
    return load_config_profile(READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json")


def readout_frequency_adapter() -> ReadoutFrequencyCalibrationAdapter:
    return ReadoutFrequencyCalibrationAdapter(
        response_model=load_readout_response_model(READOUT_FREQUENCY_RESPONSE_FIXTURE)
    )


def readout_frequency_experiment():
    return experiment(
        id="readout-frequency-calibration",
        kind="readout_frequency_calibration",
        points=grid(
            readout_frequency=linspace(5.90, 6.00, 101, unit="GHz"),
        ),
        acquire=acquire(
            "scalar",
            observations=[
                point("raw_i", unit="ratio"),
                point("raw_q", unit="ratio"),
            ],
        ),
    )


def create_processed_readout_run(tmp_path: Path) -> str:
    manifest, _snapshot = execute_runner_adapter(
        config=config_profile_snapshot(),
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )
    execute_readout_frequency_processing(
        run_id=manifest.run_id,
        workspace=tmp_path,
    )
    return manifest.run_id


def artifact_path(tmp_path: Path, run_id: str, selector: str) -> Path:
    storage = open_run_store(tmp_path)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
    )
    return storage.ref_path(run_id, artifact.path)
