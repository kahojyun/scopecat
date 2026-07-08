from __future__ import annotations

from pathlib import Path

from scopecat._workflows.runs import preview_experiment, start_run
from tests.support.authoring import SIMPLE_MODULE
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

    assert preview.points[0].point_index == 0
    assert preview.point_count == 3
    assert provider_run.status == "completed"
    assert {dataset.id for dataset in provider_run.datasets} == {"raw-measurements"}


def test_preview_and_start_run_accept_template_invocation(tmp_path: Path) -> None:
    config = load_config()
    experiment_template = SIMPLE_MODULE.template(
        id="test.workflow_request_scan",
        experiment_id="authored-simple-scan",
        kind="simple_scan",
    )
    invocation = experiment_template(subject="q0")

    preview = preview_experiment(
        config=config,
        experiment=invocation,
        workspace=tmp_path / "preview",
    )
    provider_run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=invocation,
        workspace=tmp_path / "provider",
    )

    assert preview.template_id == "test.workflow_request_scan"
    assert preview.inputs == {"subject": "q0"}
    assert preview.experiment_id == "authored-simple-scan"
    assert provider_run.status == "completed"
