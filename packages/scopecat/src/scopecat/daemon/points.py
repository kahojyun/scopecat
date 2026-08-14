"""Durable adaptive-domain control models shared with the daemon."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.adaptive_domains import (
    DomainProposalAttempt,
    OperatorDomainRequest,
    OperatorRegionScope,
    ResolvedAroundSource,
    ResolvedDomainAxis,
    ResolvedDomainFragment,
    ResolvedRangeSource,
    ResolvedValuesSource,
)
from scopecat.control.models import PointCoordinateValue
from scopecat.kernel.points import PointProposalSource
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue

type RunPointCoordinateValue = PointCoordinateValue


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunDomainValuesSourceView(_DomainModel):
    kind: Literal["values"] = "values"
    values: tuple[RunPointCoordinateValue, ...] = Field(min_length=1)


class RunDomainRangeSourceView(_DomainModel):
    kind: Literal["range"] = "range"
    start: float | Quantity
    stop: float | Quantity
    points: int = Field(ge=2)


class RunDomainAroundSourceView(_DomainModel):
    kind: Literal["around"] = "around"
    center: float | Quantity
    span: float | Quantity
    points: int = Field(ge=2)


type RunDomainAxisSourceView = Annotated[
    RunDomainValuesSourceView | RunDomainRangeSourceView | RunDomainAroundSourceView,
    Field(discriminator="kind"),
]


class RunDomainAxisView(_DomainModel):
    axis_id: str = Field(min_length=1)
    source: RunDomainAxisSourceView

    def axis(self) -> ResolvedDomainAxis:
        source = self.source
        if isinstance(source, RunDomainValuesSourceView):
            return ResolvedDomainAxis(
                self.axis_id,
                ResolvedValuesSource(cast("tuple[CellValue, ...]", source.values)),
            )
        if isinstance(source, RunDomainRangeSourceView):
            return ResolvedDomainAxis(
                self.axis_id,
                ResolvedRangeSource(source.start, source.stop, source.points),
            )
        return ResolvedDomainAxis(
            self.axis_id,
            ResolvedAroundSource(source.center, source.span, source.points),
        )

    @classmethod
    def from_axis(cls, axis: ResolvedDomainAxis) -> RunDomainAxisView:
        source = axis.source
        if isinstance(source, ResolvedValuesSource):
            view: RunDomainAxisSourceView = RunDomainValuesSourceView(
                values=cast("tuple[RunPointCoordinateValue, ...]", source.values)
            )
        elif isinstance(source, ResolvedRangeSource):
            view = RunDomainRangeSourceView(
                start=source.start,
                stop=source.stop,
                points=source.points,
            )
        else:
            view = RunDomainAroundSourceView(
                center=source.center,
                span=source.span,
                points=source.points,
            )
        return cls(axis_id=axis.id, source=view)


class _RunDomainFragmentBase(_DomainModel):
    layout: Literal["grid", "point_cloud"]
    axes: tuple[RunDomainAxisView, ...] = Field(min_length=1)

    def fragment(self) -> ResolvedDomainFragment:
        return ResolvedDomainFragment(
            tuple(axis.axis() for axis in self.axes),
            layout=self.layout,
        )


class RunDomainFragmentInput(_RunDomainFragmentBase):
    @classmethod
    def from_fragment(cls, fragment: ResolvedDomainFragment) -> RunDomainFragmentInput:
        return cls(
            layout=fragment.layout,
            axes=tuple(RunDomainAxisView.from_axis(axis) for axis in fragment.axes),
        )


class RunDomainFragmentView(_RunDomainFragmentBase):
    point_count: int = Field(ge=1)
    fragment_fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fragment(self) -> RunDomainFragmentView:
        fragment = self.fragment()
        if fragment.point_count != self.point_count:
            raise ValueError("domain fragment point count does not match")
        if fragment.fingerprint != self.fragment_fingerprint:
            raise ValueError("domain fragment fingerprint does not match")
        return self

    @classmethod
    def from_fragment(cls, fragment: ResolvedDomainFragment) -> RunDomainFragmentView:
        return cls(
            layout=fragment.layout,
            axes=tuple(RunDomainAxisView.from_axis(axis) for axis in fragment.axes),
            point_count=fragment.point_count,
            fragment_fingerprint=fragment.fingerprint,
        )


class RunDomainProposalAttemptView(_DomainModel):
    fragment: RunDomainFragmentView
    region_ids: tuple[str, ...] = ()
    source: PointProposalSource
    based_on_region_revisions: dict[str, int] = Field(default_factory=dict)
    proposal_fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_proposal(self) -> RunDomainProposalAttemptView:
        if self.proposal().proposal_fingerprint != self.proposal_fingerprint:
            raise ValueError("domain proposal fingerprint does not match")
        return self

    def proposal(self) -> DomainProposalAttempt:
        return DomainProposalAttempt(
            fragment=self.fragment.fragment(),
            region_ids=self.region_ids,
            source=self.source,
            based_on_region_revisions=self.based_on_region_revisions,
        )

    @classmethod
    def from_proposal(
        cls,
        proposal: DomainProposalAttempt,
    ) -> RunDomainProposalAttemptView:
        return cls(
            fragment=RunDomainFragmentView.from_fragment(proposal.fragment),
            region_ids=proposal.region_ids,
            source=proposal.source,
            based_on_region_revisions=dict(proposal.based_on_region_revisions),
            proposal_fingerprint=proposal.proposal_fingerprint,
        )


class OperatorDomainRequestView(_DomainModel):
    request_id: str = Field(min_length=1)
    coordinate_mode: Literal["snap", "free"]
    region_scope: OperatorRegionScope
    region_ids: tuple[str, ...] = ()
    region_count: int = Field(ge=1)
    requested_fragment: RunDomainFragmentView
    fragment: RunDomainFragmentView
    request_fingerprint: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_request(self) -> OperatorDomainRequestView:
        if self.request().request_fingerprint != self.request_fingerprint:
            raise ValueError("operator domain request fingerprint does not match")
        return self

    def request(self) -> OperatorDomainRequest:
        return OperatorDomainRequest(
            request_id=self.request_id,
            coordinate_mode=self.coordinate_mode,
            region_scope=self.region_scope,
            region_ids=self.region_ids,
            region_count=self.region_count,
            requested_fragment=self.requested_fragment.fragment(),
            fragment=self.fragment.fragment(),
        )

    @classmethod
    def from_request(cls, request: OperatorDomainRequest) -> OperatorDomainRequestView:
        return cls(
            request_id=request.request_id,
            coordinate_mode=request.coordinate_mode,
            region_scope=request.region_scope,
            region_ids=request.region_ids,
            region_count=request.region_count,
            requested_fragment=RunDomainFragmentView.from_fragment(
                request.requested_fragment
            ),
            fragment=RunDomainFragmentView.from_fragment(request.fragment),
            request_fingerprint=request.request_fingerprint,
        )


class AcceptedRunPointView(_DomainModel):
    point_index: int = Field(ge=0)
    coordinates: dict[str, RunPointCoordinateValue]
    proposal_fingerprint: str = Field(min_length=1)
    source: PointProposalSource
    region_id: str = Field(min_length=1)
    domain_proposal_fingerprint: str = Field(min_length=1)


class RunDomainDecisionView(_DomainModel):
    operation_id: str = Field(min_length=1)
    operator_request_id: str | None = Field(default=None, min_length=1)
    proposal_index: int = Field(ge=0)
    occurred_at: datetime
    proposal: RunDomainProposalAttemptView
    outcome: Literal["accepted", "rejected"]
    accepted_point_start: int | None = Field(default=None, ge=0)
    accepted_point_count: int = Field(default=0, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> RunDomainDecisionView:
        if self.outcome == "accepted":
            expected_count = self.proposal.fragment.point_count * len(
                self.proposal.region_ids
            )
            if (
                self.accepted_point_start is None
                or self.accepted_point_count != expected_count
                or self.reason is not None
            ):
                raise ValueError("accepted domain decision requires its point range")
        elif (
            self.accepted_point_start is not None
            or self.accepted_point_count != 0
            or not self.reason
        ):
            raise ValueError("rejected domain decision requires only a reason")
        return self


class RunDomainDecisionPage(_DomainModel):
    """Newest durable domain decisions, ordered by proposal index."""

    run_id: str = Field(min_length=1)
    items: tuple[RunDomainDecisionView, ...] = ()
    next_cursor: int | None = Field(default=None, ge=0)


class RunPointPlanView(_DomainModel):
    """Durable adaptive point inventory and domain-decision progress."""

    run_id: str = Field(min_length=1)
    initial_point_count: int = Field(ge=0)
    accepted_point_count: int = Field(ge=0)
    point_limit: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    optimizer_attempt_count: int = Field(ge=0)
    operator_request_count: int = Field(ge=0)
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
        if self.optimizer_attempt_count > self.decision_count:
            raise ValueError("optimizer attempts cannot exceed domain decisions")
        return self


class RunDomainDecisionCommand(_DomainModel):
    lease_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    operator_request_id: str | None = Field(default=None, min_length=1)
    proposal: RunDomainProposalAttemptView
    outcome: Literal["accepted", "rejected"]
    accepted_points: tuple[AcceptedRunPointView, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> RunDomainDecisionCommand:
        if self.outcome == "accepted":
            if not self.accepted_points or self.reason is not None:
                raise ValueError("accepted domain command requires accepted points")
            _validate_accepted_domain_points(self.proposal, self.accepted_points)
        elif self.accepted_points or not self.reason:
            raise ValueError("rejected domain command requires only a reason")
        return self


class RunDomainEnqueueCommand(_DomainModel):
    request_id: str = Field(min_length=1)
    coordinate_mode: Literal["snap", "free"]
    region_scope: OperatorRegionScope
    region_ids: tuple[str, ...] = ()
    fragment: RunDomainFragmentInput

    def domain_request(
        self,
        resolved_fragment: ResolvedDomainFragment,
        *,
        region_count: int,
    ) -> OperatorDomainRequestView:
        request = OperatorDomainRequest(
            request_id=self.request_id,
            coordinate_mode=self.coordinate_mode,
            region_scope=self.region_scope,
            region_ids=self.region_ids,
            region_count=region_count,
            requested_fragment=self.fragment.fragment(),
            fragment=resolved_fragment,
        )
        return OperatorDomainRequestView.from_request(request)


class RunDomainResolveCommand(_DomainModel):
    coordinate_mode: Literal["snap", "free"]
    region_scope: OperatorRegionScope
    region_ids: tuple[str, ...] = ()
    fragment: RunDomainFragmentInput


class ResolvedRunDomainView(_DomainModel):
    coordinate_mode: Literal["snap", "free"]
    region_scope: OperatorRegionScope
    region_ids: tuple[str, ...] = ()
    requested_fragment: RunDomainFragmentView
    fragment: RunDomainFragmentView
    region_count: int = Field(ge=1)
    total_point_count: int = Field(ge=1)


class RunDomainQueueEntryView(_DomainModel):
    queue_index: int = Field(ge=0)
    occurred_at: datetime
    request: OperatorDomainRequestView
    status: Literal["pending", "accepted", "rejected", "cancelled"]
    decision_operation_id: str | None = Field(default=None, min_length=1)
    accepted_point_start: int | None = Field(default=None, ge=0)
    accepted_point_count: int = Field(default=0, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> RunDomainQueueEntryView:
        if self.status == "pending":
            if (
                self.decision_operation_id is not None
                or self.accepted_point_start is not None
                or self.accepted_point_count != 0
                or self.reason is not None
            ):
                raise ValueError("pending domain request cannot have a resolution")
        elif self.status == "accepted":
            if (
                self.decision_operation_id is None
                or self.accepted_point_start is None
                or self.accepted_point_count < 1
                or self.reason is not None
            ):
                raise ValueError("accepted domain request requires its point range")
        elif self.status == "rejected":
            if (
                self.decision_operation_id is None
                or self.accepted_point_start is not None
                or self.accepted_point_count != 0
                or not self.reason
            ):
                raise ValueError("rejected domain request requires its reason")
        elif (
            self.decision_operation_id is not None
            or self.accepted_point_start is not None
            or self.accepted_point_count != 0
            or not self.reason
        ):
            raise ValueError("cancelled domain request requires only a reason")
        return self


class RunDomainQueueView(_DomainModel):
    run_id: str = Field(min_length=1)
    items: tuple[RunDomainQueueEntryView, ...] = ()


class RunPointPlanCloseCommand(_DomainModel):
    lease_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    based_on_completed_point_count: int = Field(ge=0)
    reason: str = Field(min_length=1)


def _validate_accepted_domain_points(
    proposal: RunDomainProposalAttemptView,
    points: tuple[AcceptedRunPointView, ...],
) -> None:
    if not proposal.region_ids:
        raise ValueError("accepted domain proposal requires resolved regions")
    expected_count = proposal.fragment.point_count * len(proposal.region_ids)
    if len(points) != expected_count:
        raise ValueError("accepted points must cover the complete domain fragment")
    if any(
        point.domain_proposal_fingerprint != proposal.proposal_fingerprint
        for point in points
    ):
        raise ValueError("accepted points must retain domain proposal identity")
    for region_id in proposal.region_ids:
        if sum(point.region_id == region_id for point in points) != (
            proposal.fragment.point_count
        ):
            raise ValueError("accepted points must cover every selected region")


__all__ = [
    "AcceptedRunPointView",
    "OperatorDomainRequestView",
    "ResolvedRunDomainView",
    "RunDomainAroundSourceView",
    "RunDomainAxisSourceView",
    "RunDomainAxisView",
    "RunDomainDecisionCommand",
    "RunDomainDecisionPage",
    "RunDomainDecisionView",
    "RunDomainEnqueueCommand",
    "RunDomainFragmentInput",
    "RunDomainFragmentView",
    "RunDomainProposalAttemptView",
    "RunDomainQueueEntryView",
    "RunDomainQueueView",
    "RunDomainRangeSourceView",
    "RunDomainResolveCommand",
    "RunDomainValuesSourceView",
    "RunPointCoordinateValue",
    "RunPointPlanCloseCommand",
    "RunPointPlanView",
]
