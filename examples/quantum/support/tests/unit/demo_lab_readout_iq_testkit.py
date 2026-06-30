from __future__ import annotations

from pathlib import Path

from demo_lab_test_paths import (
    READOUT_IQ_FIXTURE_DIR,
    READOUT_IQ_RESPONSE_FIXTURE,
)
from scopecat.experiments import acquire, experiment, point
from scopecat.models.config import load_config_profile
from scopecat.relations import grid, range_values
from scopecat.runner import execute_runner_adapter
from scopecat.runs import open_run_store, require_artifact

from quantum_lab_demo.readout.iq_scatter import ReadoutIQScatterAdapter
from quantum_lab_demo.readout.responses import load_readout_iq_response_model


def create_readout_iq_run(tmp_path: Path) -> str:
    config = load_config_profile(READOUT_IQ_FIXTURE_DIR / "config-profile.json")
    manifest, _snapshot = execute_runner_adapter(
        config=config,
        experiment=readout_iq_experiment(),
        adapter=ReadoutIQScatterAdapter(
            response_model=load_readout_iq_response_model(READOUT_IQ_RESPONSE_FIXTURE)
        ),
        workspace=tmp_path,
    )
    return manifest.run_id


def readout_iq_experiment():
    return experiment(
        id="readout-iq-quality",
        kind="readout_iq_quality",
        points=grid(
            shot_index=range_values(
                0,
                239,
                1,
                unit="count",
                include_stop=True,
            )
        ),
        acquire=acquire(
            "iq",
            observations=[
                point("i0", unit="ratio"),
                point("q0", unit="ratio"),
                point("i1", unit="ratio"),
                point("q1", unit="ratio"),
            ],
        ),
    )


def artifact_path(tmp_path: Path, run_id: str, selector: str) -> Path:
    storage = open_run_store(tmp_path)
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
    )
    return storage.ref_path(run_id, artifact.path)
