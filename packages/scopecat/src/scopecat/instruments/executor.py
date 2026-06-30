"""Native instrument execution orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

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
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentStateSnapshot,
    NativeAcquisitionContext,
    NativeInstrument,
)
from scopecat.instruments.snapshots import (
    NativePointSnapshot,
    NativeRunSnapshot,
    build_native_boundary_manifest,
    render_native_run_summary,
)
from scopecat.instruments.state import (
    AcquisitionPlan,
    DesiredResourceState,
    DesiredStateField,
    ExecutionPoint,
    StateValue,
)
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionProfile
from scopecat.models.parameter import Quantity
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

NATIVE_RUNNER_ID = "scopecat.native"
NATIVE_RUN_SUMMARY_FILENAME = "native-run.summary.md"
NATIVE_RUN_SNAPSHOT_FILENAME = "native-run.snapshot.json"
NATIVE_BOUNDARY_MANIFEST_FILENAME = "native-run.boundary.json"
NATIVE_BOUNDARY_MANIFEST_ARTIFACT_ID = "native-run-boundary"
NATIVE_RAW_MEASUREMENTS_FILENAME = "raw-measurements.jsonl"
NATIVE_RAW_MEASUREMENTS_ARTIFACT_ID = "raw-measurements"


def execute_native_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    instruments: list[NativeInstrument],
    workspace: str | Path,
) -> tuple[RunManifest, NativeRunSnapshot]:
    preflight_diagnostics = validate_config(config) + _validate_native_instruments(
        config=config,
        instruments=instruments,
    )
    if config.parameter_build is None:
        preflight_diagnostics.append(
            _diagnostic(
                "blocker",
                "missing_parameter_build_snapshot",
                "native execution requires a parameter build snapshot",
                "parameter_build",
            )
        )
    if has_blocking_diagnostics(preflight_diagnostics):
        raise ValidationFailed(preflight_diagnostics)
    assert config.parameter_build is not None
    plan = plan_experiment(experiment, config.parameter_build)
    return _execute_native_plan(
        config=config,
        experiment_id=experiment.id,
        instruments=instruments,
        workspace=workspace,
        plan=plan,
        preflight_diagnostics=preflight_diagnostics,
    )


def _execute_native_plan(
    *,
    config: ConfigProfileSnapshot,
    experiment_id: str,
    instruments: list[NativeInstrument],
    workspace: str | Path,
    plan: PlanSnapshot,
    preflight_diagnostics: list[Diagnostic],
) -> tuple[RunManifest, NativeRunSnapshot]:
    workspace_path = Path(workspace)
    instruments_by_id = {
        instrument.instrument_id: instrument for instrument in instruments
    }
    execution = ExecutionProfile(runner_id=NATIVE_RUNNER_ID)
    run_id = new_run_id()
    storage = LocalRunStore(workspace_path)
    summary_ref = ref_for_artifact(NATIVE_RUN_SUMMARY_FILENAME)
    snapshot_ref = ref_for_artifact(NATIVE_RUN_SNAPSHOT_FILENAME)
    boundary_ref = ref_for_artifact(NATIVE_BOUNDARY_MANIFEST_FILENAME)
    data_ref = ref_for_artifact(NATIVE_RAW_MEASUREMENTS_FILENAME)
    descriptions, description_diagnostics = _describe_instruments(instruments)
    expected_schema, schema_diagnostics = parse_expected_dataset_schema(plan)
    raw_measurement_schema = _raw_measurement_schema(expected_schema)
    diagnostics = (
        preflight_diagnostics
        + description_diagnostics
        + schema_diagnostics
        + _validate_plan_instruments(
            plan=plan,
            instruments_by_id=instruments_by_id,
            descriptions=descriptions,
        )
    )
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)

    planned_manifest = _manifest(
        config=config,
        experiment_id=experiment_id,
        execution=execution,
        run_id=run_id,
        status="planned",
        summary_ref=summary_ref,
        snapshot_ref=snapshot_ref,
        boundary_ref=boundary_ref,
        data_ref=data_ref,
        instruments=instruments,
        measurements=[],
        expected_schema=raw_measurement_schema,
        finalization_summary="Native run planned.",
    )
    write_planned_run_inputs(
        storage=storage,
        manifest=planned_manifest,
        config=config,
        plan=plan,
    )

    sink = MeasurementSink(run_id=run_id)
    initial_state: list[InstrumentStateSnapshot] = []
    final_state: list[InstrumentStateSnapshot] = []
    point_snapshots: list[NativePointSnapshot] = []
    current_states: dict[str, InstrumentStateSnapshot] = {}
    events = [
        RunEvent(
            event_type="native_run_started",
            message="Native run started.",
            metadata={"instrument_ids": sorted(instruments_by_id)},
        )
    ]
    execution_diagnostics: list[Diagnostic] = []
    result_events: list[RunEvent] = []

    try:
        initial_state = _readback_all(instruments, execution_diagnostics)
        current_states = {state.instrument_id: state for state in initial_state}
        if not has_blocking_diagnostics(execution_diagnostics):
            for point_index in _point_indices(plan):
                desired = _desired_for_point(plan, point_index)
                changed_field_count = _apply_desired_state(
                    desired=desired,
                    current_states=current_states,
                    instruments_by_id=instruments_by_id,
                    diagnostics=execution_diagnostics,
                )
                if has_blocking_diagnostics(execution_diagnostics):
                    break
                before_count = len(sink.measurements)
                acquisition_context = _acquisition_context(
                    run_id=run_id,
                    plan=plan,
                    point_index=point_index,
                    desired=desired,
                )
                for instrument in instruments:
                    try:
                        result = instrument.acquire(acquisition_context, sink)
                    except Exception as error:
                        execution_diagnostics.append(
                            _diagnostic_from_exception(
                                "error",
                                "native_instrument_acquire_failed",
                                "native instrument acquire failed for "
                                f"{instrument.instrument_id}: "
                                f"{type(error).__name__}: {error}",
                                instrument.instrument_id,
                                error,
                            )
                        )
                        continue
                    execution_diagnostics.extend(result.diagnostics)
                    result_events.extend(result.events)
                acquired_count = len(sink.measurements) - before_count
                point_snapshots.append(
                    NativePointSnapshot(
                        point_index=point_index,
                        changed_field_count=changed_field_count,
                        acquired_record_count=acquired_count,
                    )
                )
                if has_blocking_diagnostics(execution_diagnostics):
                    break
        final_state = _readback_all(instruments, execution_diagnostics)
    finally:
        if has_blocking_diagnostics(execution_diagnostics):
            _abort_all(instruments, execution_diagnostics)
        else:
            _cleanup_all(instruments, execution_diagnostics)

    measurements = list(sink.measurements)
    measurement_diagnostics = validate_measurement_index_shape(
        measurements=measurements,
        expected_indices=expected_measurement_indices(plan),
        duplicate_code="native_duplicate_measurement_index",
        duplicate_message="native run recorded duplicate measurement",
        unknown_code="native_unknown_measurement_index",
        unknown_message="native run recorded unknown measurement",
        missing_observables_code="native_missing_observables",
        missing_observables_message="native measurement has no observables",
    )
    dataset_contract_diagnostics = validate_raw_measurement_dataset(
        records=measurements,
        expected_schema=raw_measurement_schema,
        dataset_id=NATIVE_RAW_MEASUREMENTS_ARTIFACT_ID,
    )
    diagnostics = [
        *diagnostics,
        *execution_diagnostics,
        *dataset_contract_diagnostics,
        *measurement_diagnostics,
    ]
    success = not has_blocking_diagnostics(diagnostics)
    status: RunStatus = "completed" if success else "failed"
    final_manifest = _manifest(
        config=config,
        experiment_id=experiment_id,
        execution=execution,
        run_id=run_id,
        status=status,
        summary_ref=summary_ref,
        snapshot_ref=snapshot_ref,
        boundary_ref=boundary_ref,
        data_ref=data_ref,
        instruments=instruments,
        measurements=measurements,
        expected_schema=raw_measurement_schema,
        finalization_summary=(
            "Native run completed." if success else "Native run failed."
        ),
    )
    snapshot = NativeRunSnapshot(
        run_id=run_id,
        experiment_id=experiment_id,
        runner_id=execution.runner_id,
        status=status,
        instrument_ids=sorted(instruments_by_id),
        descriptions=descriptions,
        initial_state=initial_state,
        final_state=final_state,
        point_count=_point_count(plan),
        measurement_count=len(measurements),
        data_ref=data_ref,
        diagnostics=diagnostics,
        points=point_snapshots,
        plan=plan,
    )
    events.extend(result_events)
    events.extend(
        RunEvent(
            event_type="native_measurement_recorded",
            message=f"Recorded native measurement {measurement.point_index}.",
            metadata={"point_index": measurement.point_index},
        )
        for measurement in measurements
    )
    events.append(
        RunEvent(
            severity="info" if success else "error",
            event_type="native_run_completed" if success else "native_run_failed",
            message="Native run completed." if success else "Native run failed.",
            metadata={"measurement_count": len(measurements)},
        )
    )
    summary = render_native_run_summary(manifest=final_manifest, snapshot=snapshot)
    boundary_manifest = build_native_boundary_manifest(
        manifest=final_manifest,
        snapshot=snapshot,
        plan=plan,
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


def _describe_instruments(
    instruments: list[NativeInstrument],
) -> tuple[list[InstrumentDescription], list[Diagnostic]]:
    descriptions: list[InstrumentDescription] = []
    diagnostics: list[Diagnostic] = []
    for instrument in instruments:
        try:
            descriptions.append(instrument.describe())
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_describe_failed",
                    "native instrument describe failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )
    return descriptions, diagnostics


def _raw_measurement_schema(
    expected_schema: MeasurementDatasetSchema | None,
) -> MeasurementDatasetSchema | None:
    if expected_schema is None:
        return None
    return expected_schema.model_copy(
        update={"dataset_id": NATIVE_RAW_MEASUREMENTS_ARTIFACT_ID}
    )


def _validate_native_instruments(
    *, config: ConfigProfileSnapshot, instruments: list[NativeInstrument]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()
    config_instrument_ids = {
        instrument.id for instrument in config.instrument_registry.instruments
    }
    for instrument in instruments:
        if not instrument.instrument_id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_instrument_missing_id",
                    "native instrument_id must be non-empty",
                    "instrument.instrument_id",
                )
            )
            continue
        if instrument.instrument_id in seen:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_instrument_duplicate_id",
                    f"duplicate native instrument id {instrument.instrument_id}",
                    "instrument.instrument_id",
                )
            )
        seen.add(instrument.instrument_id)
        if instrument.instrument_id not in config_instrument_ids:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_instrument_not_in_config",
                    f"native instrument {instrument.instrument_id} is not in config",
                    "instrument.instrument_id",
                )
            )
        if not instrument.implementation_id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_instrument_missing_implementation_id",
                    "native implementation_id must be non-empty",
                    "instrument.implementation_id",
                )
            )
        if not instrument.implementation_version:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_instrument_missing_implementation_version",
                    "native implementation_version must be non-empty",
                    "instrument.implementation_version",
                )
            )
    return diagnostics


def _validate_plan_instruments(
    *,
    plan: PlanSnapshot,
    instruments_by_id: dict[str, NativeInstrument],
    descriptions: list[InstrumentDescription],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    description_by_id = {
        description.instrument_id: description for description in descriptions
    }
    capability_fields_by_resource = {
        description.instrument_id: {
            capability.id: {field.id: field for field in capability.fields}
            for capability in description.capabilities
        }
        for description in descriptions
    }
    desired_points, desired_diagnostics = _desired_points(plan)
    diagnostics.extend(desired_diagnostics)
    if not desired_points:
        return diagnostics
    resource_ids = sorted(
        {
            resource.resource_id
            for resources in desired_points.values()
            for resource in resources
        }
    )
    for resource_id in resource_ids:
        if resource_id not in instruments_by_id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_missing_instrument",
                    f"no native instrument provided for resource {resource_id}",
                    "desired_state_plan.resource_ids",
                )
            )
        elif resource_id not in description_by_id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_missing_instrument_description",
                    f"native instrument {resource_id} did not provide a description",
                    "instruments",
                )
            )
    for resources in desired_points.values():
        for resource in resources:
            capability_fields = capability_fields_by_resource.get(resource.resource_id)
            if capability_fields is None:
                continue
            field_specs = capability_fields.get(resource.capability_id)
            if field_specs is None:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "native_unsupported_capability",
                        f"native instrument {resource.resource_id} does not support "
                        f"capability {resource.capability_id}",
                        "desired_state_plan.points",
                    )
                )
                continue
            for field in resource.fields:
                field_spec = field_specs.get(field.field_path)
                if field_spec is None:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "native_unsupported_field",
                            f"native instrument {resource.resource_id} capability "
                            f"{resource.capability_id} does not support field "
                            f"{field.field_path}",
                            "desired_state_plan.points",
                        )
                    )
                elif field_spec.kind != field.value.kind:
                    diagnostics.append(
                        _diagnostic(
                            "error",
                            "native_field_kind_mismatch",
                            f"native field {field.field_path} expects "
                            f"{field_spec.kind}, got {field.value.kind}",
                            "desired_state_plan.points",
                        )
                    )
    return diagnostics


def _readback_all(
    instruments: list[NativeInstrument], diagnostics: list[Diagnostic]
) -> list[InstrumentStateSnapshot]:
    states: list[InstrumentStateSnapshot] = []
    for instrument in instruments:
        try:
            states.append(instrument.readback())
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_readback_failed",
                    "native instrument readback failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )
    return states


def _apply_desired_state(
    *,
    desired: list[DesiredResourceState],
    current_states: dict[str, InstrumentStateSnapshot],
    instruments_by_id: dict[str, NativeInstrument],
    diagnostics: list[Diagnostic],
) -> int:
    changed_field_count = 0
    for resource in desired:
        instrument = instruments_by_id[resource.resource_id]
        resource_desired = [resource]
        try:
            diagnostics.extend(instrument.validate(resource_desired))
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_validate_failed",
                    "native instrument validate failed for "
                    f"{resource.resource_id}: {type(error).__name__}: {error}",
                    resource.resource_id,
                    error,
                )
            )
            continue
        if has_blocking_diagnostics(diagnostics):
            continue
        current = current_states.get(resource.resource_id)
        if current is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_missing_current_state",
                    f"missing current state for {resource.resource_id}",
                    resource.resource_id,
                )
            )
            continue
        try:
            patch = instrument.diff(current, resource_desired)
            changed_field_count += len(patch.fields)
            current_states[resource.resource_id] = instrument.apply(patch)
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_apply_failed",
                    "native instrument apply failed for "
                    f"{resource.resource_id}: {type(error).__name__}: {error}",
                    resource.resource_id,
                    error,
                )
            )
    return changed_field_count


def _desired_for_point(
    plan: PlanSnapshot, point_index: int
) -> list[DesiredResourceState]:
    desired_points, _diagnostics = _desired_points(plan)
    return desired_points.get(point_index, [])


def _desired_points(
    plan: PlanSnapshot,
) -> tuple[dict[int, list[DesiredResourceState]], list[Diagnostic]]:
    grouped: dict[tuple[int, str, str], list[DesiredStateField]] = {}
    diagnostics: list[Diagnostic] = []
    for record in plan.desired_state:
        capability_id, separator, field_path = record.field.partition(".")
        if not separator or not capability_id or not field_path:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_state_field_requires_capability",
                    "native state fields must use capability.field syntax",
                    "desired_state.field",
                )
            )
            continue
        value = _state_value(record.value)
        if value is None:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "native_state_value_unsupported",
                    "native state values must be quantities, numbers, "
                    "or asset references",
                    "desired_state.value",
                )
            )
            continue
        grouped.setdefault(
            (record.point_id, record.resource, capability_id),
            [],
        ).append(DesiredStateField(field_path=field_path, value=value))
    desired: dict[int, list[DesiredResourceState]] = {}
    for (point_id, resource_id, capability_id), fields in grouped.items():
        desired.setdefault(point_id, []).append(
            DesiredResourceState(
                resource_id=resource_id,
                capability_id=capability_id,
                fields=fields,
            )
        )
    return desired, diagnostics


def _state_value(value: object) -> StateValue | None:
    if isinstance(value, Quantity):
        return StateValue(kind="quantity", quantity=value)
    if isinstance(value, int | float):
        return StateValue(kind="number", value=float(value))
    if isinstance(value, Mapping):
        asset_value = cast(Mapping[str, object], value)
        kind = asset_value.get("kind")
        asset_id = asset_value.get("asset_id")
        if kind == "asset" and isinstance(asset_id, str):
            return StateValue(kind="asset", asset_id=asset_id)
    return None


def _acquisition_context(
    *,
    run_id: str,
    plan: PlanSnapshot,
    point_index: int,
    desired: list[DesiredResourceState],
) -> NativeAcquisitionContext:
    point = _execution_point(plan, point_index)
    records_for_point = _records_for_point(plan)
    record_index_offset = (
        point_index * records_for_point if _record(plan) == "shot" else point_index
    )
    return NativeAcquisitionContext(
        run_id=run_id,
        plan=plan,
        point=point,
        point_count=_point_count(plan),
        record_index_offset=record_index_offset,
        records_for_point=records_for_point,
        acquisition_plan=_acquisition_plan(plan),
        desired_state=desired,
    )


def _records_for_point(plan: PlanSnapshot) -> int:
    acquisition_plan = _acquisition_plan(plan)
    if acquisition_plan is None or acquisition_plan.record != "shot":
        return 1
    point_count = max(_point_count(plan), 1)
    return max(acquisition_plan.estimated_records // point_count, 1)


def _point_indices(plan: PlanSnapshot) -> list[int]:
    return [point.point_id for point in plan.points]


def _point_count(plan: PlanSnapshot) -> int:
    return len(plan.points)


def _execution_point(plan: PlanSnapshot, point_index: int) -> ExecutionPoint:
    for point in plan.points:
        if point.point_id == point_index:
            return ExecutionPoint(
                index=point.point_id,
                coordinates={
                    name: value
                    for name, value in point.row.items()
                    if isinstance(value, Quantity)
                },
            )
    msg = f"point index {point_index} not found"
    raise ValueError(msg)


def _acquisition_plan(plan: PlanSnapshot) -> AcquisitionPlan | None:
    record = _record(plan)
    if record is None:
        return None
    return AcquisitionPlan(
        kind=plan.acquisition.kind,
        record=record,
        shots=plan.acquisition.shots,
        repetitions=plan.acquisition.repetitions,
        estimated_records=plan.acquisition.estimated_records,
    )


def _record(
    plan: PlanSnapshot,
) -> Literal["point", "shot"] | None:
    record = plan.acquisition.record
    if record == "point" or record == "shot":
        return record
    return None


def _abort_all(
    instruments: list[NativeInstrument], diagnostics: list[Diagnostic]
) -> None:
    for instrument in instruments:
        try:
            instrument.abort()
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_abort_failed",
                    "native instrument abort failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )


def _cleanup_all(
    instruments: list[NativeInstrument], diagnostics: list[Diagnostic]
) -> None:
    for instrument in instruments:
        try:
            instrument.cleanup()
        except Exception as error:
            diagnostics.append(
                _diagnostic_from_exception(
                    "error",
                    "native_instrument_cleanup_failed",
                    "native instrument cleanup failed for "
                    f"{instrument.instrument_id}: {type(error).__name__}: {error}",
                    instrument.instrument_id,
                    error,
                )
            )


def _manifest(
    *,
    config: ConfigProfileSnapshot,
    experiment_id: str,
    execution: ExecutionProfile,
    run_id: str,
    status: RunStatus,
    summary_ref: str,
    snapshot_ref: str,
    boundary_ref: str,
    data_ref: str,
    instruments: list[NativeInstrument],
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
        runner_versions=_runner_versions(instruments),
        events_ref="events.jsonl",
        artifact_refs=_artifact_refs(
            summary_ref=summary_ref,
            snapshot_ref=snapshot_ref,
            boundary_ref=boundary_ref,
            data_ref=data_ref,
            measurements=measurements,
            expected_schema=expected_schema,
        ),
        finalization_summary=finalization_summary,
    )


def _runner_versions(instruments: list[NativeInstrument]) -> dict[str, str]:
    return {
        instrument.implementation_id: instrument.implementation_version
        for instrument in instruments
    }


def _artifact_refs(
    *,
    summary_ref: str,
    snapshot_ref: str,
    boundary_ref: str,
    data_ref: str,
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
) -> list[Artifact]:
    return [
        Artifact(
            id="native-run-summary",
            kind="summary",
            path=summary_ref,
            media_type="text/markdown",
        ),
        Artifact(
            id="native-run-snapshot",
            kind="native_run_snapshot",
            path=snapshot_ref,
            media_type="application/json",
        ),
        Artifact(
            id=NATIVE_BOUNDARY_MANIFEST_ARTIFACT_ID,
            kind="native_boundary_manifest",
            path=boundary_ref,
            media_type="application/json",
        ),
        build_raw_measurement_artifact(
            artifact_id=NATIVE_RAW_MEASUREMENTS_ARTIFACT_ID,
            ref=data_ref,
            records=measurements,
            expected_schema=expected_schema,
        ),
    ]


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


def _diagnostic_from_exception(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None,
    error: Exception,
) -> Diagnostic:
    to_diagnostic = getattr(error, "to_diagnostic", None)
    if callable(to_diagnostic):
        diagnostic = to_diagnostic()
        if isinstance(diagnostic, Diagnostic):
            return diagnostic
    return _diagnostic(severity, code, message, path)
