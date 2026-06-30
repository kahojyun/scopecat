"""Run report durable and view models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic
from scopecat.models.artifact import Artifact
from scopecat.models.parameter import Quantity
from scopecat.models.run import utc_now

SectionStatus = Literal["available", "not_available"]
ReviewStatus = Literal["reviewed", "not_reviewed"]


class ReportJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.report_job.v0"
    id: str = "run-report"
    run_id: str
    input_refs: list[str]
    output_refs: list[str]
    status: str = "completed"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class ReportRunInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    runner_id: str
    dry_run: bool
    experiment_ref: str
    created_at: datetime
    workspace_ref: str
    device_ref: str


class ConfigSourceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus
    source_kind: str | None = None
    selector: str | None = None
    entry_id: str | None = None
    config_ref: str | None = None
    active_state_ref: str | None = None
    active_record_id: str | None = None


class ProcessingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ref: str
    step: str
    scope: str | None = None
    job_status: str
    input_artifact_ids: list[str]
    input_record_refs: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str]
    result_artifact_ids: list[str] = Field(default_factory=list)
    summary_artifact_ids: list[str] = Field(default_factory=list)
    result_artifacts: list[Artifact] = Field(default_factory=list)
    summary_artifacts: list[Artifact] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ref: str
    step: str
    scope: str | None = None
    job_status: str
    input_artifact_ids: list[str]
    input_record_refs: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str]
    result_artifact_ids: list[str] = Field(default_factory=list)
    summary_artifact_ids: list[str] = Field(default_factory=list)
    result_artifacts: list[Artifact] = Field(default_factory=list)
    summary_artifacts: list[Artifact] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    proposal_artifact_ids: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class AnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    ref: str
    title: str
    output_kinds: list[str]
    guess_count: int
    source_artifact_ids: list[str] = Field(default_factory=list)


class ProposalReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    review_ref: str | None = None
    decision: str | None = None
    reviewer: str | None = None
    note: str | None = None
    reviewed_at: datetime | None = None


class ProposalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ref: str
    state: str
    operation_kind: str
    parameter_id: str | None = None
    old_value: Quantity | None = None
    value: Quantity | None = None
    source_run_id: str
    reason: str
    confidence: float | None = None
    review: ProposalReviewReport


class RunComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    observable_id: str
    outcome: str
    measurement_count: int
    baseline_peak_point_index: int
    candidate_peak_point_index: int
    baseline_peak_value: Quantity
    candidate_peak_value: Quantity
    peak_value_delta: Quantity
    mean_value_delta: Quantity
    value_unit: str
    result_ref: str
    summary_ref: str
    job_ref: str
    baseline_config_source_status: SectionStatus
    candidate_config_source_status: SectionStatus
    review_status: ReviewStatus
    review_ref: str | None = None
    decision: str | None = None
    reviewer: str | None = None
    note: str | None = None
    reviewed_at: datetime | None = None
    generated_at: datetime


class RunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_report.v0"
    run_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    run: ReportRunInfo
    config_source: ConfigSourceReport
    artifact_refs: list[Artifact]
    analysis: list[AnalysisReport] = Field(default_factory=list)
    processing: list[ProcessingReport] = Field(default_factory=list)
    evaluation: list[EvaluationReport] = Field(default_factory=list)
    proposals: list[ProposalReport] = Field(default_factory=list)
    run_comparisons: list[RunComparisonReport] = Field(default_factory=list)
