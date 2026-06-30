"""Closed-loop routine workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from scopecat.authoring import resolve_experiment_with_config
from scopecat.experiments import ExperimentSpec
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.workflows._types import (
    CalibrationRoutine,
    CalibrationRoutineResult,
    ConfigSourceResult,
    EvaluateRunResult,
    ProcessRunResult,
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunDetails,
    RunMeasurementDatasetResult,
    StartRunResult,
)
from scopecat.workflows.runs import (
    list_run_artifacts,
    load_run,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_data_array,
    read_run_data_table,
    read_run_measurement_dataset,
)
from scopecat.workflows.steps import evaluate_run, process_run


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
    review = None
    active_config: ConfigSourceResult | None = None
    if routine.review_candidate is not None and candidate is not None:
        review = candidate.review(
            workspace=workspace,
            reviewer=routine.review_candidate.reviewer,
            note=routine.review_candidate.note,
        )
        active_config = ConfigSourceResult(config=review.config)
    return CalibrationRoutineResult(
        routine_id=routine.id,
        run=run,
        analyses=analyses,
        candidate=candidate,
        review=review,
        active_config=active_config,
    )


@dataclass(frozen=True)
class _RoutineSession:
    workspace: Path
    client: _RoutineClient


@dataclass(frozen=True)
class _RoutineClient:
    workspace: Path

    def process(self, run_id: str, step: Any) -> ProcessRunResult[Any]:
        return process_run(run_id=run_id, workspace=self.workspace, step=step)

    def evaluate(self, run_id: str, step: Any) -> EvaluateRunResult[Any, Any]:
        return evaluate_run(run_id=run_id, workspace=self.workspace, step=step)

    def artifacts(self, run_id: str) -> tuple[str, ...]:
        return tuple(
            artifact.artifact.id
            for artifact in list_run_artifacts(run_id=run_id, workspace=self.workspace)
        )

    def measurements(
        self, run_id: str, *, selector: str = "raw-measurements"
    ) -> RunMeasurementDatasetResult:
        return read_run_measurement_dataset(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return read_run_artifact_text(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return read_run_artifact_json(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def data_table(self, run_id: str, selector: str) -> RunDataTableResult:
        return read_run_data_table(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
        )

    def data_array(self, run_id: str, selector: str) -> RunDataArrayResult:
        return read_run_data_array(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        return read_run_artifact_bytes(
            run_id=run_id,
            workspace=self.workspace,
            selector=selector,
            expected_kind=expected_kind,
        )

    def run_details(self, run_id: str) -> RunDetails:
        return load_run(run_id=run_id, workspace=self.workspace)


def _routine_run_handle(
    *,
    run: StartRunResult,
    workspace: str | Path,
) -> Any:
    from scopecat.session_run_handle import RunHandle

    selected_workspace = Path(workspace)
    session = _RoutineSession(
        workspace=selected_workspace,
        client=_RoutineClient(workspace=selected_workspace),
    )
    return RunHandle(session=cast(Any, session), result=run)


def _candidate_from_analyses(analyses: tuple[Any, ...]) -> Any | None:
    for analysis in analyses:
        if analysis.parameter_guesses:
            return analysis.candidate_config(
                reason=analysis.parameter_guesses[0].reason
            )
    return None
