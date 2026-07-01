"""Run comparison durable and view models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic
from scopecat.models.artifact import Artifact
from scopecat.models.parameter import Quantity
from scopecat.models.run import utc_now

RUN_COMPARISON_JOB_SCHEMA_VERSION = "scopecat.run_comparison_job.v1"
RUN_COMPARISON_RESULT_SCHEMA_VERSION = "scopecat.run_comparison_result.v0"
RUN_COMPARISON_REVIEW_RECORD_SCHEMA_VERSION = "scopecat.run_comparison_review_record.v0"

SectionStatus = Literal["available", "not_available"]
ComparisonOutcome = Literal["increased", "unchanged", "decreased"]
RunComparisonReviewState = Literal["accepted", "rejected"]
RunComparisonReviewStatus = Literal["reviewed", "not_reviewed"]


class RunComparisonConfigSourceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus
    source_kind: str | None = None
    selector: str | None = None
    entry_id: str | None = None
    config_ref: str | None = None
    active_state_ref: str | None = None
    active_record_id: str | None = None


class RunComparisonPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    baseline_coordinates: dict[str, Quantity]
    candidate_coordinates: dict[str, Quantity]
    baseline_value: Quantity
    candidate_value: Quantity
    value_delta: Quantity


class RunComparisonJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUN_COMPARISON_JOB_SCHEMA_VERSION
    id: str
    baseline_run_id: str
    candidate_run_id: str
    observable_id: str
    baseline_input_artifact_ids: list[str]
    candidate_input_artifact_ids: list[str]
    input_record_refs: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str]
    output_artifacts: list[Artifact] = Field(default_factory=list)
    status: str = "completed"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class RunComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUN_COMPARISON_RESULT_SCHEMA_VERSION
    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    observable_id: str
    baseline_data_ref: str
    candidate_data_ref: str
    baseline_analysis_artifact_ids: list[str] = Field(default_factory=list)
    candidate_analysis_artifact_ids: list[str] = Field(default_factory=list)
    baseline_config_source: RunComparisonConfigSourceSummary
    candidate_config_source: RunComparisonConfigSourceSummary
    job_ref: str
    result_ref: str
    artifact_refs: list[Artifact] = Field(default_factory=list)
    measurement_count: int
    baseline_peak_point_index: int
    candidate_peak_point_index: int
    baseline_peak_value: Quantity
    candidate_peak_value: Quantity
    peak_value_delta: Quantity
    mean_value_delta: Quantity
    value_unit: str
    outcome: ComparisonOutcome
    points: list[RunComparisonPoint]
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class RunComparisonView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    observable_id: str
    outcome: ComparisonOutcome
    candidate_run_id: str
    peak_value_delta: Quantity
    review_status: RunComparisonReviewStatus
    path: str


class RunComparisonReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUN_COMPARISON_REVIEW_RECORD_SCHEMA_VERSION
    run_id: str
    comparison_id: str
    comparison_ref: str
    decision: RunComparisonReviewState
    reviewer: str
    note: str = ""
    reviewed_at: datetime = Field(default_factory=utc_now)
