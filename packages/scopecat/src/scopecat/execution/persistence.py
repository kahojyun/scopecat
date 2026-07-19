"""Common execution persistence and raw dataset contract helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.measurements.datasets import (
    MEASUREMENT_DATASET_KIND,
    measurement_dataset_entry,
    validate_measurement_dataset_records,
)
from scopecat.measurements.results import (
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigContentHash
from scopecat.records.run import RunConfigSource, RunLifecycle, RunManifest, RunOutcome
from scopecat.runs.refs import dataset_content_ref

RAW_MEASUREMENT_DATASET_KIND = MEASUREMENT_DATASET_KIND


def ref_for_dataset(
    dataset_id: str, *, kind: str = RAW_MEASUREMENT_DATASET_KIND
) -> str:
    return dataset_content_ref(dataset_id=dataset_id, kind=kind)


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
) -> list[Problem]:
    problems: list[Problem] = []
    seen_indices: set[int] = set()
    for measurement in measurements:
        if measurement.point_index in seen_indices:
            problems.append(
                _problem(
                    duplicate_code,
                    f"{duplicate_message} {measurement.point_index}",
                    "point_index",
                )
            )
        seen_indices.add(measurement.point_index)
        if measurement.point_index not in expected_indices:
            problems.append(
                _problem(
                    unknown_code,
                    f"{unknown_message} {measurement.point_index}",
                    "point_index",
                )
            )
        if not measurement.observables:
            problems.append(
                _problem(
                    missing_observables_code,
                    missing_observables_message,
                    "observables",
                )
            )
    return problems


def validate_raw_measurement_dataset(
    *,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole = "raw",
) -> list[Problem]:
    if expected_schema is None:
        return []
    return validate_measurement_dataset_records(
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
    metadata: Mapping[str, JsonValue] | None = None,
) -> RunContentEntry:
    return measurement_dataset_entry(
        dataset_id=dataset_id,
        dataset_role="raw",
        records=records,
        expected_schema=expected_schema,
        metadata=metadata,
    )


def build_run_manifest(
    *,
    run_id: str,
    lifecycle: RunLifecycle,
    outcome: RunOutcome | None = None,
    config_content_hash: ConfigContentHash,
    config_source: RunConfigSource | None = None,
    contents: Sequence[RunContentEntry] = (),
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        lifecycle=lifecycle,
        outcome=outcome,
        config_content_hash=config_content_hash,
        config_source=config_source,
        contents=tuple(contents),
    )


def _problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.DATA_INTEGRITY,
        phase=ProblemPhase.PERSISTENCE,
        location=model_location("measurement_dataset", *path),
    )
