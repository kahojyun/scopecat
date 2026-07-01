"""Run overview view models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import Artifact
from scopecat.models.parameter import ParameterPatch, Quantity
from scopecat.models.run import utc_now

SectionStatus = Literal["available", "not_available"]
ReviewStatus = Literal["reviewed", "not_reviewed"]


class RunHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    runner_id: str
    dry_run: bool
    experiment_ref: str
    created_at: datetime
    workspace_ref: str
    device_ref: str


class ConfigSourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SectionStatus
    source_kind: str | None = None
    selector: str | None = None
    entry_id: str | None = None
    config_ref: str | None = None
    active_state_ref: str | None = None
    active_record_id: str | None = None


class AnalysisRecordEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    ref: str
    title: str
    output_kinds: list[str]
    parameter_change_count: int
    source_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)


class ParameterChangeDecisionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    decision_ref: str | None = None
    decision: str | None = None
    actor: str | None = None
    note: str | None = None
    decided_at: datetime | None = None


class ParameterChangeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    ref: str
    source_run_id: str
    reason: str
    confidence: float | None = None
    patches: list[ParameterPatch]
    decision_info: ParameterChangeDecisionInfo


class RunComparisonEntry(BaseModel):
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


class RunOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_overview.v1"
    run_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    run: RunHeader
    config_source: ConfigSourceInfo
    artifact_refs: list[Artifact]
    analysis_records: list[AnalysisRecordEntry] = Field(default_factory=list)
    parameter_changes: list[ParameterChangeEntry] = Field(default_factory=list)
    run_comparisons: list[RunComparisonEntry] = Field(default_factory=list)
