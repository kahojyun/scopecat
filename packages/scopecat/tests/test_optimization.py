from __future__ import annotations

from collections import deque

import pytest

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.measurements.points import AcceptedRunPoint, PointCandidate
from scopecat.optimization import (
    AdaptivePointPlan,
    CompletedPointObservation,
    OptimizationComplete,
    PointOptimizerContext,
    PointProposalLedger,
)


class _Optimizer:
    id = "test.midpoint"

    def propose(
        self,
        context: PointOptimizerContext,
    ) -> PointCandidate | OptimizationComplete:
        if context.remaining_point_count == 0:
            return OptimizationComplete("point budget exhausted")
        return PointCandidate(
            {"x": context.completed_point_count + 0.5},
            source="optimizer",
            based_on_completed_point_count=context.completed_point_count,
        )


def _point(ordinal: int, candidate: PointCandidate) -> AcceptedRunPoint:
    return AcceptedRunPoint.accept(
        candidate,
        logical_id=LogicalPointId(
            PointDomainId("test.program", "points"),
            ordinal,
        ),
    )


def test_optimizer_context_and_ledger_preserve_proposal_identity() -> None:
    initial_candidate = PointCandidate({"x": 0.0})
    initial = _point(0, initial_candidate)
    ledger = PointProposalLedger(initial_point_count=1)
    context = PointOptimizerContext(
        observations=(CompletedPointObservation(initial),),
        ledger=ledger,
        point_limit=3,
        completed_point_count=1,
    )

    candidate = _Optimizer().propose(context)
    assert isinstance(candidate, PointCandidate)
    assert candidate.source == "optimizer"
    assert candidate.based_on_completed_point_count == 1

    accepted = _point(1, candidate)
    ledger = ledger.accept(candidate, accepted)
    rejected = PointCandidate(
        {"x": 1.5},
        source="optimizer",
        based_on_completed_point_count=2,
    )
    ledger = ledger.reject(rejected, reason="duplicate coordinate")

    assert ledger.accepted_count == 1
    assert ledger.rejected_count == 1
    assert ledger.next_logical_ordinal == 2
    assert ledger.entries[0].candidate.proposal_fingerprint == (
        accepted.proposal_fingerprint
    )
    assert ledger.entries[1].reason == "duplicate coordinate"


def test_optimizer_context_retains_bounded_suffixes_with_exact_totals() -> None:
    ledger = PointProposalLedger(initial_point_count=0)
    recent_points: deque[AcceptedRunPoint] = deque(maxlen=4)
    for index in range(40):
        candidate = PointCandidate(
            {"x": float(index)},
            source="optimizer",
            based_on_completed_point_count=ledger.accepted_count,
        )
        if index % 2:
            point = _point(ledger.next_logical_ordinal, candidate)
            recent_points.append(point)
            ledger = ledger.accept(candidate, point).recent(8)
        else:
            ledger = ledger.reject(candidate, reason="retry").recent(8)

    context = PointOptimizerContext(
        observations=tuple(CompletedPointObservation(point) for point in recent_points),
        ledger=ledger,
        point_limit=24,
        completed_point_count=20,
    )

    assert ledger.decision_count == 40
    assert ledger.entry_offset == 32
    assert len(ledger.entries) == 8
    assert ledger.accepted_count == ledger.rejected_count == 20
    assert ledger.next_logical_ordinal == 20
    assert context.observation_start_index == 16
    assert tuple(item.point.ordinal for item in context.observations) == tuple(
        range(16, 20)
    )


def test_ledger_rejects_non_contiguous_accepted_point() -> None:
    ledger = PointProposalLedger(initial_point_count=2)
    candidate = PointCandidate({"x": 3.0}, source="optimizer")

    with pytest.raises(ValueError, match="logical prefix"):
        ledger.accept(candidate, _point(3, candidate))


def test_adaptive_plan_bounds_initial_domain() -> None:
    plan = AdaptivePointPlan(_Optimizer(), max_points=2)

    assert plan.optimizer_id == "test.midpoint"
    assert plan.ledger(initial_point_count=2).next_logical_ordinal == 2
    with pytest.raises(ValueError, match="initial point plan"):
        plan.ledger(initial_point_count=3)
