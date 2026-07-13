"""Run-to-run comparison for measurement record observables."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from scopecat._manifest_updates import write_manifest_records
from scopecat._storage.refs import dataset_content_ref, record_content_ref
from scopecat.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.models.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)
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
        raise CheckFailed([unsupported_run_comparison_review_state_problem(state)])

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
        raise Conflict(
            [
                _problem(
                    "run_comparison_already_reviewed",
                    f"run comparison already reviewed: {result.comparison_id}",
                    category=ProblemCategory.CONFLICT,
                    location=StorageLocation(run_id=run_id, ref=review_ref),
                    details={"comparison_id": result.comparison_id},
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


def unsupported_run_comparison_review_state_problem(state: str) -> Problem:
    return _problem(
        "unsupported_run_comparison_review_state",
        f"unsupported run comparison review state: {state}",
        location=model_location("run_comparison", "state"),
        details={"state": state},
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
            raise CheckFailed(
                [
                    _problem(
                        "invalid_run_comparison",
                        f"record is not a run comparison result: {selector}",
                        location=model_location("run_comparison", "selector"),
                        details={"selector": selector, "record_kind": record.kind},
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
            raise CheckFailed(
                [
                    _problem(
                        "invalid_run_comparison",
                        f"record is not a run comparison result: {selector}",
                        location=model_location("run_comparison", "selector"),
                        details={"selector": selector, "record_kind": record.kind},
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

    raise NotFound(
        [
            _problem(
                "run_comparison_not_found",
                f"run comparison not found: {selector}",
                category=ProblemCategory.NOT_FOUND,
                location=StorageLocation(run_id=run_id, ref=selector),
                details={"selector": selector},
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
        raise NotFound(
            [
                _problem(
                    "run_comparison_not_found",
                    f"run comparison not found: {selector}",
                    category=ProblemCategory.NOT_FOUND,
                    location=StorageLocation(run_id=run_id, ref=record_ref),
                    details={"selector": selector},
                )
            ]
        )
    if path.is_dir():
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_is_directory",
                    f"run comparison is a directory: {selector}",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=StorageLocation(run_id=run_id, ref=record_ref),
                    details={"selector": selector},
                )
            ]
        )
    try:
        data = path.read_text()
    except OSError as error:
        raise StorageError(
            [
                _problem(
                    "run_comparison_read_failed",
                    "run comparison record could not be read",
                    category=ProblemCategory.STORAGE,
                    location=StorageLocation(run_id=run_id, ref=record_ref),
                    details={"selector": selector},
                )
            ]
        ) from error
    try:
        return RunComparisonResult.model_validate_json(data)
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _problem(
                    "invalid_run_comparison",
                    f"run comparison is not valid JSON: {selector}",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=StorageLocation(run_id=run_id, ref=record_ref),
                    details={"selector": selector},
                )
            ]
        ) from error


def _validate_selector_path(selector: str) -> None:
    path = PurePosixPath(selector)
    if path.is_absolute() or ".." in path.parts:
        raise CheckFailed(
            [
                _problem(
                    "run_comparison_path_escape",
                    f"run comparison path escapes run directory: {selector}",
                    location=model_location("run_comparison", "selector"),
                    details={"selector": selector},
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
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_primary_observable_mismatch",
                    (
                        "run comparison primary observables do not match: "
                        f"{baseline_observable} != {candidate_observable}"
                    ),
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=model_location("run_comparison", "observable_id"),
                    details={
                        "baseline_observable_id": baseline_observable,
                        "candidate_observable_id": candidate_observable,
                    },
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
    location = StorageLocation(
        run_id=manifest.run_id,
        ref="manifest.json",
        path=("datasets", dataset.id, "schema"),
    )
    if schema_data is None:
        raise DataIntegrityError(
            [
                _problem(
                    "missing_run_comparison_dataset_schema",
                    f"{side} raw measurement dataset is missing schema",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=location,
                    details={"side": side, "dataset_id": dataset.id},
                )
            ]
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(schema_data)
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _problem(
                    "invalid_run_comparison_dataset_schema",
                    f"{side} raw measurement dataset_schema is invalid",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=location,
                    details={"side": side, "dataset_id": dataset.id},
                )
            ]
        ) from error
    return schema.primary_observables


def _raw_measurement_dataset(manifest: RunManifest) -> RunDatasetEntry:
    dataset = get_dataset_by_id(manifest, MEASUREMENT_DATASET_ID)
    if dataset is not None:
        return dataset
    raise DataIntegrityError(
        [
            _problem(
                "missing_run_comparison_dataset_schema",
                "run comparison input manifest is missing raw measurement dataset",
                category=ProblemCategory.DATA_INTEGRITY,
                location=StorageLocation(
                    run_id=manifest.run_id,
                    ref="manifest.json",
                    path=("datasets",),
                ),
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
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_missing_primary_observable",
                    f"{side} raw measurement dataset has no primary observable",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=model_location("run_comparison", "observable_id"),
                    details={"side": side},
                )
            ]
        )
    raise DataIntegrityError(
        [
            _problem(
                "run_comparison_ambiguous_primary_observable",
                (
                    f"{side} raw measurement dataset has multiple primary "
                    "observables; pass observable_id explicitly"
                ),
                category=ProblemCategory.DATA_INTEGRITY,
                location=model_location("run_comparison", "observable_id"),
                details={"side": side, "observable_ids": observables},
            )
        ]
    )


def _validate_safe_id(value: str, *path: LocationPathItem) -> None:
    if not SAFE_ID_RE.fullmatch(value):
        raise CheckFailed(
            [
                _problem(
                    "run_comparison_invalid_id",
                    f"run comparison id is not safe: {value}",
                    location=model_location("run_comparison", *path),
                    details={"value": value},
                )
            ]
        )


def _read_measurements(*, storage: RunStore, run_id: str) -> list[MeasurementRecord]:
    try:
        return read_measurement_records(
            storage=storage,
            run_id=run_id,
            ref=MEASUREMENT_DATA_REF,
            missing_code="missing_run_comparison_input",
            empty_code="empty_run_comparison_input",
            invalid_code="invalid_run_comparison_input",
            noun="run comparison input",
        )
    except NotFound as error:
        source = error.problems[0]
        related_locations = source.related_locations
        if source.location is not None:
            related_locations = (source.location, *related_locations)
        raise DataIntegrityError(
            [
                source.model_copy(
                    update={
                        "category": ProblemCategory.DATA_INTEGRITY,
                        "phase": ProblemPhase.ANALYSIS,
                        "location": StorageLocation(
                            run_id=run_id,
                            ref=MEASUREMENT_DATA_REF,
                        ),
                        "related_locations": related_locations,
                    }
                )
            ]
        ) from error


def _compare_measurements(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    observable_id: str,
    baseline_measurements: list[MeasurementRecord],
    candidate_measurements: list[MeasurementRecord],
) -> list[RunComparisonPoint]:
    if len(baseline_measurements) != len(candidate_measurements):
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_measurement_mismatch",
                    "run comparison measurement counts do not match",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=StorageLocation(
                        run_id=baseline_run_id,
                        ref=MEASUREMENT_DATA_REF,
                    ),
                    related_locations=(
                        StorageLocation(
                            run_id=candidate_run_id,
                            ref=MEASUREMENT_DATA_REF,
                        ),
                    ),
                    details={
                        "baseline_count": len(baseline_measurements),
                        "candidate_count": len(candidate_measurements),
                    },
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
            raise DataIntegrityError(
                [
                    _problem(
                        "run_comparison_point_mismatch",
                        "run comparison point indexes do not match",
                        category=ProblemCategory.DATA_INTEGRITY,
                        location=StorageLocation(
                            run_id=baseline_run_id,
                            ref=MEASUREMENT_DATA_REF,
                            path=(baseline.point_index,),
                        ),
                        related_locations=(
                            StorageLocation(
                                run_id=candidate_run_id,
                                ref=MEASUREMENT_DATA_REF,
                                path=(candidate.point_index,),
                            ),
                        ),
                        details={
                            "baseline_point_index": baseline.point_index,
                            "candidate_point_index": candidate.point_index,
                        },
                    )
                ]
            )
        baseline_value = _observable(baseline, baseline_run_id, observable_id)
        candidate_value = _observable(candidate, candidate_run_id, observable_id)
        if baseline_value.unit != candidate_value.unit:
            raise DataIntegrityError(
                [
                    _problem(
                        "run_comparison_unit_mismatch",
                        f"run comparison {observable_id} units do not match",
                        category=ProblemCategory.DATA_INTEGRITY,
                        location=StorageLocation(
                            run_id=baseline_run_id,
                            ref=MEASUREMENT_DATA_REF,
                            path=(
                                baseline.point_index,
                                "observables",
                                observable_id,
                                "unit",
                            ),
                        ),
                        related_locations=(
                            StorageLocation(
                                run_id=candidate_run_id,
                                ref=MEASUREMENT_DATA_REF,
                                path=(
                                    candidate.point_index,
                                    "observables",
                                    observable_id,
                                    "unit",
                                ),
                            ),
                        ),
                        details={
                            "baseline_unit": baseline_value.unit,
                            "candidate_unit": candidate_value.unit,
                        },
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
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_missing_observable",
                    f"run comparison measurement is missing {observable_id}: {run_id}",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=StorageLocation(
                        run_id=run_id,
                        ref=MEASUREMENT_DATA_REF,
                        path=(
                            measurement.point_index,
                            "observables",
                            observable_id,
                        ),
                    ),
                    details={"observable_id": observable_id},
                )
            ]
        )
    if not isinstance(value, Quantity):
        if isinstance(value, ComplexQuantity):
            return Quantity(
                value=round(abs(complex(value.real, value.imag)), 12),
                unit=value.unit,
            )
        raise DataIntegrityError(
            [
                _problem(
                    "run_comparison_array_observable_unsupported",
                    f"run comparison observable must be scalar: {observable_id}",
                    category=ProblemCategory.DATA_INTEGRITY,
                    location=StorageLocation(
                        run_id=run_id,
                        ref=MEASUREMENT_DATA_REF,
                        path=(
                            measurement.point_index,
                            "observables",
                            observable_id,
                        ),
                    ),
                    details={"observable_id": observable_id},
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


def _problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    location: ProblemLocation | None = None,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.ANALYSIS,
        location=location,
        related_locations=related_locations,
        details={} if details is None else details,
    )
