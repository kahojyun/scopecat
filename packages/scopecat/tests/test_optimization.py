from __future__ import annotations

import numpy as np
import pytest

from scopecat.adaptive_domains import (
    AdaptiveRegion,
    DomainProposalAttempt,
    ResolvedDomainFragment,
)
from scopecat.execution.optimizer_observations import (
    project_completed_point_observation,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.optimization import (
    AdaptiveDomainPlan,
    DomainOptimizerContext,
    DomainProposalLedger,
    OptimizerScalarObservation,
    OptimizerUnavailableObservation,
)
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
)


class _Optimizer:
    id = "test.midpoint"

    def propose(self, context: DomainOptimizerContext) -> DomainProposalAttempt:
        assert context.region is not None
        return DomainProposalAttempt(
            ResolvedDomainFragment.points(
                ({"x": context.region.completed_point_count + 0.5},)
            ),
            region_ids=(context.region.id,),
            based_on_region_revisions={context.region.id: context.region.revision},
        )


def _point(ordinal: int, candidate: PointProposalAttempt) -> AcceptedRunPoint:
    return AcceptedRunPoint.accept(
        candidate,
        logical_id=LogicalPointId(PointDomainId("test.program", "points"), ordinal),
    )


def test_domain_optimizer_context_and_ledger_preserve_group_identity() -> None:
    region = AdaptiveRegion("region-0", {}, 1, 1, 1, 4)
    ledger = DomainProposalLedger(initial_point_count=1)
    context = DomainOptimizerContext(
        region=region,
        regions=(region,),
        observations=(),
        ledger=ledger,
        total_point_limit=4,
        accepted_point_count=1,
    )

    proposal = _Optimizer().propose(context)
    point_candidate = PointProposalAttempt(
        {"x": 1.5},
        source="optimizer",
        region_id=region.id,
        domain_proposal_fingerprint=proposal.proposal_fingerprint,
        based_on_region_revision=region.revision,
    )
    accepted = _point(1, point_candidate)
    ledger = ledger.accept(proposal, (accepted,))

    assert ledger.accepted_point_count == 1
    assert ledger.point_count == 2
    assert ledger.entries[0].proposal.proposal_fingerprint == (
        accepted.domain_proposal_fingerprint
    )


def test_domain_ledger_retains_bounded_decisions_with_exact_totals() -> None:
    ledger = DomainProposalLedger(initial_point_count=0)
    for index in range(40):
        proposal = DomainProposalAttempt(
            ResolvedDomainFragment.points(({"x": float(index)},))
        )
        if index % 2:
            candidate = PointProposalAttempt(
                {"x": float(index)},
                source="optimizer",
                region_id="region-0",
                domain_proposal_fingerprint=proposal.proposal_fingerprint,
            )
            ledger = ledger.accept(
                proposal,
                (_point(ledger.point_count, candidate),),
            ).recent(8)
        else:
            ledger = ledger.reject(proposal, reason="retry").recent(8)

    assert ledger.decision_count == 40
    assert ledger.entry_offset == 32
    assert len(ledger.entries) == 8
    assert ledger.accepted_point_count == ledger.rejected_count == 20
    assert ledger.optimizer_attempt_count == 40


def test_domain_ledger_does_not_retain_large_accepted_domain_payload() -> None:
    point_count = 4096
    proposal = DomainProposalAttempt(
        ResolvedDomainFragment.points(
            tuple({"x": float(index)} for index in range(point_count))
        ),
        region_ids=("region-0",),
    )
    points = tuple(
        _point(
            index,
            PointProposalAttempt(
                {"x": float(index)},
                source="optimizer",
                region_id="region-0",
                domain_proposal_fingerprint=proposal.proposal_fingerprint,
            ),
        )
        for index in range(point_count)
    )

    [decision] = (
        DomainProposalLedger(initial_point_count=0).accept(proposal, points).entries
    )

    assert decision.accepted_point_start == 0
    assert decision.accepted_point_count == point_count
    assert decision.proposal.point_count == point_count
    assert decision.proposal.region_count == 1
    assert not hasattr(decision.proposal, "fragment")


def test_optimizer_observation_projection_retains_only_metadata_free_scalars() -> None:
    point = _point(0, PointProposalAttempt({"x": 0.0}))
    record = MeasurementRecord(
        run_id="run-adaptive",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={
            "score": MeasurementScalar.create(
                value=0.25,
                unit="V",
                metadata={"raw": "large acquisition metadata"},
            ),
            "trace": MeasurementArray.create(
                values=np.arange(4096, dtype=np.float64),
                unit="V",
                metadata={"channel": "readout"},
            ),
            "missing": MeasurementUnavailable.create(
                reason="missing",
                dtype="float64",
                unit="V",
                shape=(),
                metadata={"driver": "detail"},
            ),
        },
        metadata={"batch": "discarded"},
    )

    observation = project_completed_point_observation(point, (record,))

    [measurement] = observation.measurements
    assert measurement.omitted_array_ids == ("trace",)
    score = measurement.observables["score"]
    missing = measurement.observables["missing"]
    assert isinstance(score, OptimizerScalarObservation)
    assert isinstance(missing, OptimizerUnavailableObservation)
    assert score.value == 0.25


def test_adaptive_domain_plan_bounds_initial_domain_and_axes() -> None:
    plan = AdaptiveDomainPlan(
        _Optimizer(),
        total_point_limit=2,
        adaptive_coordinate_ids=("x",),
    )

    plan.validate_initial_point_count(2)
    with pytest.raises(ValueError, match="initial point plan"):
        plan.validate_initial_point_count(3)
    with pytest.raises(ValueError, match="unique"):
        AdaptiveDomainPlan(
            _Optimizer(),
            total_point_limit=2,
            adaptive_coordinate_ids=("x", "x"),
        )
