from __future__ import annotations

from pathlib import Path

from scopecat.workflows.runs import start_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_config, load_experiment


def test_start_run_dispatches_dry_and_native_modes(tmp_path: Path) -> None:
    config = load_config()
    experiment = load_experiment()

    dry = start_run(
        mode="dry",
        config=config,
        experiment=experiment,
        workspace=tmp_path / "dry",
    )
    native = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=tmp_path / "native",
    )

    assert dry.manifest.runner_id == "scopecat.planner"
    assert dry.snapshot.point_count == 3
    assert native.manifest.runner_id == "scopecat.native"
    assert native.data_ref == "artifacts/raw-measurements.jsonl"
