"""Run-to-run comparison for measurement record observables."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.config_registry import ConfigRegistryConfigSourceProvenance
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest
from scopecat.results import MeasurementDatasetSchema, MeasurementRecord
from scopecat.run_comparison.models import (
    ComparisonOutcome,
    RunComparisonConfigSourceSummary,
    RunComparisonJob,
    RunComparisonPoint,
    RunComparisonResult,
    RunComparisonReviewRecord,
    RunComparisonReviewState,
    RunComparisonReviewStatus,
    RunComparisonView,
)
from scopecat.runs import (
    RunStore,
    open_run_store,
    read_measurement_records,
)

MEASUREMENT_DATA_REF = "artifacts/raw-measurements.jsonl"
MEASUREMENT_DATA_ARTIFACT_ID = "raw-measurements"
CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def execute_run_comparison(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    workspace: str | Path,
    observable_id: str | None = None,
) -> tuple[RunComparisonJob, RunComparisonResult]:
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
    refs = _comparison_refs(comparison_id)
    artifacts = _comparison_output_artifacts(comparison_id=comparison_id, refs=refs)
    baseline_analysis_artifacts = _analysis_artifacts(baseline_manifest)
    candidate_analysis_artifacts = _analysis_artifacts(candidate_manifest)
    result = RunComparisonResult(
        comparison_id=comparison_id,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        observable_id=resolved_observable_id,
        baseline_analysis_artifact_ids=[
            artifact.id for artifact in baseline_analysis_artifacts
        ],
        candidate_analysis_artifact_ids=[
            artifact.id for artifact in candidate_analysis_artifacts
        ],
        baseline_config_source=_read_config_source_summary(
            storage=storage,
            run_id=baseline_run_id,
        ),
        candidate_config_source=_read_config_source_summary(
            storage=storage,
            run_id=candidate_run_id,
        ),
        job_ref=refs.job_ref,
        result_ref=refs.result_ref,
        artifact_refs=artifacts,
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
    job = RunComparisonJob(
        id=comparison_id,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        observable_id=resolved_observable_id,
        baseline_input_artifact_ids=[
            MEASUREMENT_DATA_ARTIFACT_ID,
            *[artifact.id for artifact in baseline_analysis_artifacts],
        ],
        candidate_input_artifact_ids=[
            MEASUREMENT_DATA_ARTIFACT_ID,
            *[artifact.id for artifact in candidate_analysis_artifacts],
        ],
        input_record_refs=[
            f"runs/{baseline_run_id}/manifest.json",
            f"runs/{baseline_run_id}/{CONFIG_PROFILE_SNAPSHOT_REF}",
            f"runs/{candidate_run_id}/manifest.json",
            f"runs/{candidate_run_id}/{CONFIG_PROFILE_SNAPSHOT_REF}",
        ],
        output_artifact_ids=[artifacts[0].id],
        output_artifacts=artifacts[:1],
    )
    storage.write_model(baseline_run_id, refs.job_ref, job)
    storage.write_model(baseline_run_id, refs.result_ref, result)

    write_manifest_artifacts(
        storage=storage,
        manifest=baseline_manifest,
        artifacts=artifacts,
    )
    return job, result


def list_run_comparisons(
    *, run_id: str, workspace: str | Path
) -> list[RunComparisonView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    views: list[RunComparisonView] = []
    for artifact in _comparison_artifacts(manifest):
        result = _load_comparison_artifact(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
            selector=artifact.id,
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
                path=artifact.path,
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
    artifact, result = _resolve_comparison(
        manifest=manifest,
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    review_ref = _review_ref(result.comparison_id)
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
        comparison_ref=artifact.path,
        decision=state,
        reviewer=reviewer,
        note=note,
    )
    storage.write_model(run_id, review_ref, review)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[
            Artifact(
                id=f"{result.comparison_id}-review",
                kind="run_comparison_review_record",
                path=review_ref,
                media_type="application/json",
            )
        ],
    )
    return result, review


def unsupported_run_comparison_review_state_diagnostic(state: str) -> Diagnostic:
    return _diagnostic(
        "error",
        "unsupported_run_comparison_review_state",
        f"unsupported run comparison review state: {state}",
        "state",
    )


class _ComparisonRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ref: str
    result_ref: str


def _comparison_refs(comparison_id: str) -> _ComparisonRefs:
    return _ComparisonRefs(
        job_ref=f"comparisons/{comparison_id}.job.json",
        result_ref=f"artifacts/{comparison_id}.json",
    )


def _comparison_output_artifacts(
    *, comparison_id: str, refs: _ComparisonRefs
) -> list[Artifact]:
    return [
        Artifact(
            id=f"{comparison_id}-result",
            kind="run_comparison_result",
            path=refs.result_ref,
            media_type="application/json",
        ),
        Artifact(
            id=f"{comparison_id}-job",
            kind="run_comparison_job",
            path=refs.job_ref,
            media_type="application/json",
        ),
    ]


def _comparison_artifacts(manifest: RunManifest) -> list[Artifact]:
    return sorted(
        (
            artifact
            for artifact in manifest.artifact_refs
            if artifact.kind == "run_comparison_result"
        ),
        key=lambda artifact: artifact.id,
    )


def _analysis_artifacts(manifest: RunManifest) -> list[Artifact]:
    return sorted(
        (
            artifact
            for artifact in manifest.artifact_refs
            if artifact.kind == "analysis"
        ),
        key=lambda artifact: artifact.id,
    )


def _resolve_comparison(
    *,
    manifest: RunManifest,
    storage: RunStore,
    run_id: str,
    selector: str,
) -> tuple[Artifact, RunComparisonResult]:
    _validate_selector_path(selector)
    artifact_by_id = {artifact.id: artifact for artifact in manifest.artifact_refs}
    artifact_by_path = {artifact.path: artifact for artifact in manifest.artifact_refs}

    if selector in artifact_by_id:
        artifact = artifact_by_id[selector]
        if artifact.kind != "run_comparison_result":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_run_comparison",
                        f"artifact is not a run comparison result: {selector}",
                        "comparison",
                    )
                ]
            )
        return artifact, _load_comparison_artifact(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
            selector=selector,
        )

    if selector in artifact_by_path:
        artifact = artifact_by_path[selector]
        if artifact.kind != "run_comparison_result":
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_run_comparison",
                        f"artifact is not a run comparison result: {selector}",
                        "comparison",
                    )
                ]
            )
        return artifact, _load_comparison_artifact(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
            selector=selector,
        )

    for artifact in _comparison_artifacts(manifest):
        result = _load_comparison_artifact(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
            selector=selector,
        )
        if result.comparison_id == selector:
            return artifact, result

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


def _load_comparison_artifact(
    *,
    storage: RunStore,
    run_id: str,
    artifact: Artifact,
    selector: str,
) -> RunComparisonResult:
    path = storage.ref_path(run_id, artifact.path)
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
    return f"reviews/{comparison_id}.review.json"


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
    artifact = _raw_measurement_artifact(manifest)
    schema_data = artifact.metadata.get("dataset_schema")
    path = (
        f"runs/{manifest.run_id}/manifest.artifact_refs."
        f"{artifact.id}.metadata.dataset_schema"
    )
    if schema_data is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_run_comparison_dataset_schema",
                    f"{side} raw measurement artifact is missing dataset_schema",
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


def _raw_measurement_artifact(manifest: RunManifest) -> Artifact:
    for artifact in manifest.artifact_refs:
        if artifact.id == "raw-measurements" or artifact.path == MEASUREMENT_DATA_REF:
            return artifact
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "missing_run_comparison_dataset_schema",
                "run comparison input manifest is missing raw measurement artifact",
                f"runs/{manifest.run_id}/manifest.artifact_refs",
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


def _read_config_source_summary(
    *, storage: RunStore, run_id: str
) -> RunComparisonConfigSourceSummary:
    config_path = storage.ref_path(run_id, CONFIG_PROFILE_SNAPSHOT_REF)
    if not config_path.is_file():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_run_comparison_input",
                    f"run comparison input is missing: {CONFIG_PROFILE_SNAPSHOT_REF}",
                    CONFIG_PROFILE_SNAPSHOT_REF,
                )
            ]
        )
    try:
        config = ConfigProfileSnapshot.model_validate_json(config_path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_run_comparison_input",
                    "run comparison input is not valid JSON for "
                    f"{CONFIG_PROFILE_SNAPSHOT_REF}",
                    CONFIG_PROFILE_SNAPSHOT_REF,
                )
            ]
        ) from error
    source = config.source
    if source is None or source.kind != "config_registry_entry":
        return RunComparisonConfigSourceSummary(status="not_available")
    provenance = ConfigRegistryConfigSourceProvenance(
        selector=source.selector or "",
        entry_id=source.entry_id or "",
        config_ref=source.config_ref or "",
        active_state_ref=source.active_state_ref,
        active_record_id=source.active_record_id,
    )
    return RunComparisonConfigSourceSummary(
        status="available",
        source_kind=provenance.source_kind,
        selector=provenance.selector,
        entry_id=provenance.entry_id,
        config_ref=provenance.config_ref,
        active_state_ref=provenance.active_state_ref,
        active_record_id=provenance.active_record_id,
    )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
