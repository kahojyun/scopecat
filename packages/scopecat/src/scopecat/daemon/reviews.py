"""Transient experiment-review models shared by notebook, daemon, and GUI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.control.models import (
    PointCoordinateKind,
    PointCoordinateSpec,
    PointCoordinateValue,
)
from scopecat.daemon.points import RunDomainFragmentView
from scopecat.inspection import CompiledArtifactInspection

type ReviewCoordinateValue = PointCoordinateValue
type ReviewCoordinateKind = PointCoordinateKind
type ReviewCoordinateMode = Literal["exact", "snap", "free"]
ReviewCoordinateSpec = PointCoordinateSpec


class _ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewPointView(_ReviewModel):
    point_index: int | None = Field(default=None, ge=0)
    coordinates: dict[str, ReviewCoordinateValue]
    proposal_fingerprint: str | None = None
    source: Literal["author", "optimizer", "operator"] = "author"


class ReviewInspectionView(_ReviewModel):
    operation_id: str
    point_index: int | None = Field(default=None, ge=0)
    target_id: str
    artifact_id: str
    artifact_fingerprint: str
    content: CompiledArtifactInspection


class ReviewCompilationResult(_ReviewModel):
    request_id: str = Field(min_length=1)
    completed_at: datetime
    point: ReviewPointView | None = None
    inspections: tuple[ReviewInspectionView, ...] = ()
    error: str | None = None


class ReviewSessionCreateCommand(_ReviewModel):
    session_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    experiment_kind: str = Field(min_length=1)
    coordinates: tuple[PointCoordinateSpec, ...]
    planned_points: tuple[ReviewPointView, ...] = ()
    planned_points_truncated: bool = False
    initial_result: ReviewCompilationResult | None = None


class ReviewCompileCommand(_ReviewModel):
    point_index: int | None = Field(default=None, ge=0)
    coordinates: dict[str, ReviewCoordinateValue] | None = None
    coordinate_mode: ReviewCoordinateMode = "exact"

    @model_validator(mode="after")
    def validate_selector(self) -> ReviewCompileCommand:
        if (self.point_index is None) == (self.coordinates is None):
            raise ValueError("select a review point by index or coordinates")
        if self.coordinate_mode == "free" and self.coordinates is None:
            raise ValueError("free review compilation requires coordinates")
        return self


class ReviewCompileReceipt(_ReviewModel):
    session_id: str
    request_id: str
    state: Literal["queued"] = "queued"


class ReviewWorkItem(_ReviewModel):
    session_id: str
    request_id: str
    point_index: int | None = Field(default=None, ge=0)
    coordinates: dict[str, ReviewCoordinateValue] | None = None
    coordinate_mode: ReviewCoordinateMode


class ReviewCompletionCommand(_ReviewModel):
    worker_id: str = Field(min_length=1)
    result: ReviewCompilationResult


class ReviewSessionView(_ReviewModel):
    session_id: str
    title: str
    experiment_id: str
    experiment_kind: str
    active: bool
    created_at: datetime
    updated_at: datetime
    heartbeat_interval_seconds: float = Field(gt=0)
    coordinates: tuple[PointCoordinateSpec, ...]
    planned_points: tuple[ReviewPointView, ...] = ()
    planned_points_truncated: bool = False
    pending_request_count: int = Field(default=0, ge=0)
    latest_result: ReviewCompilationResult | None = None


class ReviewSessionListView(_ReviewModel):
    items: tuple[ReviewSessionView, ...] = ()


class ReviewHeartbeatReceipt(_ReviewModel):
    session_id: str
    active: bool
    updated_at: datetime


class ReviewSessionCloseReceipt(_ReviewModel):
    session_id: str
    closed_at: datetime


class RunDomainInspectionEvent(_ReviewModel):
    """One transient domain decision and all compiled point inspections."""

    proposal_index: int = Field(ge=0)
    occurred_at: datetime
    fragment: RunDomainFragmentView
    region_ids: tuple[str, ...]
    source: Literal["author", "optimizer", "operator"]
    outcome: Literal["accepted", "rejected"]
    accepted_point_start: int | None = Field(default=None, ge=0)
    accepted_point_count: int = Field(default=0, ge=0)
    reason: str | None = None
    inspections: tuple[ReviewInspectionView, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> RunDomainInspectionEvent:
        if self.outcome == "accepted":
            expected_count = self.fragment.point_count * len(self.region_ids)
            if (
                self.accepted_point_start is None
                or self.accepted_point_count != expected_count
                or self.reason is not None
            ):
                raise ValueError(
                    "accepted domain proposal requires its accepted point range"
                )
        elif (
            self.accepted_point_start is not None
            or self.accepted_point_count != 0
            or not self.reason
        ):
            raise ValueError("rejected domain proposal requires a reason")
        if self.outcome == "rejected" and self.inspections:
            raise ValueError("rejected run proposal cannot have compiled inspections")
        return self


class RunInspectionAppendCommand(_ReviewModel):
    lease_id: str = Field(min_length=1)
    event: RunDomainInspectionEvent


class RunInspectionView(_ReviewModel):
    run_id: str = Field(min_length=1)
    items: tuple[RunDomainInspectionEvent, ...] = ()
    total_proposal_count: int = Field(default=0, ge=0)
    items_truncated: bool = False


__all__ = [
    "ReviewCompilationResult",
    "ReviewCompileCommand",
    "ReviewCompileReceipt",
    "ReviewCompletionCommand",
    "ReviewCoordinateKind",
    "ReviewCoordinateMode",
    "ReviewCoordinateSpec",
    "ReviewCoordinateValue",
    "ReviewHeartbeatReceipt",
    "ReviewInspectionView",
    "ReviewPointView",
    "ReviewSessionCloseReceipt",
    "ReviewSessionCreateCommand",
    "ReviewSessionListView",
    "ReviewSessionView",
    "ReviewWorkItem",
    "RunDomainInspectionEvent",
    "RunInspectionAppendCommand",
    "RunInspectionView",
]
