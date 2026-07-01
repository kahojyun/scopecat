"""Closed-loop routine workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from scopecat.authoring import resolve_experiment_with_config
from scopecat.candidate_configs import resolve_candidate_config
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.workflows._types import (
    CalibrationRoutine,
    CalibrationRoutineResult,
    ConfigSourceResult,
    StartRunResult,
)
from scopecat.workflows.config import register_and_activate_candidate_config


def run_calibration_routine(
    *,
    routine: CalibrationRoutine,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
) -> CalibrationRoutineResult:
    resolved_experiment = None
    experiment = routine.experiment
    if not isinstance(experiment, ExperimentSpec):
        resolved_experiment = resolve_experiment_with_config(
            experiment,
            config=config,
            workspace=workspace,
        )
        experiment = resolved_experiment.experiment
    run = routine.run_executor.start(
        config=config,
        experiment=experiment,
        workspace=workspace,
    )
    if resolved_experiment is not None and (
        run.resolved_experiment is None or run.resolved_experiment.template_id is None
    ):
        run = StartRunResult(
            manifest=run.manifest,
            snapshot=run.snapshot,
            data_ref=run.data_ref,
            resolved_experiment=resolved_experiment,
        )
    run_handle = _routine_run_handle(run=run, workspace=workspace)
    analyses = tuple(run_handle.analyze(step) for step in routine.analysis_steps)
    for analysis in analyses:
        analysis.save()
    candidate = _candidate_from_analyses(analyses)
    activation = None
    active_config: ConfigSourceResult | None = None
    if routine.activate_candidate is not None and candidate is not None:
        resolved_candidate = resolve_candidate_config(candidate, workspace=workspace)
        activation = register_and_activate_candidate_config(
            candidate=resolved_candidate,
            workspace=workspace,
            entry_id=routine.activate_candidate.entry_id or f"{routine.id}-candidate",
            registered_by=(
                routine.activate_candidate.registered_by
                or routine.activate_candidate.operator
            ),
            operator=routine.activate_candidate.operator,
            note=routine.activate_candidate.note,
        )
        active_config = ConfigSourceResult(config=resolved_candidate.config)
    return CalibrationRoutineResult(
        routine_id=routine.id,
        run=run,
        analyses=analyses,
        candidate=candidate,
        activation=activation,
        active_config=active_config,
    )


@dataclass(frozen=True)
class _RoutineSession:
    workspace: Path
    reviewer: str = "operator"
    operator: str = "operator"


def _routine_run_handle(
    *,
    run: StartRunResult,
    workspace: str | Path,
) -> Any:
    from scopecat.session_run_handle import RunHandle

    session = _RoutineSession(workspace=Path(workspace))
    return RunHandle(session=cast(Any, session), result=run)


def _candidate_from_analyses(analyses: tuple[Any, ...]) -> Any | None:
    for analysis in analyses:
        if analysis.parameter_changes:
            return analysis.candidate_config()
    return None
