"""Runner adapter execution orchestration."""

from __future__ import annotations

from pathlib import Path

from scopecat._execution import (
    build_raw_measurement_artifact,
    expected_measurement_indices,
    parse_expected_dataset_schema,
    ref_for_artifact,
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
    write_final_execution_artifacts,
    write_planned_run_inputs,
)
from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
    PlanSnapshot,
    plan_experiment,
)
from scopecat.ids import new_run_id
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionProfile
from scopecat.models.run import RunEvent, RunManifest, RunStatus
from scopecat.planning.validation import (
    has_blocking_diagnostics,
    validate_config,
)
from scopecat.results import (
    MeasurementDatasetSchema,
    MeasurementRecord,
    MeasurementSink,
)
from scopecat.runner.artifact_store import RunnerArtifactStore
from scopecat.runner.constants import (
    RUNNER_ADAPTER_BOUNDARY_MANIFEST_ARTIFACT_ID,
    RUNNER_ADAPTER_BOUNDARY_MANIFEST_FILENAME,
    RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID,
    RUNNER_ADAPTER_RAW_MEASUREMENTS_FILENAME,
    RUNNER_ADAPTER_SNAPSHOT_FILENAME,
    RUNNER_ADAPTER_SUMMARY_FILENAME,
)
from scopecat.runner.sdk import RunnerAdapter, RunnerAdapterResult, RunnerContext
from scopecat.runner.snapshots import (
    RunnerAdapterRunSnapshot,
    build_runner_adapter_boundary_manifest,
    render_runner_adapter_summary,
)


def execute_runner_adapter(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    adapter: RunnerAdapter,
    workspace: str | Path,
) -> tuple[RunManifest, RunnerAdapterRunSnapshot]:
    adapter_diagnostics = _validate_adapter(adapter)
    preflight_diagnostics = validate_config(config) + adapter_diagnostics
    if config.parameter_build is None:
        preflight_diagnostics.append(
            _diagnostic(
                "blocker",
                "missing_parameter_build_snapshot",
                "runner adapter execution requires a parameter build snapshot",
                "parameter_build",
            )
        )
    if has_blocking_diagnostics(preflight_diagnostics):
        raise ValidationFailed(preflight_diagnostics)
    assert config.parameter_build is not None
    plan = plan_experiment(experiment, config.parameter_build)
    return _execute_runner_plan(
        config=config,
        experiment=experiment,
        adapter=adapter,
        workspace=workspace,
        plan=plan,
        preflight_diagnostics=preflight_diagnostics,
    )


def _execute_runner_plan(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    adapter: RunnerAdapter,
    workspace: str | Path,
    plan: PlanSnapshot,
    preflight_diagnostics: list[Diagnostic],
) -> tuple[RunManifest, RunnerAdapterRunSnapshot]:
    workspace_path = Path(workspace)
    execution = ExecutionProfile(runner_id=adapter.adapter_id)
    run_id = new_run_id()
    storage = LocalRunStore(workspace_path)
    artifacts_dir = storage.layout.artifacts_dir(run_id)
    artifact_store = RunnerArtifactStore(artifacts_dir=artifacts_dir)
    summary_ref = ref_for_artifact(RUNNER_ADAPTER_SUMMARY_FILENAME)
    snapshot_ref = ref_for_artifact(RUNNER_ADAPTER_SNAPSHOT_FILENAME)
    boundary_ref = ref_for_artifact(RUNNER_ADAPTER_BOUNDARY_MANIFEST_FILENAME)
    data_ref = ref_for_artifact(RUNNER_ADAPTER_RAW_MEASUREMENTS_FILENAME)
    adapter_id = adapter.adapter_id
    adapter_version = adapter.adapter_version
    expected_schema, schema_diagnostics = parse_expected_dataset_schema(plan)
    raw_measurement_schema = _raw_measurement_schema(expected_schema)
    diagnostics = preflight_diagnostics + _plan_diagnostics(plan) + schema_diagnostics
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)

    planned_manifest = _manifest(
        config=config,
        experiment_id=experiment.id,
        execution=execution,
        run_id=run_id,
        status="planned",
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        summary_ref=summary_ref,
        snapshot_ref=snapshot_ref,
        boundary_ref=boundary_ref,
        data_ref=data_ref,
        adapter_artifacts=[],
        measurements=[],
        expected_schema=raw_measurement_schema,
        finalization_summary="Runner adapter planned.",
    )
    write_planned_run_inputs(
        storage=storage,
        manifest=planned_manifest,
        config=config,
        plan=plan,
    )

    sink = MeasurementSink(run_id=run_id)
    context = RunnerContext(
        run_id=run_id,
        config=config,
        experiment=experiment,
        execution=execution,
        plan=plan,
        artifacts=artifact_store,
    )
    events = [
        RunEvent(
            event_type="runner_adapter_started",
            message="Runner adapter started.",
            metadata={"adapter_id": adapter_id},
        )
    ]
    result = RunnerAdapterResult()
    adapter_run_diagnostics: list[Diagnostic] = []
    try:
        result = adapter.run(context, sink)
    except Exception as error:
        adapter_run_diagnostics.append(
            _diagnostic(
                "error",
                "runner_adapter_failed",
                f"runner adapter failed: {type(error).__name__}: {error}",
                "adapter",
            )
        )

    measurements = list(sink.measurements)
    adapter_artifacts = list(artifact_store.artifacts)
    artifact_diagnostics = list(artifact_store.diagnostics)
    measurement_diagnostics = validate_measurement_index_shape(
        measurements=measurements,
        expected_indices=expected_measurement_indices(plan),
        duplicate_code="runner_adapter_duplicate_point",
        duplicate_message="runner adapter recorded duplicate point",
        unknown_code="runner_adapter_unknown_point",
        unknown_message="runner adapter recorded unknown point",
        missing_observables_code="runner_adapter_missing_observables",
        missing_observables_message="runner adapter measurement has no observables",
    )
    dataset_contract_diagnostics = validate_raw_measurement_dataset(
        records=measurements,
        expected_schema=raw_measurement_schema,
        dataset_id=RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID,
    )
    diagnostics = [
        *diagnostics,
        *dataset_contract_diagnostics,
        *measurement_diagnostics,
        *result.diagnostics,
        *artifact_diagnostics,
        *adapter_run_diagnostics,
    ]
    success = not has_blocking_diagnostics(diagnostics)
    status: RunStatus = "completed" if success else "failed"
    final_manifest = _manifest(
        config=config,
        experiment_id=experiment.id,
        execution=execution,
        run_id=run_id,
        status=status,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        summary_ref=summary_ref,
        snapshot_ref=snapshot_ref,
        boundary_ref=boundary_ref,
        data_ref=data_ref,
        adapter_artifacts=adapter_artifacts,
        measurements=measurements,
        expected_schema=raw_measurement_schema,
        finalization_summary=(
            "Runner adapter completed." if success else "Runner adapter failed."
        ),
    )
    snapshot = RunnerAdapterRunSnapshot(
        run_id=run_id,
        experiment_id=experiment.id,
        runner_id=execution.runner_id,
        dry_run=execution.dry_run,
        status=status,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        point_count=_point_count(plan),
        measurement_count=len(measurements),
        data_ref=data_ref,
        diagnostics=diagnostics,
        metadata=result.metadata,
        plan=plan,
    )
    events.extend(result.events)
    events.extend(
        RunEvent(
            event_type="runner_adapter_measurement_recorded",
            message=f"Recorded runner adapter measurement {measurement.point_index}.",
            metadata={"point_index": measurement.point_index},
        )
        for measurement in measurements
    )
    events.append(
        RunEvent(
            severity="info" if success else "error",
            event_type=(
                "runner_adapter_completed" if success else "runner_adapter_failed"
            ),
            message=(
                "Runner adapter completed." if success else "Runner adapter failed."
            ),
            metadata={"measurement_count": len(measurements)},
        )
    )
    summary = render_runner_adapter_summary(
        manifest=final_manifest,
        snapshot=snapshot,
    )
    boundary_manifest = build_runner_adapter_boundary_manifest(
        manifest=final_manifest,
        snapshot=snapshot,
        plan=plan,
        adapter_artifacts=adapter_artifacts,
        event_count=len(events),
    )
    write_final_execution_artifacts(
        storage=storage,
        manifest=final_manifest,
        snapshot_ref=snapshot_ref,
        snapshot=snapshot,
        summary_ref=summary_ref,
        summary=summary,
        data_ref=data_ref,
        measurements=measurements,
        events=events,
    )
    storage.write_model(run_id, boundary_ref, boundary_manifest)
    if not success:
        raise ValidationFailed(diagnostics)
    return final_manifest, snapshot


def _raw_measurement_schema(
    expected_schema: MeasurementDatasetSchema | None,
) -> MeasurementDatasetSchema | None:
    if expected_schema is None:
        return None
    return expected_schema.model_copy(
        update={"dataset_id": RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID}
    )


def _plan_diagnostics(plan: PlanSnapshot) -> list[Diagnostic]:
    return [Diagnostic.model_validate(diagnostic) for diagnostic in plan.diagnostics]


def _point_count(plan: PlanSnapshot) -> int:
    return len(plan.points)


def _manifest(
    *,
    config: ConfigProfileSnapshot,
    experiment_id: str,
    execution: ExecutionProfile,
    run_id: str,
    status: RunStatus,
    adapter_id: str,
    adapter_version: str,
    summary_ref: str,
    snapshot_ref: str,
    boundary_ref: str,
    data_ref: str,
    adapter_artifacts: list[Artifact],
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
    finalization_summary: str,
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        status=status,
        runner_id=execution.runner_id,
        dry_run=execution.dry_run,
        workspace_ref=config.workspace_id,
        device_ref=config.device_under_test_id,
        experiment_ref=experiment_id,
        config_profile_snapshot_ref="config-profile.snapshot.json",
        plan_snapshot_ref="plan.snapshot.json",
        runner_versions={adapter_id: adapter_version},
        events_ref="events.jsonl",
        artifact_refs=_artifact_refs(
            summary_ref=summary_ref,
            snapshot_ref=snapshot_ref,
            boundary_ref=boundary_ref,
            data_ref=data_ref,
            adapter_artifacts=adapter_artifacts,
            measurements=measurements,
            expected_schema=expected_schema,
        ),
        finalization_summary=finalization_summary,
    )


def _artifact_refs(
    *,
    summary_ref: str,
    snapshot_ref: str,
    boundary_ref: str,
    data_ref: str,
    adapter_artifacts: list[Artifact],
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
) -> list[Artifact]:
    return [
        Artifact(
            id="runner-adapter-summary",
            kind="summary",
            path=summary_ref,
            media_type="text/markdown",
        ),
        Artifact(
            id="runner-adapter-snapshot",
            kind="runner_adapter_run_snapshot",
            path=snapshot_ref,
            media_type="application/json",
        ),
        Artifact(
            id=RUNNER_ADAPTER_BOUNDARY_MANIFEST_ARTIFACT_ID,
            kind="runner_adapter_boundary_manifest",
            path=boundary_ref,
            media_type="application/json",
        ),
        build_raw_measurement_artifact(
            artifact_id=RUNNER_ADAPTER_RAW_MEASUREMENTS_ARTIFACT_ID,
            ref=data_ref,
            records=measurements,
            expected_schema=expected_schema,
        ),
        *adapter_artifacts,
    ]


def _validate_adapter(adapter: RunnerAdapter) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not adapter.adapter_id:
        diagnostics.append(
            _diagnostic(
                "error",
                "runner_adapter_missing_id",
                "runner adapter_id must be non-empty",
                "adapter.adapter_id",
            )
        )
    if not adapter.adapter_version:
        diagnostics.append(
            _diagnostic(
                "error",
                "runner_adapter_missing_version",
                "runner adapter_version must be non-empty",
                "adapter.adapter_version",
            )
        )
    return diagnostics


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
