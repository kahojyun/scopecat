"""Stable local run overview assembly.

Run overviews are assembled from the persisted run manifest plus the optional
workflow records registered on that run: analysis artifacts, parameter
proposals and reviews, run comparisons and reviews, and config registry
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
from scopecat.models.parameter import ParameterChangeSet, Quantity
from scopecat.models.run import RunManifest
from scopecat.proposals.review import ProposalReviewRecord
from scopecat.reporting.models import (
    AnalysisRecordOverview,
    AnalysisReportOverview,
    ConfigSourceReport,
    ProposalReport,
    ProposalReviewReport,
    ReportRunInfo,
    RunComparisonReport,
    RunOverview,
)
from scopecat.run_comparison import (
    RunComparisonJob,
    RunComparisonResult,
    RunComparisonReviewRecord,
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
    proposals: list[Any] = Field(default_factory=list)


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
    analysis_reports = _read_analysis_reports(manifest)
    proposals = _read_proposals(storage=storage, run_id=run_id, manifest=manifest)
    run_comparisons = _read_run_comparisons(
        storage=storage, run_id=run_id, manifest=manifest
    )
    return RunOverview(
        run_id=run_id,
        run=ReportRunInfo(
            run_id=manifest.run_id,
            status=manifest.status,
            runner_id=manifest.runner_id,
            dry_run=manifest.dry_run,
            experiment_ref=manifest.experiment_ref,
            created_at=manifest.created_at,
            workspace_ref=manifest.workspace_ref,
            device_ref=manifest.device_ref,
        ),
        config_source=config_source,
        artifact_refs=list(manifest.artifact_refs),
        analysis_records=analysis_records,
        analysis_reports=analysis_reports,
        proposals=proposals,
        run_comparisons=run_comparisons,
    )


def _read_analysis_records(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[AnalysisRecordOverview]:
    records: list[AnalysisRecordOverview] = []
    for artifact in _artifacts_by_kind(manifest, "analysis"):
        payload = _read_model(
            storage.ref_path(run_id, artifact.path),
            _AnalysisArtifactPayload,
            artifact.path,
        )
        records.append(
            AnalysisRecordOverview(
                artifact_id=artifact.id,
                ref=artifact.path,
                title=payload.title,
                output_kinds=[output.kind for output in payload.outputs],
                proposal_count=len(payload.proposals),
                source_artifact_ids=_source_artifact_ids(payload, artifact),
                report_artifact_ids=_report_artifact_ids(payload),
            )
        )
    return records


def _read_analysis_reports(manifest: RunManifest) -> list[AnalysisReportOverview]:
    reports: list[AnalysisReportOverview] = []
    for artifact in _artifacts_by_kind(manifest, "analysis_report"):
        report_title = artifact.metadata.get("report_title")
        source_analysis_artifact_id = artifact.metadata.get(
            "source_analysis_artifact_id"
        )
        source_artifact_ids = artifact.metadata.get("source_artifact_ids")
        reports.append(
            AnalysisReportOverview(
                artifact_id=artifact.id,
                ref=artifact.path,
                title=report_title if isinstance(report_title, str) else artifact.id,
                media_type=artifact.media_type,
                source_analysis_artifact_id=(
                    source_analysis_artifact_id
                    if isinstance(source_analysis_artifact_id, str)
                    else None
                ),
                source_artifact_ids=(
                    _unique_strings(cast(Sequence[object], source_artifact_ids))
                    if isinstance(source_artifact_ids, list)
                    else []
                ),
            )
        )
    return reports


def _read_config_source(*, storage: RunStore, run_id: str) -> ConfigSourceReport:
    config = _read_model(
        storage.ref_path(run_id, CONFIG_PROFILE_SNAPSHOT_REF),
        ConfigProfileSnapshot,
        CONFIG_PROFILE_SNAPSHOT_REF,
    )
    source = config.source
    if source is None or source.kind != "config_registry_entry":
        return ConfigSourceReport(status="not_available")
    provenance = ConfigRegistryConfigSourceProvenance(
        selector=source.selector or "",
        entry_id=source.entry_id or "",
        config_ref=source.config_ref or "",
        active_state_ref=source.active_state_ref,
        active_record_id=source.active_record_id,
    )
    return _config_source_report_from_provenance(provenance)


def _config_source_report_from_provenance(
    provenance: ConfigRegistryConfigSourceProvenance,
) -> ConfigSourceReport:
    return ConfigSourceReport(
        status="available",
        source_kind=provenance.source_kind,
        selector=provenance.selector,
        entry_id=provenance.entry_id,
        config_ref=provenance.config_ref,
        active_state_ref=provenance.active_state_ref,
        active_record_id=provenance.active_record_id,
    )


def _read_proposals(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[ProposalReport]:
    proposals: list[ProposalReport] = []
    for proposal_artifact in list_artifacts(manifest, kind="parameter_change_set"):
        proposal_record_ref = proposal_artifact.path
        proposal_path = storage.ref_path(run_id, proposal_record_ref)
        proposal = _read_model(
            proposal_path,
            ParameterChangeSet,
            proposal_record_ref,
        )
        review = _read_review(storage=storage, run_id=run_id, proposal=proposal)
        patch = proposal.patches[0] if proposal.patches else None
        proposals.append(
            ProposalReport(
                id=proposal.id,
                ref=proposal_record_ref,
                state=proposal.state,
                operation_kind=patch.kind if patch is not None else "none",
                parameter_id=patch.parameter_id if patch is not None else None,
                old_value=(
                    patch.expected_value
                    if patch is not None and isinstance(patch.expected_value, Quantity)
                    else None
                ),
                value=(
                    patch.value
                    if patch is not None and isinstance(patch.value, Quantity)
                    else None
                ),
                source_run_id=proposal.source_run_id,
                reason=proposal.reason,
                confidence=proposal.confidence,
                review=review,
            )
        )
    return proposals


def _read_review(
    *, storage: RunStore, run_id: str, proposal: ParameterChangeSet
) -> ProposalReviewReport:
    review_ref = f"reviews/{proposal.id}.review.json"
    review_path = storage.ref_path(run_id, review_ref)
    if not review_path.exists():
        return ProposalReviewReport(status="not_reviewed")
    review = _read_model(review_path, ProposalReviewRecord, review_ref)
    return ProposalReviewReport(
        status="reviewed",
        review_ref=review_ref,
        decision=review.decision,
        reviewer=review.reviewer,
        note=review.note,
        reviewed_at=review.reviewed_at,
    )


def _read_run_comparisons(
    *, storage: RunStore, run_id: str, manifest: RunManifest
) -> list[RunComparisonReport]:
    comparisons: list[RunComparisonReport] = []
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
            RunComparisonReport(
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
                summary_ref=result.summary_ref,
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
                    "missing_report_input",
                    f"report input is missing: {ref}",
                    ref,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "report_artifact_is_directory",
                    f"report input is a directory: {ref}",
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
                    "invalid_report_input",
                    f"report input is not valid JSON for {ref}",
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
                        "report_artifact_is_directory",
                        f"report artifact is a directory: {artifact.path}",
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


def _report_artifact_ids(payload: _AnalysisArtifactPayload) -> list[str]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for output in payload.outputs:
        if output.kind != "report" or not isinstance(output.content, dict):
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
