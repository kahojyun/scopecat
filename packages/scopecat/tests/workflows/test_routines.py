from __future__ import annotations

from pathlib import Path

from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.workflows._types import (
    CalibrationRoutine,
    CandidateReviewPolicy,
    StartRunResult,
)
from scopecat.workflows.routines import run_calibration_routine
from scopecat.workflows.runs import callable_run_executor, run_mode_executor, start_run
from tests.support.native_signal import TestSignalInstrumentProvider
from tests.support.signal_testkit import TestSignalAnalysisStep
from tests.support.workflow_fixtures import load_config, load_experiment


def test_calibration_routine_runs_experiment_spec(tmp_path: Path) -> None:
    routine = CalibrationRoutine(
        id="kernel-demo",
        experiment=load_experiment(),
        run_executor=run_mode_executor("dry"),
    )

    result = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )

    assert result.routine_id == "kernel-demo"
    assert result.run.manifest.runner_id == "scopecat.planner"
    assert result.run.resolved_experiment is None


def test_calibration_routine_runs_native_analysis_closed_loop(
    tmp_path: Path,
) -> None:
    routine = CalibrationRoutine(
        id="kernel-best-signal",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate",
            native_instrument_provider=TestSignalInstrumentProvider(),
        ),
        analysis_steps=(TestSignalAnalysisStep(),),
        review_candidate=CandidateReviewPolicy(reviewer="operator"),
    )

    result = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )
    assert result.active_config is not None
    followup = start_run(
        mode="native_simulate",
        native_instrument_provider=TestSignalInstrumentProvider(),
        config=result.active_config.config,
        experiment=load_experiment(),
        workspace=tmp_path,
    )

    assert result.run.manifest.runner_id == "scopecat.native"
    assert result.analyses[0].parameter_proposals[0].parameter_id == "drive_frequency"
    assert result.review is not None
    assert followup.manifest.status == "completed"


def test_calibration_routine_without_review_leaves_active_config_empty(
    tmp_path: Path,
) -> None:
    routine = CalibrationRoutine(
        id="demo-no-accept",
        experiment=load_experiment(),
        run_executor=run_mode_executor(
            "native_simulate",
            native_instrument_provider=TestSignalInstrumentProvider(),
        ),
        analysis_steps=(TestSignalAnalysisStep(),),
    )

    result = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )

    assert result.analyses[0].parameter_proposals[0].parameter_id == "drive_frequency"
    assert result.review is None
    assert result.active_config is None


def test_callable_run_executor_wraps_custom_start_function(tmp_path: Path) -> None:
    calls: list[str] = []

    def start_custom(
        *,
        config: ConfigProfileSnapshot,
        experiment: object,
        workspace: str | Path,
    ) -> StartRunResult:
        assert isinstance(experiment, ExperimentSpec)
        calls.append(experiment.id)
        return start_run(
            mode="dry",
            config=config,
            experiment=experiment,
            workspace=workspace,
        )

    routine = CalibrationRoutine(
        id="callable-demo",
        experiment=load_experiment(),
        run_executor=callable_run_executor("custom-dry", start_custom),
    )

    result = run_calibration_routine(
        routine=routine,
        config=load_config(),
        workspace=tmp_path,
    )

    assert routine.run_executor.id == "custom-dry"
    assert calls == [load_experiment().id]
    assert result.run.manifest.runner_id == "scopecat.planner"
