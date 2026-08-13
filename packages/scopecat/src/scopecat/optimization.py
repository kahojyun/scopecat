"""Point-adaptive experiment contracts shared by authoring and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from scopecat.measurements.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.records.measurement import MeasurementRecord

OPTIMIZER_OBSERVATION_WINDOW = 256
OPTIMIZER_DECISION_WINDOW = 1024


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
    candidate: PointProposalAttempt
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
    """Immutable recent proposal decisions plus exact run-wide counters."""

    initial_point_count: int
    entries: tuple[PointProposalDecision, ...] = ()
    entry_offset: int = 0
    accepted_count_before: int = 0
    rejected_count_before: int = 0
    author_attempt_count_before: int = 0
    optimizer_attempt_count_before: int = 0
    operator_attempt_count_before: int = 0
    accepted_count_in_window: int = 0
    rejected_count_in_window: int = 0

    def __post_init__(self) -> None:
        if self.initial_point_count < 0:
            raise ValueError("initial point count must be non-negative")
        if (
            min(
                self.entry_offset,
                self.accepted_count_before,
                self.rejected_count_before,
                self.author_attempt_count_before,
                self.optimizer_attempt_count_before,
                self.operator_attempt_count_before,
                self.accepted_count_in_window,
                self.rejected_count_in_window,
            )
            < 0
        ):
            raise ValueError("proposal ledger counters must be non-negative")
        if self.accepted_count_before + self.rejected_count_before != self.entry_offset:
            raise ValueError("proposal ledger prefix counters must match its offset")
        if (
            self.author_attempt_count_before
            + self.optimizer_attempt_count_before
            + self.operator_attempt_count_before
            != self.entry_offset
        ):
            raise ValueError("proposal ledger source counters must match its offset")
        if self.accepted_count_in_window + self.rejected_count_in_window != len(
            self.entries
        ):
            raise ValueError("proposal ledger window counters must match its entries")
        if self.entries and (
            self.entries[0].proposal_index != self.entry_offset
            or self.entries[-1].proposal_index
            != self.entry_offset + len(self.entries) - 1
        ):
            raise ValueError("proposal ledger indices must bound one contiguous window")

    @property
    def accepted_count(self) -> int:
        return self.accepted_count_before + self.accepted_count_in_window

    @property
    def rejected_count(self) -> int:
        return self.rejected_count_before + self.rejected_count_in_window

    @property
    def decision_count(self) -> int:
        return self.entry_offset + len(self.entries)

    @property
    def optimizer_attempt_count(self) -> int:
        return self.optimizer_attempt_count_before + sum(
            entry.candidate.source == "optimizer" for entry in self.entries
        )

    @property
    def operator_attempt_count(self) -> int:
        return self.operator_attempt_count_before + sum(
            entry.candidate.source == "operator" for entry in self.entries
        )

    @property
    def next_logical_ordinal(self) -> int:
        return self.initial_point_count + self.accepted_count

    def accept(
        self,
        candidate: PointProposalAttempt,
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
                    proposal_index=self.decision_count,
                    candidate=candidate,
                    outcome="accepted",
                    accepted_point=point,
                ),
            ),
            entry_offset=self.entry_offset,
            accepted_count_before=self.accepted_count_before,
            rejected_count_before=self.rejected_count_before,
            author_attempt_count_before=self.author_attempt_count_before,
            optimizer_attempt_count_before=self.optimizer_attempt_count_before,
            operator_attempt_count_before=self.operator_attempt_count_before,
            accepted_count_in_window=self.accepted_count_in_window + 1,
            rejected_count_in_window=self.rejected_count_in_window,
        )

    def reject(
        self,
        candidate: PointProposalAttempt,
        *,
        reason: str,
    ) -> PointProposalLedger:
        """Return a ledger extended by one rejected candidate."""

        return PointProposalLedger(
            self.initial_point_count,
            (
                *self.entries,
                PointProposalDecision(
                    proposal_index=self.decision_count,
                    candidate=candidate,
                    outcome="rejected",
                    reason=reason,
                ),
            ),
            entry_offset=self.entry_offset,
            accepted_count_before=self.accepted_count_before,
            rejected_count_before=self.rejected_count_before,
            author_attempt_count_before=self.author_attempt_count_before,
            optimizer_attempt_count_before=self.optimizer_attempt_count_before,
            operator_attempt_count_before=self.operator_attempt_count_before,
            accepted_count_in_window=self.accepted_count_in_window,
            rejected_count_in_window=self.rejected_count_in_window + 1,
        )

    def recent(self, limit: int = OPTIMIZER_DECISION_WINDOW) -> PointProposalLedger:
        """Bound retained decision objects without losing exact prefix counts."""

        if limit <= 0:
            raise ValueError("proposal ledger window must be positive")
        dropped = self.entries[:-limit]
        if not dropped:
            return self
        dropped_accepted = sum(entry.outcome == "accepted" for entry in dropped)
        dropped_rejected = len(dropped) - dropped_accepted
        dropped_authored = sum(entry.candidate.source == "author" for entry in dropped)
        dropped_optimizer = sum(
            entry.candidate.source == "optimizer" for entry in dropped
        )
        dropped_operator = len(dropped) - dropped_authored - dropped_optimizer
        return PointProposalLedger(
            initial_point_count=self.initial_point_count,
            entries=self.entries[-limit:],
            entry_offset=self.entry_offset + len(dropped),
            accepted_count_before=self.accepted_count_before + dropped_accepted,
            rejected_count_before=self.rejected_count_before + dropped_rejected,
            author_attempt_count_before=(
                self.author_attempt_count_before + dropped_authored
            ),
            optimizer_attempt_count_before=(
                self.optimizer_attempt_count_before + dropped_optimizer
            ),
            operator_attempt_count_before=(
                self.operator_attempt_count_before + dropped_operator
            ),
            accepted_count_in_window=(self.accepted_count_in_window - dropped_accepted),
            rejected_count_in_window=(self.rejected_count_in_window - dropped_rejected),
        )


@dataclass(frozen=True, slots=True)
class PointOptimizerContext:
    """Exact counters and bounded recent facts for one optimizer decision."""

    observations: tuple[CompletedPointObservation, ...]
    ledger: PointProposalLedger
    point_limit: int
    completed_point_count: int

    def __post_init__(self) -> None:
        if self.point_limit <= 0:
            raise ValueError("adaptive point limit must be positive")
        if self.completed_point_count != (
            self.ledger.initial_point_count + self.ledger.accepted_count
        ):
            raise ValueError("optimizer completed count must cover accepted points")
        if self.completed_point_count > self.point_limit:
            raise ValueError("optimizer observations exceed the adaptive point limit")
        observation_start = self.completed_point_count - len(self.observations)
        if observation_start < 0 or tuple(
            observation.point.ordinal for observation in self.observations
        ) != tuple(range(observation_start, self.completed_point_count)):
            raise ValueError("optimizer observations must be one completed suffix")

    @property
    def observation_start_index(self) -> int:
        return self.completed_point_count - len(self.observations)

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
    ) -> PointProposalAttempt | OptimizationComplete: ...


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

    @property
    def proposal_limit(self) -> int:
        """Bound rejected retries while leaving room for optimizer correction."""

        return self.max_points * 4


__all__ = [
    "OPTIMIZER_DECISION_WINDOW",
    "OPTIMIZER_OBSERVATION_WINDOW",
    "AdaptivePointPlan",
    "CompletedPointObservation",
    "OptimizationComplete",
    "PointOptimizer",
    "PointOptimizerContext",
    "PointProposalDecision",
    "PointProposalLedger",
    "PointProposalOutcome",
]
