"""Point-adaptive experiment contracts shared by authoring and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from scopecat.measurements.points import AcceptedRunPoint, PointCandidate
from scopecat.records.measurement import MeasurementRecord


@dataclass(frozen=True, slots=True)
class CompletedPointObservation:
    """One accepted point and the durable-shaped records visible to an optimizer."""

    point: AcceptedRunPoint
    records: tuple[MeasurementRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class OptimizationComplete:
    """Explicit optimizer decision to stop proposing points."""

    reason: str = "optimizer completed"

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("optimization completion reason must be non-empty")


type PointProposalOutcome = Literal["accepted", "rejected"]


@dataclass(frozen=True, slots=True)
class PointProposalDecision:
    """One ordered runner decision about an optimizer candidate."""

    proposal_index: int
    candidate: PointCandidate
    outcome: PointProposalOutcome
    accepted_point: AcceptedRunPoint | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.proposal_index < 0:
            raise ValueError("proposal index must be non-negative")
        if self.outcome == "accepted":
            if self.accepted_point is None or self.reason is not None:
                raise ValueError("accepted proposal requires only an accepted point")
            if (
                self.accepted_point.proposal_fingerprint
                != self.candidate.proposal_fingerprint
            ):
                raise ValueError("accepted point must retain its proposal fingerprint")
        elif self.accepted_point is not None or not self.reason:
            raise ValueError("rejected proposal requires only a non-empty reason")


@dataclass(frozen=True, slots=True)
class PointProposalLedger:
    """Immutable proposal decisions for one adaptive run."""

    initial_point_count: int
    entries: tuple[PointProposalDecision, ...] = ()

    def __post_init__(self) -> None:
        if self.initial_point_count < 0:
            raise ValueError("initial point count must be non-negative")
        if tuple(entry.proposal_index for entry in self.entries) != tuple(
            range(len(self.entries))
        ):
            raise ValueError("proposal ledger indices must be contiguous")
        accepted_ordinals = tuple(
            entry.accepted_point.ordinal
            for entry in self.entries
            if entry.accepted_point is not None
        )
        if accepted_ordinals != tuple(
            range(
                self.initial_point_count,
                self.initial_point_count + len(accepted_ordinals),
            )
        ):
            raise ValueError("accepted optimizer points must extend one logical prefix")

    @property
    def accepted_count(self) -> int:
        return sum(entry.outcome == "accepted" for entry in self.entries)

    @property
    def rejected_count(self) -> int:
        return len(self.entries) - self.accepted_count

    @property
    def next_logical_ordinal(self) -> int:
        return self.initial_point_count + self.accepted_count

    def accept(
        self,
        candidate: PointCandidate,
        point: AcceptedRunPoint,
    ) -> PointProposalLedger:
        """Return a ledger extended by one admitted candidate."""

        if point.ordinal != self.next_logical_ordinal:
            raise ValueError("accepted optimizer point must extend the logical prefix")
        return PointProposalLedger(
            self.initial_point_count,
            (
                *self.entries,
                PointProposalDecision(
                    proposal_index=len(self.entries),
                    candidate=candidate,
                    outcome="accepted",
                    accepted_point=point,
                ),
            ),
        )

    def reject(self, candidate: PointCandidate, *, reason: str) -> PointProposalLedger:
        """Return a ledger extended by one rejected candidate."""

        return PointProposalLedger(
            self.initial_point_count,
            (
                *self.entries,
                PointProposalDecision(
                    proposal_index=len(self.entries),
                    candidate=candidate,
                    outcome="rejected",
                    reason=reason,
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class PointOptimizerContext:
    """Complete immutable facts supplied for one optimizer decision."""

    observations: tuple[CompletedPointObservation, ...]
    ledger: PointProposalLedger
    point_limit: int

    def __post_init__(self) -> None:
        if self.point_limit <= 0:
            raise ValueError("adaptive point limit must be positive")
        if len(self.observations) != (
            self.ledger.initial_point_count + self.ledger.accepted_count
        ):
            raise ValueError("optimizer observations must cover every accepted point")
        if len(self.observations) > self.point_limit:
            raise ValueError("optimizer observations exceed the adaptive point limit")

    @property
    def completed_point_count(self) -> int:
        return len(self.observations)

    @property
    def remaining_point_count(self) -> int:
        return self.point_limit - self.completed_point_count


class PointOptimizer(Protocol):
    """Pure next-point strategy retained by the local execution process."""

    @property
    def id(self) -> str: ...

    def propose(
        self,
        context: PointOptimizerContext,
    ) -> PointCandidate | OptimizationComplete: ...


@dataclass(frozen=True, slots=True)
class AdaptivePointPlan:
    """Bounded optimizer policy paired with an invocation's initial point plan."""

    optimizer: PointOptimizer = field(repr=False, compare=False)
    max_points: int
    optimizer_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.optimizer.id:
            raise ValueError("point optimizer id must be non-empty")
        if self.max_points <= 0:
            raise ValueError("adaptive point limit must be positive")
        object.__setattr__(self, "optimizer_id", self.optimizer.id)

    def ledger(self, *, initial_point_count: int) -> PointProposalLedger:
        """Create the empty ledger after the initial plan has materialized."""

        if initial_point_count > self.max_points:
            raise ValueError("initial point plan exceeds the adaptive point limit")
        return PointProposalLedger(initial_point_count)


__all__ = [
    "AdaptivePointPlan",
    "CompletedPointObservation",
    "OptimizationComplete",
    "PointOptimizer",
    "PointOptimizerContext",
    "PointProposalDecision",
    "PointProposalLedger",
    "PointProposalOutcome",
]
