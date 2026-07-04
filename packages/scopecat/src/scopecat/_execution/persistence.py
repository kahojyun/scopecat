"""Common execution persistence and raw dataset contract helpers."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from scopecat._storage.local import LocalRunStore
from scopecat._storage.refs import dataset_content_ref
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.experiments import PlanSnapshot
from scopecat.models.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource, RunManifest, RunStatus
from scopecat.results import (
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
    infer_measurement_dataset_schema,
    validate_measurement_records_against_schema,
)

RAW_MEASUREMENT_DATASET_KIND = "measurement_dataset"


def ref_for_dataset(
    dataset_id: str, *, kind: str = RAW_MEASUREMENT_DATASET_KIND
) -> str:
    return dataset_content_ref(dataset_id=dataset_id, kind=kind)


def parse_expected_dataset_schema(
    plan: PlanSnapshot,
) -> tuple[MeasurementDatasetSchema | None, list[Diagnostic]]:
    if plan.expected_dataset_schema is None:
        return None, []
    try:
        return MeasurementDatasetSchema.model_validate(plan.expected_dataset_schema), []
    except ValueError as error:
        return None, [
            _diagnostic(
                "error",
                "invalid_expected_dataset_schema",
                f"expected dataset schema is invalid: {error}",
                "expected_dataset_schema",
            )
        ]


def expected_measurement_indices(plan: PlanSnapshot) -> set[int]:
    if plan.acquisition.record == "shot":
        return set(range(plan.acquisition.estimated_records))
    return {point.point_id for point in plan.points}


def validate_measurement_index_shape(
    *,
    measurements: Sequence[MeasurementRecord],
    expected_indices: set[int],
    duplicate_code: str,
    duplicate_message: str,
    unknown_code: str,
    unknown_message: str,
    missing_observables_code: str,
    missing_observables_message: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen_indices: set[int] = set()
    for measurement in measurements:
        if measurement.point_index in seen_indices:
            diagnostics.append(
                _diagnostic(
                    "error",
                    duplicate_code,
                    f"{duplicate_message} {measurement.point_index}",
                    "point_index",
                )
            )
        seen_indices.add(measurement.point_index)
        if measurement.point_index not in expected_indices:
            diagnostics.append(
                _diagnostic(
                    "error",
                    unknown_code,
                    f"{unknown_message} {measurement.point_index}",
                    "point_index",
                )
            )
        if not measurement.observables:
            diagnostics.append(
                _diagnostic(
                    "error",
                    missing_observables_code,
                    missing_observables_message,
                    "observables",
                )
            )
    return diagnostics


def validate_raw_measurement_dataset(
    *,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole = "raw",
) -> list[Diagnostic]:
    if expected_schema is None:
        return []
    return validate_measurement_records_against_schema(
        records=records,
        schema=expected_schema,
        dataset_id=dataset_id,
        dataset_role=dataset_role,
    )


def build_raw_measurement_dataset(
    *,
    dataset_id: str,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
) -> RunDatasetEntry:
    schema = expected_schema
    if schema is None:
        schema = infer_measurement_dataset_schema(
            dataset_id=dataset_id,
            dataset_role="raw",
            records=records,
        )
    return RunDatasetEntry(
        id=dataset_id,
        kind=RAW_MEASUREMENT_DATASET_KIND,
        media_type="application/x-ndjson",
        role="raw",
        schema=schema.model_dump(mode="json"),
    )


def build_run_manifest(
    *,
    run_id: str,
    status: RunStatus,
    config_source: RunConfigSource | None = None,
    records: Sequence[RunRecordEntry] = (),
    datasets: Sequence[RunDatasetEntry] = (),
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        status=status,
        config_source=config_source,
        records=list(records),
        datasets=list(datasets),
    )


def write_final_execution_artifacts(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    config: ConfigProfileSnapshot,
    plan: BaseModel,
    snapshot_ref: str,
    snapshot: BaseModel,
    data_ref: str | None,
    measurements: Sequence[MeasurementRecord] = (),
) -> None:
    storage.write_run_inputs(manifest=manifest, config=config, plan=plan)
    storage.write_model(manifest.run_id, snapshot_ref, snapshot)
    if data_ref is not None:
        storage.write_jsonl(manifest.run_id, data_ref, measurements)


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
