from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from quantum_lab_demo import (
    NOTEBOOK_WORKSPACE_ROOT_ENV,
    run_readout_frequency_workflow,
    run_readout_iq_workflow,
    run_sample_native_experiments,
)

EXAMPLE_ROOT = Path(__file__).parents[1]
SCRIPTS_DIR = EXAMPLE_ROOT / "scripts"
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"


def _load_script(name: str) -> ModuleType:
    return _load_script_path(SCRIPTS_DIR / f"{name}.py")


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


def test_notebook_style_examples_execute_user_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(NOTEBOOK_WORKSPACE_ROOT_ENV, str(tmp_path))

    open_workspace = _run_notebook("01_open_workspace.py")
    define_experiment = _run_notebook("02_define_experiment.py")
    run_and_read = _run_notebook("03_run_and_read_data.py")
    manual_analysis = _run_notebook("04_manual_analysis.py")
    promoted_analysis = _run_notebook("05_promote_analysis_step.py")
    review_rerun = _run_notebook("06_review_candidate_and_rerun.py")

    assert open_workspace["workspace"] == tmp_path / "notebooks" / "01-open-workspace"
    assert open_workspace["lab"].workspace == open_workspace["workspace"]
    assert (
        define_experiment["source"].template_id
        == "quantum_lab_demo.readout.frequency_calibration"
    )
    assert define_experiment["sweep_points"] == 41
    assert run_and_read["completed_run"].manifest.status == "completed"
    assert len(run_and_read["raw"].dataset.records) == 101
    assert "raw-measurements" in [artifact.id for artifact in run_and_read["artifacts"]]
    assert manual_analysis["baseline"].manifest.status == "completed"
    assert manual_analysis["follow_up"].manifest.status == "completed"
    assert manual_analysis["saved_analysis"].source_artifact_ids == (
        "raw-measurements",
    )
    assert manual_analysis["review"].candidate_config_artifact.kind == (
        "candidate_config"
    )
    assert promoted_analysis["completed_run"].manifest.status == "completed"
    assert promoted_analysis["saved_analysis"].artifact.kind == "analysis"
    assert promoted_analysis["candidate"].guesses[0].parameter_id == "readout_frequency"
    assert (
        promoted_analysis["overview"].overview.run_id
        == promoted_analysis["completed_run"].id
    )
    assert "Scopecat Run Overview" in promoted_analysis["overview"].markdown
    assert review_rerun["baseline"].manifest.status == "completed"
    assert review_rerun["follow_up"].manifest.status == "completed"
    assert (
        review_rerun["comparison"].result.baseline_run_id == review_rerun["baseline"].id
    )
    assert (
        review_rerun["comparison"].result.candidate_run_id
        == review_rerun["follow_up"].id
    )


def _run_notebook(name: str) -> dict[str, Any]:
    return runpy.run_path(str(NOTEBOOKS_DIR / name))
