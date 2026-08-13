"""Point-adaptive experiment contracts shared by authoring and execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol

from scopecat.adaptive_domains import (
    AdaptiveRegion,
    AdaptiveScope,
    DomainProposalAttempt,
    RegionOptimizationComplete,
)
from scopecat.kernel.points import AcceptedRunPoint

OPTIMIZER_OBSERVATION_WINDOW = 256
OPTIMIZER_DECISION_WINDOW = 1024


type OptimizerMeasurementDType = Literal[
    "float64",
    "int64",
    "complex128",
    "bool",
    "string",
]
type OptimizerScalarData = bool | int | float | complex | str
type OptimizerUnavailableReason = Literal["missing", "invalid", "overload"]


@dataclass(frozen=True, slots=True)
class OptimizerScalarObservation:
    """One metadata-free scalar observable available to an optimizer."""

    dtype: OptimizerMeasurementDType
    unit: str | None
    value: OptimizerScalarData


@dataclass(frozen=True, slots=True)
class OptimizerUnavailableObservation:
    """One metadata-free unavailable observable available to an optimizer."""

    reason: OptimizerUnavailableReason
    dtype: OptimizerMeasurementDType
    unit: str | None
    shape: tuple[int | None, ...]


type OptimizerObservationValue = (
    OptimizerScalarObservation | OptimizerUnavailableObservation
)


@dataclass(frozen=True, slots=True)
class OptimizerMeasurementObservation:
    """Lightweight scalar measurement facts retained for one completed point."""

    run_id: str
    logical_point_id: str | None
    observables: Mapping[str, OptimizerObservationValue]
    omitted_array_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observables",
            MappingProxyType(dict(self.observables)),
        )


@dataclass(frozen=True, slots=True)
class CompletedPointObservation:
    """One accepted point and its bounded optimizer-facing measurement projection."""

    point: AcceptedRunPoint
    measurements: tuple[OptimizerMeasurementObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class OptimizationComplete:
    """Explicit optimizer decision to stop proposing points."""

    reason: str = "optimizer completed"

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("optimization completion reason must be non-empty")


type PointProposalOutcome = Literal["accepted", "rejected"]


@dataclass(frozen=True, slots=True)
class DomainProposalDecision:
    """One ordered decision about a proposed compatible domain fragment."""

    proposal_index: int
    proposal: DomainProposalAttempt
    outcome: PointProposalOutcome
    accepted_points: tuple[AcceptedRunPoint, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.proposal_index < 0:
            raise ValueError("proposal index must be non-negative")
        if self.outcome == "accepted":
            if not self.accepted_points or self.reason is not None:
                raise ValueError(
                    "accepted domain proposal requires only accepted points"
                )
            if any(
                point.domain_proposal_fingerprint != self.proposal.proposal_fingerprint
                for point in self.accepted_points
            ):
                raise ValueError(
                    "accepted points must retain their domain proposal identity"
                )
        elif self.accepted_points or not self.reason:
            raise ValueError("rejected domain proposal requires only a reason")


@dataclass(frozen=True, slots=True)
class DomainProposalLedger:
    """Bounded recent domain decisions for one adaptive region."""

    initial_point_count: int
    entries: tuple[DomainProposalDecision, ...] = ()
    entry_offset: int = 0
    accepted_point_count_before: int = 0
    rejected_count_before: int = 0
    optimizer_attempt_count_before: int = 0

    def __post_init__(self) -> None:
        if (
            min(
                self.initial_point_count,
                self.entry_offset,
                self.accepted_point_count_before,
                self.rejected_count_before,
                self.optimizer_attempt_count_before,
            )
            < 0
        ):
            raise ValueError("domain proposal ledger counters must be non-negative")
        if self.entries and (
            self.entries[0].proposal_index != self.entry_offset
            or self.entries[-1].proposal_index
            != self.entry_offset + len(self.entries) - 1
        ):
            raise ValueError("domain decisions must form one contiguous window")

    @property
    def decision_count(self) -> int:
        return self.entry_offset + len(self.entries)

    @property
    def accepted_point_count(self) -> int:
        return self.accepted_point_count_before + sum(
            len(entry.accepted_points)
            for entry in self.entries
            if entry.outcome == "accepted"
        )

    @property
    def rejected_count(self) -> int:
        return self.rejected_count_before + sum(
            entry.outcome == "rejected" for entry in self.entries
        )

    @property
    def point_count(self) -> int:
        return self.initial_point_count + self.accepted_point_count

    @property
    def optimizer_attempt_count(self) -> int:
        return self.optimizer_attempt_count_before + sum(
            entry.proposal.source == "optimizer" for entry in self.entries
        )

    def accept(
        self,
        proposal: DomainProposalAttempt,
        points: tuple[AcceptedRunPoint, ...],
    ) -> DomainProposalLedger:
        return DomainProposalLedger(
            initial_point_count=self.initial_point_count,
            entries=(
                *self.entries,
                DomainProposalDecision(
                    proposal_index=self.decision_count,
                    proposal=proposal,
                    outcome="accepted",
                    accepted_points=points,
                ),
            ),
            entry_offset=self.entry_offset,
            accepted_point_count_before=self.accepted_point_count_before,
            rejected_count_before=self.rejected_count_before,
            optimizer_attempt_count_before=self.optimizer_attempt_count_before,
        )

    def reject(
        self,
        proposal: DomainProposalAttempt,
        *,
        reason: str,
    ) -> DomainProposalLedger:
        return DomainProposalLedger(
            initial_point_count=self.initial_point_count,
            entries=(
                *self.entries,
                DomainProposalDecision(
                    proposal_index=self.decision_count,
                    proposal=proposal,
                    outcome="rejected",
                    reason=reason,
                ),
            ),
            entry_offset=self.entry_offset,
            accepted_point_count_before=self.accepted_point_count_before,
            rejected_count_before=self.rejected_count_before,
            optimizer_attempt_count_before=self.optimizer_attempt_count_before,
        )

    def recent(self, limit: int = OPTIMIZER_DECISION_WINDOW) -> DomainProposalLedger:
        if limit <= 0:
            raise ValueError("domain decision window must be positive")
        dropped = self.entries[:-limit]
        if not dropped:
            return self
        return DomainProposalLedger(
            initial_point_count=self.initial_point_count,
            entries=self.entries[-limit:],
            entry_offset=self.entry_offset + len(dropped),
            accepted_point_count_before=self.accepted_point_count_before
            + sum(
                len(entry.accepted_points)
                for entry in dropped
                if entry.outcome == "accepted"
            ),
            rejected_count_before=self.rejected_count_before
            + sum(entry.outcome == "rejected" for entry in dropped),
            optimizer_attempt_count_before=self.optimizer_attempt_count_before
            + sum(entry.proposal.source == "optimizer" for entry in dropped),
        )


@dataclass(frozen=True, slots=True)
class DomainOptimizerContext:
    """Region-scoped observations and exact budgets for one domain decision."""

    region: AdaptiveRegion | None
    regions: tuple[AdaptiveRegion, ...]
    observations: tuple[CompletedPointObservation, ...]
    ledger: DomainProposalLedger
    total_point_limit: int
    accepted_point_count: int

    def __post_init__(self) -> None:
        if self.total_point_limit <= 0:
            raise ValueError("adaptive total point limit must be positive")
        if not self.regions:
            raise ValueError("domain optimizer context requires at least one region")
        if self.region is not None and self.region.id not in {
            region.id for region in self.regions
        }:
            raise ValueError("selected optimizer region is not in the run")
        if not 0 <= self.accepted_point_count <= self.total_point_limit:
            raise ValueError("accepted point count exceeds the adaptive total limit")

    @property
    def remaining_total_point_count(self) -> int:
        return self.total_point_limit - self.accepted_point_count


class DomainOptimizer(Protocol):
    """Pure compatible-domain strategy retained by the local executor."""

    @property
    def id(self) -> str: ...

    def propose(
        self,
        context: DomainOptimizerContext,
    ) -> DomainProposalAttempt | RegionOptimizationComplete | OptimizationComplete: ...


@dataclass(frozen=True, slots=True)
class AdaptiveDomainPlan:
    """Composable outer-static and inner-adaptive domain policy."""

    optimizer: DomainOptimizer = field(repr=False, compare=False)
    total_point_limit: int
    adaptive_coordinate_ids: tuple[str, ...] = ()
    scope: AdaptiveScope = "per_region"
    per_region_point_limit: int | None = None
    optimizer_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.optimizer.id:
            raise ValueError("domain optimizer id must be non-empty")
        if self.total_point_limit <= 0:
            raise ValueError("adaptive total point limit must be positive")
        if self.per_region_point_limit is not None and self.per_region_point_limit <= 0:
            raise ValueError("adaptive region point limit must be positive")
        if len(self.adaptive_coordinate_ids) != len(set(self.adaptive_coordinate_ids)):
            raise ValueError("adaptive coordinate ids must be unique")
        if any(not coordinate_id for coordinate_id in self.adaptive_coordinate_ids):
            raise ValueError("adaptive coordinate ids must be non-empty")
        object.__setattr__(self, "optimizer_id", self.optimizer.id)

    def validate_initial_point_count(self, initial_point_count: int) -> None:
        if initial_point_count > self.total_point_limit:
            raise ValueError("initial point plan exceeds the adaptive point limit")

    @property
    def proposal_limit(self) -> int:
        """Bound rejected retries while leaving room for optimizer correction."""

        return self.total_point_limit * 4


__all__ = [
    "OPTIMIZER_DECISION_WINDOW",
    "OPTIMIZER_OBSERVATION_WINDOW",
    "AdaptiveDomainPlan",
    "CompletedPointObservation",
    "DomainOptimizer",
    "DomainOptimizerContext",
    "DomainProposalDecision",
    "DomainProposalLedger",
    "OptimizationComplete",
    "OptimizerMeasurementObservation",
    "OptimizerObservationValue",
    "OptimizerScalarObservation",
    "OptimizerUnavailableObservation",
    "PointProposalOutcome",
]
