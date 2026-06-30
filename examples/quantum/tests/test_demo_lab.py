from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from quantum_lab_demo import (
    run_readout_frequency_workflow,
    run_readout_iq_workflow,
    run_sample_native_experiments,
)

EXAMPLE_ROOT = Path(__file__).parents[1]
SCRIPTS_DIR = EXAMPLE_ROOT / "scripts"
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"


def _load_script(name: str) -> ModuleType:
    return _load_script_path(SCRIPTS_DIR / f"{name}.py")


def _load_notebook_example(name: str) -> ModuleType:
    return _load_script_path(NOTEBOOKS_DIR / name)


def _load_script_path(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"quantum_lab_demo_script_{path.stem}",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def test_readout_frequency_demo_lab_runs_native_workflow(
    tmp_path: Path,
) -> None:
    result = run_readout_frequency_workflow(workspace=tmp_path)

    assert result.run.manifest.status == "completed"
    assert result.processed_points == 101
    assert result.candidate.guesses
    assert [artifact.kind for artifact in result.run.data().list(kind="analysis")] == [
        "analysis"
    ]


def test_readout_iq_demo_lab_runs_native_workflow(
    tmp_path: Path,
) -> None:
    result = run_readout_iq_workflow(workspace=tmp_path)

    assert result.run.manifest.status == "completed"
    assert result.processed_shots == 240
    assert [artifact.kind for artifact in result.run.data().list(kind="analysis")] == [
        "analysis"
    ]


def test_sample_experiments_demo_lab_runs_native_workflow(
    tmp_path: Path,
) -> None:
    result = run_sample_native_experiments(workspace=tmp_path)

    assert [run.manifest.status for run in result.runs] == ["completed"] * 4
    assert result.template_ids == (
        "quantum_lab_demo.sample.rabi",
        "quantum_lab_demo.sample.readout_frequency",
        "quantum_lab_demo.sample.sqg_rb",
        "quantum_lab_demo.sample.cz_rb",
    )


def test_demo_lab_scripts_return_workflow_results(tmp_path: Path) -> None:
    dry_run_script = _load_script("dry_run")
    readout_frequency = _load_script("readout_frequency")
    readout_iq = _load_script("readout_iq")
    sample_experiments = _load_script("sample_experiments")

    dry_run_result = dry_run_script.run(workspace=tmp_path / "dry-run")

    assert dry_run_result.manifest.runner_id == "scopecat.planner"
    assert "Result intents: signal" in dry_run_script.format_dry_run_summary(
        dry_run_result
    )
    frequency_result = readout_frequency.run(workspace=tmp_path / "readout-frequency")
    iq_result = readout_iq.run(workspace=tmp_path / "readout-iq")
    sample_result = sample_experiments.run(workspace=tmp_path / "sample-experiments")
    assert frequency_result.processed_points == 101
    assert iq_result.processed_shots == 240
    assert [run.manifest.status for run in sample_result.runs] == ["completed"] * 4


def test_notebook_style_examples_execute_user_workflows(tmp_path: Path) -> None:
    open_workspace = _load_notebook_example("01_open_workspace.py")
    define_experiment = _load_notebook_example("02_define_experiment.py")
    run_and_read = _load_notebook_example("03_run_and_read_data.py")
    manual_analysis = _load_notebook_example("04_manual_analysis.py")
    promoted_analysis = _load_notebook_example("05_promote_analysis_step.py")
    review_rerun = _load_notebook_example("06_review_candidate_and_rerun.py")

    open_result = open_workspace.run(workspace=tmp_path / "open")
    define_result = define_experiment.run(workspace=tmp_path / "define")
    run_data_result = run_and_read.run(workspace=tmp_path / "run-data")
    manual_result = manual_analysis.run(workspace=tmp_path / "manual-analysis")
    promoted_result = promoted_analysis.run(workspace=tmp_path / "promoted-analysis")
    review_result = review_rerun.run(workspace=tmp_path / "review-rerun")

    assert open_result.workspace_path == tmp_path / "open"
    assert define_result.template_id == "quantum_lab_demo.readout.frequency_calibration"
    assert define_result.sweep_points == 41
    assert run_data_result.run.manifest.status == "completed"
    assert run_data_result.measurement_count == 101
    assert "raw-measurements" in run_data_result.artifact_ids
    assert manual_result.baseline.manifest.status == "completed"
    assert manual_result.follow_up.manifest.status == "completed"
    assert manual_result.saved_analysis.source_artifact_ids == ("raw-measurements",)
    assert manual_result.review.candidate_config_artifact.kind == "candidate_config"
    assert promoted_result.run.manifest.status == "completed"
    assert promoted_result.saved_analysis.artifact.kind == "analysis"
    assert promoted_result.candidate.guesses[0].parameter_id == "readout_frequency"
    assert promoted_result.overview.overview.run_id == promoted_result.run.id
    assert "Scopecat Run Overview" in promoted_result.overview.markdown
    assert review_result.baseline.manifest.status == "completed"
    assert review_result.follow_up.manifest.status == "completed"
    assert review_result.comparison.result.baseline_run_id == review_result.baseline.id
    assert (
        review_result.comparison.result.candidate_run_id == review_result.follow_up.id
    )
