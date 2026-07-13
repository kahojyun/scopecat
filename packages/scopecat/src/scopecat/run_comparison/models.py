"""Run comparison durable and view models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.kernel.problems import Problem
from scopecat.records.measurement import CoordinateValue
from scopecat.records.parameter import Quantity
from scopecat.records.run import RunConfigSource, utc_now

RUN_COMPARISON_RESULT_SCHEMA_VERSION = "scopecat.run_comparison_result.v5"
RUN_COMPARISON_REVIEW_RECORD_SCHEMA_VERSION = "scopecat.run_comparison_review_record.v2"

ComparisonOutcome = Literal["increased", "unchanged", "decreased"]
RunComparisonReviewState = Literal["accepted", "rejected"]
RunComparisonReviewStatus = Literal["reviewed", "not_reviewed"]


class RunComparisonPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    baseline_coordinates: dict[str, CoordinateValue]
    candidate_coordinates: dict[str, CoordinateValue]
    baseline_value: Quantity
    candidate_value: Quantity
    value_delta: Quantity


class RunComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_comparison_result.v5"] = (
        RUN_COMPARISON_RESULT_SCHEMA_VERSION
    )
    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    observable_id: str
    baseline_config_source: RunConfigSource | None = None
    candidate_config_source: RunConfigSource | None = None
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
    problems: tuple[Problem, ...] = ()
    generated_at: datetime = Field(default_factory=utc_now)


class RunComparisonView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    observable_id: str
    outcome: ComparisonOutcome
    candidate_run_id: str
    peak_value_delta: Quantity
    review_status: RunComparisonReviewStatus


class RunComparisonReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_comparison_review_record.v2"] = (
        RUN_COMPARISON_REVIEW_RECORD_SCHEMA_VERSION
    )
    run_id: str
    comparison_id: str
    decision: RunComparisonReviewState
    reviewer: str
    note: str = ""
    reviewed_at: datetime = Field(default_factory=utc_now)
