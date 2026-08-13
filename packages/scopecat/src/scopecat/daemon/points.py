"""Durable adaptive-point control models shared with the daemon."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.measurements.points import PointCandidate, PointCandidateSource

type RunPointCoordinateValue = bool | int | float | str | Quantity | EntityRef | None

POINT_PLAN_INITIALIZE_OPERATION_ID = "point-plan.initialize.v1"


class _PointModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunPointCandidateView(_PointModel):
    """Canonical candidate content crossing the daemon boundary."""

    coordinates: dict[str, RunPointCoordinateValue]
    proposal_fingerprint: str = Field(min_length=1)
    source: PointCandidateSource
    based_on_completed_point_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_fingerprint(self) -> RunPointCandidateView:
        candidate = PointCandidate(
            coordinates=cast("dict[str, CellValue]", self.coordinates),
            source=self.source,
            based_on_completed_point_count=self.based_on_completed_point_count,
        )
        if candidate.proposal_fingerprint != self.proposal_fingerprint:
            raise ValueError("point candidate fingerprint does not match its content")
        return self


class AcceptedRunPointView(_PointModel):
    """One daemon-accepted dynamic run point."""

    point_index: int = Field(ge=0)
    coordinates: dict[str, RunPointCoordinateValue]
    proposal_fingerprint: str = Field(min_length=1)
    source: PointCandidateSource


class RunPointDecisionView(_PointModel):
    """One durable ordered decision about a point candidate."""

    operation_id: str = Field(min_length=1)
    queue_operation_id: str | None = Field(default=None, min_length=1)
    proposal_index: int = Field(ge=0)
    occurred_at: datetime
    candidate: RunPointCandidateView
    outcome: Literal["accepted", "rejected"]
    accepted_point: AcceptedRunPointView | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> RunPointDecisionView:
        if self.outcome == "accepted":
            if self.accepted_point is None or self.reason is not None:
                raise ValueError(
                    "accepted point decision requires only an accepted point"
                )
            if (
                self.accepted_point.proposal_fingerprint
                != self.candidate.proposal_fingerprint
                or self.accepted_point.coordinates != self.candidate.coordinates
                or self.accepted_point.source != self.candidate.source
            ):
                raise ValueError("accepted point must retain its candidate content")
        elif self.accepted_point is not None or not self.reason:
            raise ValueError("rejected point decision requires only a reason")
        return self


class RunPointPlanView(_PointModel):
    """Durable adaptive point-plan progress without transient waveforms."""

    run_id: str = Field(min_length=1)
    initial_point_count: int = Field(ge=0)
    accepted_point_count: int = Field(ge=0)
    point_limit: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    plan_closed: bool
    stop_reason: str | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> RunPointPlanView:
        if not (
            self.initial_point_count <= self.accepted_point_count <= self.point_limit
        ):
            raise ValueError("point-plan counts must form one bounded prefix")
        if self.plan_closed != (self.stop_reason is not None):
            raise ValueError("closed point plan requires exactly one stop reason")
        return self


class RunPointPlanInitializeCommand(_PointModel):
    lease_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


class RunPointDecisionCommand(_PointModel):
    lease_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    queue_operation_id: str | None = Field(default=None, min_length=1)
    candidate: RunPointCandidateView
    outcome: Literal["accepted", "rejected"]
    reason: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> RunPointDecisionCommand:
        if self.outcome == "accepted" and self.reason is not None:
            raise ValueError("accepted point command cannot include a reason")
        if self.outcome == "rejected" and not self.reason:
            raise ValueError("rejected point command requires a reason")
        return self


class RunPointEnqueueCommand(_PointModel):
    operation_id: str = Field(min_length=1)
    candidate: RunPointCandidateView

    @model_validator(mode="after")
    def validate_source(self) -> RunPointEnqueueCommand:
        if self.candidate.source != "operator":
            raise ValueError("queued point candidate must have operator source")
        return self


class RunPointQueueEntryView(_PointModel):
    queue_index: int = Field(ge=0)
    operation_id: str = Field(min_length=1)
    occurred_at: datetime
    candidate: RunPointCandidateView
    status: Literal["pending", "accepted", "rejected", "cancelled"]
    decision_operation_id: str | None = Field(default=None, min_length=1)
    accepted_point_index: int | None = Field(default=None, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> RunPointQueueEntryView:
        if self.status == "pending":
            if (
                self.decision_operation_id is not None
                or self.accepted_point_index is not None
                or self.reason is not None
            ):
                raise ValueError("pending queue entry cannot have a resolution")
        elif self.status == "accepted":
            if (
                self.decision_operation_id is None
                or self.accepted_point_index is None
                or self.reason is not None
            ):
                raise ValueError("accepted queue entry requires its accepted decision")
        elif self.status == "rejected":
            if (
                self.decision_operation_id is None
                or self.accepted_point_index is not None
                or not self.reason
            ):
                raise ValueError("rejected queue entry requires its rejected decision")
        elif (
            self.decision_operation_id is not None
            or self.accepted_point_index is not None
            or not self.reason
        ):
            raise ValueError("cancelled queue entry requires only a reason")
        return self


class RunPointQueueView(_PointModel):
    run_id: str = Field(min_length=1)
    items: tuple[RunPointQueueEntryView, ...] = ()


class RunPointPlanCloseCommand(_PointModel):
    lease_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    based_on_completed_point_count: int = Field(ge=0)
    reason: str = Field(min_length=1)


__all__ = [
    "POINT_PLAN_INITIALIZE_OPERATION_ID",
    "AcceptedRunPointView",
    "RunPointCandidateView",
    "RunPointCoordinateValue",
    "RunPointDecisionCommand",
    "RunPointDecisionView",
    "RunPointEnqueueCommand",
    "RunPointPlanCloseCommand",
    "RunPointPlanInitializeCommand",
    "RunPointPlanView",
    "RunPointQueueEntryView",
    "RunPointQueueView",
]
