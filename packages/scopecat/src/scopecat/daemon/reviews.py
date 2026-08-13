"""Transient experiment-review models shared by notebook, daemon, and GUI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.inspection import CompiledArtifactInspection
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity

type ReviewCoordinateValue = bool | int | float | str | Quantity | EntityRef | None
type ReviewCoordinateKind = Literal[
    "bool",
    "int",
    "float",
    "string",
    "quantity",
    "entity",
]
type ReviewCoordinateMode = Literal["exact", "free"]


class _ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewCoordinateSpec(_ReviewModel):
    id: str = Field(min_length=1)
    kind: ReviewCoordinateKind
    unit: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[str, ...] | None = None
    planned_values: tuple[ReviewCoordinateValue, ...] = ()
    planned_values_truncated: bool = False


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
    coordinates: tuple[ReviewCoordinateSpec, ...]
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
    coordinates: tuple[ReviewCoordinateSpec, ...]
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


class RunPointInspectionEvent(_ReviewModel):
    """One transient optimizer decision and its compiled target inspection."""

    proposal_index: int = Field(ge=0)
    occurred_at: datetime
    candidate: ReviewPointView
    outcome: Literal["accepted", "rejected"]
    accepted_point: ReviewPointView | None = None
    reason: str | None = None
    inspections: tuple[ReviewInspectionView, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> RunPointInspectionEvent:
        if self.candidate.point_index is not None:
            raise ValueError("proposal candidates cannot have a run point index")
        if self.outcome == "accepted":
            if self.accepted_point is None or self.reason is not None:
                raise ValueError("accepted run proposal requires an accepted point")
        elif self.accepted_point is not None or not self.reason:
            raise ValueError("rejected run proposal requires a reason")
        if self.outcome == "rejected" and self.inspections:
            raise ValueError("rejected run proposal cannot have compiled inspections")
        return self


class RunInspectionAppendCommand(_ReviewModel):
    lease_id: str = Field(min_length=1)
    event: RunPointInspectionEvent


class RunInspectionView(_ReviewModel):
    run_id: str = Field(min_length=1)
    items: tuple[RunPointInspectionEvent, ...] = ()
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
    "RunInspectionAppendCommand",
    "RunInspectionView",
    "RunPointInspectionEvent",
]
