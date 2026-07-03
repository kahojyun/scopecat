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
    run_sample_experiments,
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


def test_readout_frequency_demo_lab_runs_provider_workflow(
    tmp_path: Path,
) -> None:
    result = run_readout_frequency_workflow(workspace=tmp_path)

    assert result.run.manifest.status == "completed"
    assert result.processed_points == 101
    assert result.candidate.parameter_changes[0].patches
    assert [artifact.kind for artifact in result.run.data().list(kind="analysis")] == [
        "analysis"
    ]


def test_readout_iq_demo_lab_runs_provider_workflow(
    tmp_path: Path,
) -> None:
    result = run_readout_iq_workflow(workspace=tmp_path)

    assert result.run.manifest.status == "completed"
    assert result.processed_shots == 240
    assert [artifact.kind for artifact in result.run.data().list(kind="analysis")] == [
        "analysis"
    ]


def test_sample_experiments_demo_lab_runs_provider_workflow(
    tmp_path: Path,
) -> None:
    result = run_sample_experiments(workspace=tmp_path)

    assert [run.manifest.status for run in result.runs] == ["completed"] * 4
    assert result.template_ids == (
        "quantum_lab_demo.sample.rabi",
        "quantum_lab_demo.sample.readout_frequency",
        "quantum_lab_demo.sample.sqg_rb",
        "quantum_lab_demo.sample.cz_rb",
    )


def test_demo_lab_scripts_return_workflow_results(tmp_path: Path) -> None:
    preview_script = _load_script("preview")

    preview_result = preview_script.run(workspace=tmp_path / "preview")

    assert len(preview_result.plan.points) == 3
    assert "Result intents: signal" in preview_script.format_preview_summary(
        preview_result
    )


def test_notebook_style_examples_execute_user_workflows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(NOTEBOOK_WORKSPACE_ROOT_ENV, str(tmp_path))

    review_rerun = _run_notebook("06_review_candidate_and_rerun.py")

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
