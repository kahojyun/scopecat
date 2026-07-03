"""Stable local run overview assembly.

Run overviews are assembled from the persisted run manifest plus the optional
workflow records registered on that run: analysis artifacts, parameter
changes and decisions, run comparisons and reviews, and config registry
provenance. Missing optional records are omitted from the overview instead of
being treated as part of the required run contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, ValidationError

from scopecat.config_registry import ConfigRegistryConfigSourceProvenance
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import ParameterChangeSet
from scopecat.models.run import RunManifest
from scopecat.parameter_changes import (
    ParameterChangeDecisionRecord,
    parameter_change_decision_ref,
)
from scopecat.run_comparison import (
    RunComparisonJob,
    RunComparisonResult,
    RunComparisonReviewRecord,
)
from scopecat.run_overview.models import (
    AnalysisRecordEntry,
    ConfigSourceInfo,
    ParameterChangeDecisionInfo,
    ParameterChangeEntry,
    RunComparisonEntry,
    RunHeader,
    RunOverview,
)
from scopecat.runs import RunStore, list_artifacts, open_run_store

CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"


class _AnalysisOutputPayload(BaseModel):
    kind: str
    title: str
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class _AnalysisInputPayload(BaseModel):
    target: str
    target_type: str
    role: str
    title: str | None = None
    artifact_kind: str | None = None
    path: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


class _AnalysisArtifactPayload(BaseModel):
    schema_version: str
    run_id: str
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: list[_AnalysisInputPayload] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    outputs: list[_AnalysisOutputPayload]
    parameter_changes: list[Any] = Field(default_factory=list)


def build_run_overview(*, run_id: str, workspace: str | Path) -> RunOverview:
    workspace_path = Path(workspace)
    storage = open_run_store(workspace_path)
    manifest = storage.read_manifest(run_id)
    _validate_manifest_artifacts(storage=storage, run_id=run_id, manifest=manifest)

    config_source = _read_config_source(storage=storage, run_id=run_id)
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
        config_source=config_source,
        artifact_refs=list(manifest.artifact_refs),
        analysis_records=analysis_records,
        parameter_changes=parameter_changes,
        run_comparisons=run_comparisons,
    )


def _read_analysis_records(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[AnalysisRecordEntry]:
    records: list[AnalysisRecordEntry] = []
    for artifact in _artifacts_by_kind(manifest, "analysis"):
        payload = _read_model(
            storage.ref_path(run_id, artifact.path),
            _AnalysisArtifactPayload,
            artifact.path,
        )
        records.append(
            AnalysisRecordEntry(
                artifact_id=artifact.id,
                ref=artifact.path,
                title=payload.title,
                output_kinds=[output.kind for output in payload.outputs],
                parameter_change_count=len(payload.parameter_changes),
                source_artifact_ids=_source_artifact_ids(payload, artifact),
                output_artifact_ids=_output_artifact_ids(payload),
            )
        )
    return records


def _read_config_source(*, storage: RunStore, run_id: str) -> ConfigSourceInfo:
    config = _read_model(
        storage.ref_path(run_id, CONFIG_PROFILE_SNAPSHOT_REF),
        ConfigProfileSnapshot,
        CONFIG_PROFILE_SNAPSHOT_REF,
    )
    source = config.source
    if source is None or source.kind != "config_registry_entry":
        return ConfigSourceInfo(status="not_available")
    provenance = ConfigRegistryConfigSourceProvenance(
        selector=source.selector or "",
        entry_id=source.entry_id or "",
        config_ref=source.config_ref or "",
        active_state_ref=source.active_state_ref,
        active_record_id=source.active_record_id,
    )
    return _config_source_info_from_provenance(provenance)


def _config_source_info_from_provenance(
    provenance: ConfigRegistryConfigSourceProvenance,
) -> ConfigSourceInfo:
    return ConfigSourceInfo(
        status="available",
        source_kind=provenance.source_kind,
        selector=provenance.selector,
        entry_id=provenance.entry_id,
        config_ref=provenance.config_ref,
        active_state_ref=provenance.active_state_ref,
        active_record_id=provenance.active_record_id,
    )


def _read_parameter_changes(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[ParameterChangeEntry]:
    changes: list[ParameterChangeEntry] = []
    for change_artifact in list_artifacts(manifest, kind="parameter_change_set"):
        change_record_ref = change_artifact.path
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
                ref=change_record_ref,
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
        decision_ref=decision_ref,
        decision=decision.decision,
        actor=decision.actor,
        note=decision.note,
        decided_at=decision.decided_at,
    )


def _read_run_comparisons(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[RunComparisonEntry]:
    comparisons: list[RunComparisonEntry] = []
    for artifact in _artifacts_by_kind(manifest, "run_comparison_result"):
        result = _read_model(
            storage.ref_path(run_id, artifact.path),
            RunComparisonResult,
            artifact.path,
        )
        job_ref = f"comparisons/{result.comparison_id}.job.json"
        _read_model(
            storage.ref_path(run_id, job_ref),
            RunComparisonJob,
            job_ref,
        )
        review_ref = f"reviews/{result.comparison_id}.review.json"
        review_path = storage.ref_path(run_id, review_ref)
        review: RunComparisonReviewRecord | None = None
        if review_path.exists():
            review = _read_model(
                review_path,
                RunComparisonReviewRecord,
                review_ref,
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
                result_ref=artifact.path,
                job_ref=job_ref,
                baseline_config_source_status=result.baseline_config_source.status,
                candidate_config_source_status=result.candidate_config_source.status,
                review_status="reviewed" if review is not None else "not_reviewed",
                review_ref=review_ref if review is not None else None,
                decision=review.decision if review is not None else None,
                reviewer=review.reviewer if review is not None else None,
                note=review.note if review is not None else None,
                reviewed_at=review.reviewed_at if review is not None else None,
                generated_at=result.generated_at,
            )
        )
    return comparisons


def _artifacts_by_kind(manifest: RunManifest, kind: str) -> list[Artifact]:
    return sorted(
        (artifact for artifact in manifest.artifact_refs if artifact.kind == kind),
        key=lambda artifact: artifact.id,
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


def _validate_manifest_artifacts(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> None:
    for artifact in manifest.artifact_refs:
        path = storage.ref_path(run_id, artifact.path)
        if path.exists() and path.is_dir():
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "overview_artifact_is_directory",
                        f"overview artifact is a directory: {artifact.path}",
                        "artifact_refs",
                    )
                ]
            )


def _source_artifact_ids(
    payload: _AnalysisArtifactPayload,
    artifact: Artifact,
) -> list[str]:
    if payload.source_artifact_ids:
        return _unique_strings(payload.source_artifact_ids)
    input_artifact_ids = _input_artifact_ids(payload)
    if input_artifact_ids:
        return input_artifact_ids
    metadata_ids = artifact.metadata.get("source_artifact_ids")
    if isinstance(metadata_ids, list):
        selected = _unique_strings(cast(Sequence[object], metadata_ids))
        if selected:
            return selected
    return []


def _input_artifact_ids(payload: _AnalysisArtifactPayload) -> list[str]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for input_ref in payload.inputs:
        if input_ref.target_type != "artifact" or input_ref.target in seen:
            continue
        artifact_ids.append(input_ref.target)
        seen.add(input_ref.target)
    return artifact_ids


def _output_artifact_ids(payload: _AnalysisArtifactPayload) -> list[str]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for output in payload.outputs:
        if output.kind != "artifact" or not isinstance(output.content, dict):
            continue
        content = cast(dict[str, object], output.content)
        target = content.get("target")
        if not isinstance(target, str) or target in seen:
            continue
        artifact_ids.append(target)
        seen.add(target)
    return artifact_ids


def _unique_strings(values: Sequence[object]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or value in seen:
            continue
        selected.append(value)
        seen.add(value)
    return selected


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
