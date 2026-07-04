from __future__ import annotations

from pathlib import Path

from scopecat.workflows.runs import preview_experiment, start_run
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_config, load_experiment


def test_preview_and_start_run_use_separate_paths(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_experiment()

    preview = preview_experiment(
        config=config,
        experiment=experiment,
        workspace=tmp_path / "preview",
    )
    provider_run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=tmp_path / "provider",
    )

    assert preview.plan.points[0].point_id == 0
    assert len(preview.plan.points) == 3
    assert provider_run.status == "completed"
    assert {dataset.id for dataset in provider_run.datasets} == {"raw-measurements"}
