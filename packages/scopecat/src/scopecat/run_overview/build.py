"""Stable local run overview assembly.

Run overviews are assembled from the persisted run manifest plus the optional
workflow records registered on that run: analysis records, parameter
changes and decisions, run comparisons and reviews, and config source
coordinates. Missing optional records are omitted from the overview instead of
being treated as part of the required run contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import BaseModel, ValidationError

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.analysis import AnalysisRecord
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.parameter import ParameterChangeSet
from scopecat.models.run import RunManifest
from scopecat.parameter_changes import (
    ParameterChangeDecisionRecord,
    parameter_change_decision_ref,
)
from scopecat.run_comparison import (
    RunComparisonResult,
    RunComparisonReviewRecord,
)
from scopecat.run_overview.models import (
    AnalysisRecordEntry,
    ParameterChangeDecisionInfo,
    ParameterChangeEntry,
    RunComparisonEntry,
    RunHeader,
    RunOverview,
)
from scopecat.runs import RunStore, list_records, open_run_store
from scopecat.runs.access import record_storage_ref, storage_ref


def build_run_overview(*, run_id: str, workspace: str | Path) -> RunOverview:
    workspace_path = Path(workspace)
    storage = open_run_store(workspace_path)
    manifest = storage.read_manifest(run_id)
    _validate_manifest_entries(storage=storage, run_id=run_id, manifest=manifest)

    analysis_records = _read_analysis_records(
        storage=storage,
        run_id=run_id,
        manifest=manifest,
    )
    parameter_changes = _read_parameter_changes(
        storage=storage, run_id=run_id, manifest=manifest
    )
    run_comparisons = _read_run_comparisons(
        storage=storage, run_id=run_id, manifest=manifest
    )
    return RunOverview(
        run_id=run_id,
        run=RunHeader(
            run_id=manifest.run_id,
            status=manifest.status,
            created_at=manifest.created_at,
        ),
        config_source=manifest.config_source,
        analysis_records=analysis_records,
        parameter_changes=parameter_changes,
        run_comparisons=run_comparisons,
    )


def _read_analysis_records(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[AnalysisRecordEntry]:
    records: list[AnalysisRecordEntry] = []
    for record in _records_by_kind(manifest, "analysis"):
        record_ref = record_storage_ref(record)
        payload = _read_model(
            storage.ref_path(run_id, record_ref),
            AnalysisRecord,
            record_ref,
        )
        records.append(
            AnalysisRecordEntry(
                id=record.id,
                title=payload.title,
                output_kinds=[output.kind for output in payload.outputs],
                parameter_change_count=len(payload.parameter_changes),
                input_ids=_input_ids(payload),
                output_ids=_output_ids(payload),
            )
        )
    return records


def _read_parameter_changes(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[ParameterChangeEntry]:
    changes: list[ParameterChangeEntry] = []
    for change_record in list_records(manifest, kind="parameter_change_set"):
        change_record_ref = record_storage_ref(change_record)
        change_path = storage.ref_path(run_id, change_record_ref)
        change_set = _read_model(
            change_path,
            ParameterChangeSet,
            change_record_ref,
        )
        decision_info = _read_parameter_change_decision(
            storage=storage,
            run_id=run_id,
            change_set=change_set,
        )
        changes.append(
            ParameterChangeEntry(
                id=change_set.id,
                source_run_id=change_set.source_run_id,
                reason=change_set.reason,
                confidence=change_set.confidence,
                patches=list(change_set.patches),
                decision_info=decision_info,
            )
        )
    return changes


def _read_parameter_change_decision(
    *, storage: RunStore, run_id: str, change_set: ParameterChangeSet
) -> ParameterChangeDecisionInfo:
    decision_ref = parameter_change_decision_ref(change_set.id)
    decision_path = storage.ref_path(run_id, decision_ref)
    if not decision_path.exists():
        return ParameterChangeDecisionInfo(status="not_reviewed")
    decision = _read_model(decision_path, ParameterChangeDecisionRecord, decision_ref)
    return ParameterChangeDecisionInfo(
        status="reviewed",
        decision=decision.decision,
        actor=decision.actor,
        note=decision.note,
        decided_at=decision.decided_at,
    )


def _read_run_comparisons(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[RunComparisonEntry]:
    comparisons: list[RunComparisonEntry] = []
    for record in _records_by_kind(manifest, "run_comparison_result"):
        result_ref = record_storage_ref(record)
        result = _read_model(
            storage.ref_path(run_id, result_ref),
            RunComparisonResult,
            result_ref,
        )
        review_record_id = f"{result.comparison_id}-review"
        review_record = next(
            (
                candidate
                for candidate in manifest.records
                if candidate.id == review_record_id
            ),
            None,
        )
        review_ref = (
            record_storage_ref(review_record) if review_record is not None else None
        )
        review_path = (
            storage.ref_path(run_id, review_ref) if review_ref is not None else None
        )
        review: RunComparisonReviewRecord | None = None
        if review_path is not None and review_path.exists():
            review = _read_model(
                review_path,
                RunComparisonReviewRecord,
                review_ref or review_record_id,
            )
        comparisons.append(
            RunComparisonEntry(
                comparison_id=result.comparison_id,
                baseline_run_id=result.baseline_run_id,
                candidate_run_id=result.candidate_run_id,
                observable_id=result.observable_id,
                outcome=result.outcome,
                measurement_count=result.measurement_count,
                baseline_peak_point_index=result.baseline_peak_point_index,
                candidate_peak_point_index=result.candidate_peak_point_index,
                baseline_peak_value=result.baseline_peak_value,
                candidate_peak_value=result.candidate_peak_value,
                peak_value_delta=result.peak_value_delta,
                mean_value_delta=result.mean_value_delta,
                value_unit=result.value_unit,
                baseline_config_source=result.baseline_config_source,
                candidate_config_source=result.candidate_config_source,
                review_status="reviewed" if review is not None else "not_reviewed",
                decision=review.decision if review is not None else None,
                reviewer=review.reviewer if review is not None else None,
                note=review.note if review is not None else None,
                reviewed_at=review.reviewed_at if review is not None else None,
                generated_at=result.generated_at,
            )
        )
    return comparisons


def _records_by_kind(manifest: RunManifest, kind: str) -> list[RunRecordEntry]:
    return sorted(
        list_records(manifest, kind=kind),
        key=lambda record: record.id,
    )


def _read_model[TModel: BaseModel](
    path: Path, model_type: type[TModel], ref: str
) -> TModel:
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_overview_input",
                    f"overview input is missing: {ref}",
                    ref,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "overview_input_is_directory",
                    f"overview input is a directory: {ref}",
                    ref,
                )
            ]
        )
    try:
        return model_type.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_overview_input",
                    f"overview input is not valid JSON for {ref}",
                    ref,
                )
            ]
        ) from error


def _validate_manifest_entries(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> None:
    entries = [*manifest.artifacts, *manifest.datasets, *manifest.records]
    for entry in entries:
        entry_storage_ref = storage_ref(entry)
        path = storage.ref_path(run_id, entry_storage_ref)
        if path.exists() and path.is_dir():
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "overview_ref_is_directory",
                        f"overview input is a directory: {entry_storage_ref}",
                        "manifest",
                    )
                ]
            )


def _input_ids(payload: AnalysisRecord) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for input_ref in payload.inputs:
        key = f"{input_ref.kind}:{input_ref.target}"
        if key in seen:
            continue
        ids.append(key)
        seen.add(key)
    return ids


def _output_ids(payload: AnalysisRecord) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for output in payload.outputs:
        if output.kind != "artifact" or not isinstance(output.content, dict):
            continue
        content = cast(dict[str, object], output.content)
        artifact_id = content.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in seen:
            continue
        ids.append(artifact_id)
        seen.add(artifact_id)
    return ids


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
