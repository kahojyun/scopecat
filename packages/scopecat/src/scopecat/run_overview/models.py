"""Run overview view models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.models.config import ConfigContentHash
from scopecat.models.parameter import Quantity
from scopecat.models.parameter_change import ParameterValueDelta
from scopecat.models.run import RunConfigSource, utc_now

ReviewStatus = Literal["reviewed", "not_reviewed"]
ParameterChangeDecision = Literal["approved", "rejected", "invalidated"]


class RunHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    created_at: datetime


class RuntimeExecutionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_point_count: int | None = None
    compute_evaluated_node_count: int = 0
    compute_reused_node_count: int = 0
    compute_payload_count: int = 0


class StateExecutionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    payload_count: int = 0


class ExecutionOverviewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    status: str
    point_count: int
    measurement_count: int
    instrument_ids: list[str]
    problem_count: int
    runtime: RuntimeExecutionEntry = Field(default_factory=RuntimeExecutionEntry)
    state: StateExecutionEntry = Field(default_factory=StateExecutionEntry)


class DatasetVariableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    dtype: str
    unit: str | None = None
    dims: list[str] = Field(default_factory=list)
    shape: list[int] = Field(default_factory=list)


class DatasetOverviewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    role: str | None = None
    record_count: int | None = None
    coordinate_ids: list[str] = Field(default_factory=list)
    observable_ids: list[str] = Field(default_factory=list)
    dimensions: dict[str, int] = Field(default_factory=dict)
    variables: list[DatasetVariableEntry] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class AnalysisRecordEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    output_kinds: list[str]
    parameter_change_proposal_count: int
    input_ids: list[str] = Field(default_factory=list)
    output_ids: list[str] = Field(default_factory=list)


class ParameterChangeDecisionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    decision: ParameterChangeDecision
    actor: str
    note: str = ""
    related_refs: list[str] = Field(default_factory=list)
    decided_at: datetime


class ParameterChangeDecisionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    decision: ParameterChangeDecision | None = None
    actor: str | None = None
    note: str | None = None
    decided_at: datetime | None = None
    history: list[ParameterChangeDecisionEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_latest_event(self) -> ParameterChangeDecisionInfo:
        if not self.history:
            if self.status != "not_reviewed" or any(
                value is not None
                for value in (
                    self.decision,
                    self.actor,
                    self.note,
                    self.decided_at,
                )
            ):
                msg = "unreviewed parameter proposal must not expose a decision"
                raise ValueError(msg)
            return self
        latest = self.history[-1]
        if self.status != "reviewed" or (
            self.decision,
            self.actor,
            self.note,
            self.decided_at,
        ) != (
            latest.decision,
            latest.actor,
            latest.note,
            latest.decided_at,
        ):
            msg = "parameter proposal decision summary must match its latest event"
            raise ValueError(msg)
        return self


class ParameterChangeProposalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_run_id: str
    base_config_id: str
    base_config_content_hash: ConfigContentHash
    reason: str
    confidence: float | None = None
    candidate_snapshot_id: str
    deltas: list[ParameterValueDelta]
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
    baseline_config_source: RunConfigSource | None = None
    candidate_config_source: RunConfigSource | None = None
    review_status: ReviewStatus
    decision: str | None = None
    reviewer: str | None = None
    note: str | None = None
    reviewed_at: datetime | None = None
    generated_at: datetime


class RunOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_overview.v4"] = "scopecat.run_overview.v4"
    run_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    run: RunHeader
    config_source: RunConfigSource | None = None
    execution: ExecutionOverviewEntry | None = None
    datasets: list[DatasetOverviewEntry] = Field(default_factory=list)
    analysis_records: list[AnalysisRecordEntry] = Field(default_factory=list)
    parameter_change_proposals: list[ParameterChangeProposalEntry] = Field(
        default_factory=list
    )
    run_comparisons: list[RunComparisonEntry] = Field(default_factory=list)
