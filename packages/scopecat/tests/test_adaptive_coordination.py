from __future__ import annotations

import pytest

from scopecat.adaptive_coordination import AdaptiveDomainCoordinator
from scopecat.adaptive_domains import (
    DomainProposalAttempt,
    RegionOptimizationComplete,
    ResolvedDomainAxis,
    ResolvedDomainFragment,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.kernel.value_types import Float, Scalar, TableColumn
from scopecat.measurements.points import RunPointCatalog, RunPointContract
from scopecat.optimization import (
    AdaptiveDomainPlan,
    CompletedPointObservation,
    DomainOptimizerContext,
    OptimizationComplete,
)


class _Optimizer:
    id = "test.domain-optimizer"

    def propose(
        self,
        context: DomainOptimizerContext,
    ) -> DomainProposalAttempt | RegionOptimizationComplete | OptimizationComplete:
        del context
        return OptimizationComplete()


def _point(
    ordinal: int,
    coordinates: dict[str, float],
    *,
    candidate: PointProposalAttempt | None = None,
) -> AcceptedRunPoint:
    return AcceptedRunPoint.accept(
        candidate or PointProposalAttempt(coordinates),
        logical_id=LogicalPointId(PointDomainId("test", "points"), ordinal),
    )


def _catalog() -> RunPointCatalog:
    columns = tuple(
        TableColumn(id, Scalar(Float())) for id in ("temperature", "frequency")
    )
    points = tuple(
        _point(index, {"temperature": temperature, "frequency": frequency})
        for index, (temperature, frequency) in enumerate(
            ((10.0, 4.0), (10.0, 5.0), (20.0, 4.0), (20.0, 5.0))
        )
    )
    return RunPointCatalog(
        RunPointContract(
            experiment_id="test",
            experiment_kind="test",
            point_count=None,
            point_limit=12,
            coordinate_columns=columns,
        ),
        points,
    )


def _coordinator(
    *,
    total_limit: int = 12,
    region_limit: int = 6,
) -> AdaptiveDomainCoordinator:
    return AdaptiveDomainCoordinator.create(
        AdaptiveDomainPlan(
            _Optimizer(),
            total_point_limit=total_limit,
            adaptive_coordinate_ids=("frequency",),
            per_region_point_limit=region_limit,
        ),
        _catalog(),
    )


def _accept_bound(
    coordinator: AdaptiveDomainCoordinator,
    proposal: DomainProposalAttempt,
) -> tuple[AcceptedRunPoint, ...]:
    bound = coordinator.bind(proposal)
    start = coordinator.accepted_point_count
    points = tuple(
        _point(start + index, dict(candidate.coordinates), candidate=candidate)
        for index, candidate in enumerate(bound.candidates)
    )
    coordinator.accept(bound, points)
    return points


def test_static_outer_scan_creates_independent_adaptive_regions() -> None:
    coordinator = _coordinator()

    first, second = coordinator.regions
    assert first.coordinates == {"temperature": 10.0}
    assert second.coordinates == {"temperature": 20.0}
    assert first.point_count == second.point_count == 2


def test_one_fragment_can_extend_one_or_all_outer_regions() -> None:
    coordinator = _coordinator()
    first, second = coordinator.regions
    fragment = ResolvedDomainFragment.grid(
        ResolvedDomainAxis.range_axis("frequency", 5.5, 6.0, points=2)
    )

    first_points = _accept_bound(
        coordinator,
        DomainProposalAttempt(fragment, region_ids=(first.id,)),
    )
    all_points = _accept_bound(
        coordinator,
        DomainProposalAttempt(fragment, region_ids=(first.id, second.id)),
    )

    assert {point.coordinates["temperature"] for point in first_points} == {10.0}
    assert tuple(point.coordinates["temperature"] for point in all_points) == (
        10.0,
        10.0,
        20.0,
        20.0,
    )


def test_completion_in_another_region_does_not_stale_a_proposal() -> None:
    coordinator = _coordinator()
    first, second = coordinator.regions
    fragment = ResolvedDomainFragment.points(({"frequency": 5.5},))
    proposal = DomainProposalAttempt(
        fragment,
        region_ids=(first.id,),
        based_on_region_revisions={first.id: first.revision},
    )
    point = _catalog().points[2]

    coordinator.add_observation(CompletedPointObservation(point))

    assert coordinator.bind(proposal).proposal.region_ids == (first.id,)
    assert coordinator.regions[1].revision == second.revision + 1


def test_region_completion_keeps_other_regions_open() -> None:
    coordinator = _coordinator()
    first, second = coordinator.regions

    coordinator.apply_completion(
        RegionOptimizationComplete("first region converged"),
        region_id=first.id,
    )

    context = coordinator.optimizer_context()
    assert context is not None
    assert context.region is not None
    assert context.region.id == second.id


def test_multi_region_fragment_is_rejected_atomically_when_over_budget() -> None:
    coordinator = _coordinator(total_limit=7)
    first, second = coordinator.regions
    proposal = DomainProposalAttempt(
        ResolvedDomainFragment.grid(
            ResolvedDomainAxis.range_axis("frequency", 5.5, 6.0, points=2)
        ),
        region_ids=(first.id, second.id),
    )

    with pytest.raises(ValueError, match="total point budget"):
        coordinator.bind(proposal)

    assert coordinator.accepted_point_count == 4
    assert tuple(region.point_count for region in coordinator.regions) == (2, 2)
