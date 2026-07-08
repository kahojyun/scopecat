"""Run-to-run comparison for measurement record observables."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from scopecat._manifest_updates import write_manifest_records
from scopecat._storage.refs import dataset_content_ref, record_content_ref
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.results import (
    ComplexQuantity,
    MeasurementDatasetSchema,
    MeasurementRecord,
)
from scopecat.run_comparison.models import (
    ComparisonOutcome,
    RunComparisonPoint,
    RunComparisonResult,
    RunComparisonReviewRecord,
    RunComparisonReviewState,
    RunComparisonReviewStatus,
    RunComparisonView,
)
from scopecat.runs import (
    RunStore,
    get_dataset_by_id,
    list_records,
    open_run_store,
    read_measurement_records,
)
from scopecat.runs.access import record_storage_ref

MEASUREMENT_DATASET_ID = "raw-measurements"
MEASUREMENT_DATA_REF = dataset_content_ref(
    dataset_id=MEASUREMENT_DATASET_ID,
    kind="measurement_dataset",
)
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def execute_run_comparison(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    workspace: str | Path,
    observable_id: str | None = None,
) -> RunComparisonResult:
    _validate_safe_id(baseline_run_id, "baseline_run_id")
    _validate_safe_id(candidate_run_id, "candidate_run_id")
    if observable_id is not None:
        _validate_safe_id(observable_id, "observable_id")

    storage = open_run_store(workspace)
    baseline_manifest = storage.read_manifest(baseline_run_id)
    candidate_manifest = storage.read_manifest(candidate_run_id)
    resolved_observable_id = _resolve_observable_id(
        requested=observable_id,
        baseline_manifest=baseline_manifest,
        candidate_manifest=candidate_manifest,
    )

    baseline_measurements = _read_measurements(
        storage=storage,
        run_id=baseline_run_id,
    )
    candidate_measurements = _read_measurements(
        storage=storage,
        run_id=candidate_run_id,
    )
    points = _compare_measurements(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        observable_id=resolved_observable_id,
        baseline_measurements=baseline_measurements,
        candidate_measurements=candidate_measurements,
    )

    baseline_peak = _peak_point(points, side="baseline")
    candidate_peak = _peak_point(points, side="candidate")
    peak_value_delta = Quantity(
        value=round(
            candidate_peak.candidate_value.value - baseline_peak.baseline_value.value,
            12,
        ),
        unit=baseline_peak.baseline_value.unit,
    )
    mean_value_delta = Quantity(
        value=round(
            sum(point.value_delta.value for point in points) / len(points),
            12,
        ),
        unit=baseline_peak.baseline_value.unit,
    )
    comparison_id = _comparison_id(candidate_run_id, resolved_observable_id)
    result_record = _comparison_output_record(comparison_id=comparison_id)
    result = RunComparisonResult(
        comparison_id=comparison_id,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        observable_id=resolved_observable_id,
        baseline_config_source=_read_config_source(
            storage=storage,
            run_id=baseline_run_id,
        ),
        candidate_config_source=_read_config_source(
            storage=storage,
            run_id=candidate_run_id,
        ),
        measurement_count=len(points),
        baseline_peak_point_index=baseline_peak.point_index,
        candidate_peak_point_index=candidate_peak.point_index,
        baseline_peak_value=baseline_peak.baseline_value,
        candidate_peak_value=candidate_peak.candidate_value,
        peak_value_delta=peak_value_delta,
        mean_value_delta=mean_value_delta,
        value_unit=peak_value_delta.unit,
        outcome=_outcome(peak_value_delta.value),
        points=points,
    )
    storage.write_model(baseline_run_id, record_storage_ref(result_record), result)

    write_manifest_records(
        storage=storage,
        manifest=baseline_manifest,
        records=[result_record],
    )
    return result


def list_run_comparisons(
    *, run_id: str, workspace: str | Path
) -> list[RunComparisonView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    views: list[RunComparisonView] = []
    for record in _comparison_records(manifest):
        result = _load_comparison_record(
            storage=storage,
            run_id=run_id,
            record=record,
            selector=record.id,
        )
        views.append(
            RunComparisonView(
                id=result.comparison_id,
                observable_id=result.observable_id,
                outcome=result.outcome,
                candidate_run_id=result.candidate_run_id,
                peak_value_delta=result.peak_value_delta,
                review_status=_review_status(
                    storage=storage,
                    run_id=run_id,
                    comparison_id=result.comparison_id,
                ),
            )
        )
    return views


def review_run_comparison(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    state: RunComparisonReviewState,
    reviewer: str,
    note: str,
) -> tuple[RunComparisonResult, RunComparisonReviewRecord]:
    if state not in {"accepted", "rejected"}:
        raise ValidationFailed(
            [unsupported_run_comparison_review_state_diagnostic(state)]
        )

    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    _comparison_record, result = _resolve_comparison(
        manifest=manifest,
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    review_record = RunRecordEntry(
        id=f"{result.comparison_id}-review",
        kind="run_comparison_review_record",
        media_type="application/json",
    )
    review_ref = record_storage_ref(review_record)
    if storage.exists(run_id, review_ref):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_already_reviewed",
                    f"run comparison already reviewed: {result.comparison_id}",
                    "comparison",
                )
            ]
        )

    review = RunComparisonReviewRecord(
        run_id=run_id,
        comparison_id=result.comparison_id,
        decision=state,
        reviewer=reviewer,
        note=note,
    )
    storage.write_model(run_id, review_ref, review)
    write_manifest_records(
        storage=storage,
        manifest=manifest,
        records=[review_record],
    )
    return result, review


def unsupported_run_comparison_review_state_diagnostic(state: str) -> Diagnostic:
    return _diagnostic(
        "error",
        "unsupported_run_comparison_review_state",
        f"unsupported run comparison review state: {state}",
        "state",
    )


def _comparison_output_record(*, comparison_id: str) -> RunRecordEntry:
    return RunRecordEntry(
        id=f"{comparison_id}-result",
        kind="run_comparison_result",
        media_type="application/json",
    )


def _comparison_records(manifest: RunManifest) -> list[RunRecordEntry]:
    return sorted(
        list_records(manifest, kind="run_comparison_result"),
        key=lambda record: record.id,
    )


def _resolve_comparison(
    *,
    manifest: RunManifest,
    storage: RunStore,
    run_id: str,
    selector: str,
) -> tuple[RunRecordEntry, RunComparisonResult]:
    _validate_selector_path(selector)
    record_by_id = {record.id: record for record in manifest.records}
    record_by_path = {record_storage_ref(record): record for record in manifest.records}

    if selector in record_by_id:
        record = record_by_id[selector]
        if record.kind != "run_comparison_result":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_run_comparison",
                        f"record is not a run comparison result: {selector}",
                        "comparison",
                    )
                ]
            )
        return record, _load_comparison_record(
            storage=storage,
            run_id=run_id,
            record=record,
            selector=selector,
        )

    if selector in record_by_path:
        record = record_by_path[selector]
        if record.kind != "run_comparison_result":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_run_comparison",
                        f"record is not a run comparison result: {selector}",
                        "comparison",
                    )
                ]
            )
        return record, _load_comparison_record(
            storage=storage,
            run_id=run_id,
            record=record,
            selector=selector,
        )

    for record in _comparison_records(manifest):
        result = _load_comparison_record(
            storage=storage,
            run_id=run_id,
            record=record,
            selector=selector,
        )
        if result.comparison_id == selector:
            return record, result

    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "run_comparison_not_found",
                f"run comparison not found: {selector}",
                "comparison",
            )
        ]
    )


def _load_comparison_record(
    *,
    storage: RunStore,
    run_id: str,
    record: RunRecordEntry,
    selector: str,
) -> RunComparisonResult:
    record_ref = record_storage_ref(record)
    path = storage.ref_path(run_id, record_ref)
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_not_found",
                    f"run comparison not found: {selector}",
                    "comparison",
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_is_directory",
                    f"run comparison is a directory: {selector}",
                    "comparison",
                )
            ]
        )
    try:
        return RunComparisonResult.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_run_comparison",
                    f"run comparison is not valid JSON: {selector}",
                    "comparison",
                )
            ]
        ) from error


def _validate_selector_path(selector: str) -> None:
    path = PurePosixPath(selector)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_path_escape",
                    f"run comparison path escapes run directory: {selector}",
                    "comparison",
                )
            ]
        )


def _review_ref(comparison_id: str) -> str:
    return record_content_ref(
        record_id=f"{comparison_id}-review",
        kind="run_comparison_review_record",
    )


def _review_status(
    *, storage: RunStore, run_id: str, comparison_id: str
) -> RunComparisonReviewStatus:
    if storage.exists(run_id, _review_ref(comparison_id)):
        return "reviewed"
    return "not_reviewed"


def _comparison_id(candidate_run_id: str, observable_id: str) -> str:
    return f"run-comparison-{candidate_run_id}-{observable_id}"


def _resolve_observable_id(
    *,
    requested: str | None,
    baseline_manifest: RunManifest,
    candidate_manifest: RunManifest,
) -> str:
    if requested is not None:
        return requested

    baseline_observables = _primary_observables_from_manifest(
        manifest=baseline_manifest,
        side="baseline",
    )
    candidate_observables = _primary_observables_from_manifest(
        manifest=candidate_manifest,
        side="candidate",
    )
    _validate_single_primary_observable(
        observables=baseline_observables,
        side="baseline",
    )
    _validate_single_primary_observable(
        observables=candidate_observables,
        side="candidate",
    )
    baseline_observable = baseline_observables[0]
    candidate_observable = candidate_observables[0]
    if baseline_observable != candidate_observable:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_primary_observable_mismatch",
                    (
                        "run comparison primary observables do not match: "
                        f"{baseline_observable} != {candidate_observable}"
                    ),
                    "observable_id",
                )
            ]
        )
    _validate_safe_id(baseline_observable, "observable_id")
    return baseline_observable


def _primary_observables_from_manifest(
    *,
    manifest: RunManifest,
    side: str,
) -> list[str]:
    dataset = _raw_measurement_dataset(manifest)
    schema_data = dataset.data_schema
    path = f"runs/{manifest.run_id}/manifest.datasets.{dataset.id}.schema"
    if schema_data is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_run_comparison_dataset_schema",
                    f"{side} raw measurement dataset is missing schema",
                    path,
                )
            ]
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(schema_data)
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_run_comparison_dataset_schema",
                    f"{side} raw measurement dataset_schema is invalid",
                    path,
                )
            ]
        ) from error
    return schema.primary_observables


def _raw_measurement_dataset(manifest: RunManifest) -> RunDatasetEntry:
    dataset = get_dataset_by_id(manifest, MEASUREMENT_DATASET_ID)
    if dataset is not None:
        return dataset
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "missing_run_comparison_dataset_schema",
                "run comparison input manifest is missing raw measurement dataset",
                f"runs/{manifest.run_id}/manifest.datasets",
            )
        ]
    )


def _validate_single_primary_observable(
    *,
    observables: list[str],
    side: str,
) -> None:
    if len(observables) == 1:
        return
    if not observables:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_missing_primary_observable",
                    f"{side} raw measurement dataset has no primary observable",
                    "observable_id",
                )
            ]
        )
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "run_comparison_ambiguous_primary_observable",
                (
                    f"{side} raw measurement dataset has multiple primary "
                    "observables; pass observable_id explicitly"
                ),
                "observable_id",
            )
        ]
    )


def _validate_safe_id(value: str, path: str) -> None:
    if not SAFE_ID_RE.fullmatch(value):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_invalid_id",
                    f"run comparison id is not safe: {value}",
                    path,
                )
            ]
        )


def _read_measurements(*, storage: RunStore, run_id: str) -> list[MeasurementRecord]:
    diagnostic_path = f"runs/{run_id}/{MEASUREMENT_DATA_REF}"
    return read_measurement_records(
        storage=storage,
        run_id=run_id,
        ref=MEASUREMENT_DATA_REF,
        missing_code="missing_run_comparison_input",
        empty_code="empty_run_comparison_input",
        invalid_code="invalid_run_comparison_input",
        noun="run comparison input",
        diagnostic_path=diagnostic_path,
    )


def _compare_measurements(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    observable_id: str,
    baseline_measurements: list[MeasurementRecord],
    candidate_measurements: list[MeasurementRecord],
) -> list[RunComparisonPoint]:
    if len(baseline_measurements) != len(candidate_measurements):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_measurement_mismatch",
                    "run comparison measurement counts do not match",
                    MEASUREMENT_DATA_REF,
                )
            ]
        )

    points: list[RunComparisonPoint] = []
    for baseline, candidate in zip(
        baseline_measurements,
        candidate_measurements,
        strict=True,
    ):
        if baseline.point_index != candidate.point_index:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "run_comparison_point_mismatch",
                        "run comparison point indexes do not match",
                        "point_index",
                    )
                ]
            )
        baseline_value = _observable(baseline, baseline_run_id, observable_id)
        candidate_value = _observable(candidate, candidate_run_id, observable_id)
        if baseline_value.unit != candidate_value.unit:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "run_comparison_unit_mismatch",
                        f"run comparison {observable_id} units do not match",
                        f"observables.{observable_id}.unit",
                    )
                ]
            )
        points.append(
            RunComparisonPoint(
                point_index=baseline.point_index,
                baseline_coordinates=baseline.coordinates,
                candidate_coordinates=candidate.coordinates,
                baseline_value=baseline_value,
                candidate_value=candidate_value,
                value_delta=Quantity(
                    value=round(candidate_value.value - baseline_value.value, 12),
                    unit=baseline_value.unit,
                ),
            )
        )
    return points


def _observable(
    measurement: MeasurementRecord, run_id: str, observable_id: str
) -> Quantity:
    value = measurement.observables.get(observable_id)
    if value is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_missing_observable",
                    f"run comparison measurement is missing {observable_id}: {run_id}",
                    f"observables.{observable_id}",
                )
            ]
        )
    if not isinstance(value, Quantity):
        if isinstance(value, ComplexQuantity):
            return Quantity(
                value=round(abs(complex(value.real, value.imag)), 12),
                unit=value.unit,
            )
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "run_comparison_array_observable_unsupported",
                    f"run comparison observable must be scalar: {observable_id}",
                    f"observables.{observable_id}",
                )
            ]
        )
    return value


def _peak_point(
    points: list[RunComparisonPoint],
    *,
    side: Literal["baseline", "candidate"],
) -> RunComparisonPoint:
    if side == "baseline":
        return max(points, key=lambda point: point.baseline_value.value)
    return max(points, key=lambda point: point.candidate_value.value)


def _outcome(peak_value_delta: float) -> ComparisonOutcome:
    if peak_value_delta > 0:
        return "increased"
    if peak_value_delta < 0:
        return "decreased"
    return "unchanged"


def _read_config_source(*, storage: RunStore, run_id: str) -> RunConfigSource | None:
    manifest = storage.read_manifest(run_id)
    return manifest.config_source


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
