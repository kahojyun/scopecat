"""Coordinate compatible domain proposals across static outer scan regions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product
from typing import cast

from scopecat.adaptive_domains import (
    AdaptiveRegion,
    DomainProposalAttempt,
    OperatorDomainRequest,
    RegionOptimizationComplete,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.kernel.value_data import CellValue
from scopecat.measurements.points import RunPointCatalog
from scopecat.optimization import (
    OPTIMIZER_OBSERVATION_WINDOW,
    AdaptiveDomainPlan,
    CompletedPointObservation,
    DomainOptimizerContext,
    DomainProposalDecision,
    DomainProposalLedger,
    OptimizationComplete,
)
from scopecat.program.point_domain import point_axis_size, point_axis_value


@dataclass(frozen=True, slots=True)
class BoundDomainProposal:
    """A fresh domain proposal normalized to ordered full coordinate rows."""

    proposal: DomainProposalAttempt
    candidates: tuple[PointProposalAttempt, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveRegionLayout:
    """Pure initial partition of an adaptive run across its static outer axes."""

    coordinate_ids: tuple[str, ...]
    adaptive_coordinate_ids: tuple[str, ...]
    outer_coordinate_ids: tuple[str, ...]
    regions: tuple[AdaptiveRegion, ...]


def derive_adaptive_region_layout(
    plan: AdaptiveDomainPlan,
    catalog: RunPointCatalog,
) -> AdaptiveRegionLayout:
    coordinate_ids = catalog.coordinate_ids
    adaptive_ids = plan.adaptive_coordinate_ids or coordinate_ids
    unknown = sorted(set(adaptive_ids) - set(coordinate_ids))
    if unknown:
        raise ValueError(
            "adaptive coordinates are not admitted axes: " + ", ".join(unknown)
        )
    adaptive_id_set = set(adaptive_ids)
    outer_ids = tuple(
        coordinate_id
        for coordinate_id in coordinate_ids
        if coordinate_id not in adaptive_id_set
    )
    grouped = _initial_regions(catalog, outer_ids)
    if not grouped:
        if outer_ids:
            raise ValueError(
                "an adaptive plan with static outer axes requires seeded points"
            )
        grouped[_outer_fingerprint({})] = ({}, 0)
    plan.validate_initial_point_count(len(catalog.points))
    region_limit = plan.per_region_point_limit or plan.total_point_limit
    regions: list[AdaptiveRegion] = []
    for index, (fingerprint, (coordinates, point_count)) in enumerate(grouped.items()):
        if point_count > region_limit:
            raise ValueError(
                "initial region points exceed the adaptive region point limit"
            )
        regions.append(
            AdaptiveRegion(
                id=f"region-{index}.{fingerprint[:12]}",
                coordinates=coordinates,
                point_count=point_count,
                completed_point_count=0,
                revision=0,
                point_limit=region_limit,
            )
        )
    return AdaptiveRegionLayout(
        coordinate_ids=coordinate_ids,
        adaptive_coordinate_ids=adaptive_ids,
        outer_coordinate_ids=outer_ids,
        regions=tuple(regions),
    )


@dataclass(slots=True)
class _RegionState:
    id: str
    coordinates: dict[str, CellValue]
    point_count: int
    completed_point_count: int
    revision: int
    point_limit: int
    ledger: DomainProposalLedger
    observations: list[CompletedPointObservation] = field(default_factory=list)
    closed: bool = False
    stop_reason: str | None = None

    def view(self) -> AdaptiveRegion:
        return AdaptiveRegion(
            id=self.id,
            coordinates=self.coordinates,
            point_count=self.point_count,
            completed_point_count=self.completed_point_count,
            revision=self.revision,
            point_limit=self.point_limit,
            closed=self.closed,
            stop_reason=self.stop_reason,
        )


@dataclass(slots=True)
class AdaptiveDomainCoordinator:
    """Own region freshness, observations, budgets, and domain normalization."""

    plan: AdaptiveDomainPlan
    coordinate_ids: tuple[str, ...]
    adaptive_coordinate_ids: tuple[str, ...]
    outer_coordinate_ids: tuple[str, ...]
    _regions: dict[str, _RegionState]
    _region_id_by_outer_fingerprint: dict[str, str]
    _global_ledger: DomainProposalLedger
    _global_observations: list[CompletedPointObservation]
    accepted_point_count: int
    closed: bool = False
    stop_reason: str | None = None

    @classmethod
    def create(
        cls,
        plan: AdaptiveDomainPlan,
        catalog: RunPointCatalog,
    ) -> AdaptiveDomainCoordinator:
        layout = derive_adaptive_region_layout(plan, catalog)
        regions = {
            region.id: _RegionState(
                id=region.id,
                coordinates=dict(region.coordinates),
                point_count=region.point_count,
                completed_point_count=0,
                revision=0,
                point_limit=region.point_limit,
                ledger=DomainProposalLedger(region.point_count),
            )
            for region in layout.regions
        }
        return cls(
            plan=plan,
            coordinate_ids=layout.coordinate_ids,
            adaptive_coordinate_ids=layout.adaptive_coordinate_ids,
            outer_coordinate_ids=layout.outer_coordinate_ids,
            _regions=regions,
            _region_id_by_outer_fingerprint={
                _outer_fingerprint(dict(region.coordinates)): region.id
                for region in layout.regions
            },
            _global_ledger=DomainProposalLedger(len(catalog.points)),
            _global_observations=[],
            accepted_point_count=len(catalog.points),
        )

    @property
    def regions(self) -> tuple[AdaptiveRegion, ...]:
        return tuple(region.view() for region in self._regions.values())

    @property
    def ledger(self) -> DomainProposalLedger:
        return self._global_ledger

    def optimizer_context(self) -> DomainOptimizerContext | None:
        """Return the next independent region context, or one global context."""

        if self.closed or self.accepted_point_count >= self.plan.total_point_limit:
            return None
        if self.plan.scope == "global":
            return DomainOptimizerContext(
                region=None,
                regions=self.regions,
                observations=tuple(self._global_observations),
                ledger=self._global_ledger,
                total_point_limit=self.plan.total_point_limit,
                accepted_point_count=self.accepted_point_count,
            )
        for region in self._regions.values():
            if not region.closed and region.point_count >= region.point_limit:
                self._close_region(region, "region point budget exhausted")
            if not region.closed:
                return DomainOptimizerContext(
                    region=region.view(),
                    regions=self.regions,
                    observations=tuple(region.observations),
                    ledger=region.ledger,
                    total_point_limit=self.plan.total_point_limit,
                    accepted_point_count=self.accepted_point_count,
                )
        self.close("all adaptive regions completed")
        return None

    def bind(self, proposal: DomainProposalAttempt) -> BoundDomainProposal:
        """Validate one entire fragment and expand it to full coordinate rows."""

        region_ids = proposal.region_ids
        if not region_ids:
            if self.plan.scope == "per_region":
                context = self.optimizer_context()
                if context is None or context.region is None:
                    raise ValueError("no adaptive region remains open")
                region_ids = (context.region.id,)
            elif len(self._regions) == 1:
                region_ids = tuple(self._regions)
            else:
                raise ValueError(
                    "global domain proposals must select one or more outer regions"
                )
        missing = sorted(set(region_ids) - set(self._regions))
        if missing:
            raise ValueError("unknown adaptive regions: " + ", ".join(missing))
        if set(proposal.fragment.coordinate_ids) != set(self.adaptive_coordinate_ids):
            raise ValueError(
                "domain fragment coordinates must exactly match the adaptive axes"
            )
        if proposal.source != "operator" and any(
            self._regions[region_id].closed for region_id in region_ids
        ):
            raise ValueError("domain proposal targets a closed adaptive region")
        expected_revisions = {
            region_id: self._regions[region_id].revision for region_id in region_ids
        }
        if proposal.based_on_region_revisions and (
            dict(proposal.based_on_region_revisions) != expected_revisions
        ):
            raise ValueError("domain proposal is stale for its selected regions")
        bound_proposal = replace(
            proposal,
            region_ids=region_ids,
            based_on_region_revisions=expected_revisions,
        )
        proposal_fingerprint = bound_proposal.proposal_fingerprint
        count_per_region = proposal.fragment.point_count
        total_count = count_per_region * len(region_ids)
        if self.accepted_point_count + total_count > self.plan.total_point_limit:
            raise ValueError("domain proposal exceeds the remaining total point budget")
        for region_id in region_ids:
            region = self._regions[region_id]
            if region.point_count + count_per_region > region.point_limit:
                raise ValueError(
                    f"domain proposal exceeds the point budget for {region_id}"
                )
        candidates = tuple(
            PointProposalAttempt(
                coordinates={**self._regions[region_id].coordinates, **row},
                source=bound_proposal.source,
                region_id=region_id,
                domain_proposal_fingerprint=proposal_fingerprint,
                based_on_region_revision=expected_revisions[region_id],
            )
            for region_id in region_ids
            for row in bound_proposal.fragment.rows()
        )
        return BoundDomainProposal(bound_proposal, candidates)

    def operator_proposal(
        self,
        request: OperatorDomainRequest,
    ) -> DomainProposalAttempt:
        """Resolve an operator region scope without changing fragment semantics."""

        if request.region_scope == "current":
            context = self.optimizer_context()
            if context is None or context.region is None:
                raise ValueError("no current adaptive region is available")
            region_ids = (context.region.id,)
        elif request.region_scope == "all":
            region_ids = tuple(self._regions)
        else:
            region_ids = request.region_ids
            unknown = sorted(set(region_ids) - set(self._regions))
            if unknown:
                raise ValueError("unknown adaptive regions: " + ", ".join(unknown))
        if not region_ids:
            raise ValueError("operator domain request selects no open regions")
        return DomainProposalAttempt(
            fragment=request.fragment,
            region_ids=region_ids,
            source="operator",
        )

    def accept(
        self,
        bound: BoundDomainProposal,
        points: tuple[AcceptedRunPoint, ...],
    ) -> DomainProposalDecision:
        if len(points) != len(bound.candidates):
            raise ValueError("accepted domain points do not match the bound fragment")
        by_region: dict[str, list[AcceptedRunPoint]] = {
            region_id: [] for region_id in bound.proposal.region_ids
        }
        proposal_fingerprint = bound.proposal.proposal_fingerprint
        for point in points:
            if point.domain_proposal_fingerprint != proposal_fingerprint:
                raise ValueError("accepted point lost its domain proposal identity")
            region_id = cast("str", point.region_id)
            by_region[region_id].append(point)
        for region_id, selected in by_region.items():
            region = self._regions[region_id]
            region.point_count += len(selected)
            region.revision += 1
            region.ledger = region.ledger.accept(
                bound.proposal,
                tuple(selected),
            ).recent()
        self._global_ledger = self._global_ledger.accept(
            bound.proposal,
            points,
        ).recent()
        self.accepted_point_count += len(points)
        return self._global_ledger.entries[-1]

    def reject(
        self,
        proposal: DomainProposalAttempt,
        *,
        reason: str,
    ) -> DomainProposalDecision:
        selected = proposal.region_ids or tuple(self._regions)
        for region_id in selected:
            region = self._regions.get(region_id)
            if region is not None:
                region.ledger = region.ledger.reject(proposal, reason=reason).recent()
        self._global_ledger = self._global_ledger.reject(
            proposal,
            reason=reason,
        ).recent()
        return self._global_ledger.entries[-1]

    def add_observation(self, observation: CompletedPointObservation) -> None:
        region = self._region_for_point(observation.point)
        region.completed_point_count += 1
        region.revision += 1
        region.observations.append(observation)
        del region.observations[:-OPTIMIZER_OBSERVATION_WINDOW]
        self._global_observations.append(observation)
        del self._global_observations[:-OPTIMIZER_OBSERVATION_WINDOW]

    def apply_completion(
        self,
        completion: RegionOptimizationComplete | OptimizationComplete,
        *,
        region_id: str | None,
    ) -> None:
        if isinstance(completion, OptimizationComplete):
            self.close(completion.reason)
            return
        if region_id is None:
            raise ValueError("region completion requires a selected region")
        self._close_region(self._regions[region_id], completion.reason)

    def close(self, reason: str) -> None:
        if not reason:
            raise ValueError("adaptive plan stop reason must be non-empty")
        self.closed = True
        self.stop_reason = reason

    def _close_region(self, region: _RegionState, reason: str) -> None:
        region.closed = True
        region.stop_reason = reason
        region.revision += 1

    def _region_for_point(self, point: AcceptedRunPoint) -> _RegionState:
        if point.region_id is not None:
            return self._regions[point.region_id]
        outer = {
            coordinate_id: point.coordinates[coordinate_id]
            for coordinate_id in self.outer_coordinate_ids
        }
        region_id = self._region_id_by_outer_fingerprint[_outer_fingerprint(outer)]
        return self._regions[region_id]


def _outer_fingerprint(coordinates: dict[str, CellValue]) -> str:
    return stable_content_hash(content_fingerprint(coordinates))


def _initial_regions(
    catalog: RunPointCatalog,
    outer_ids: tuple[str, ...],
) -> dict[str, tuple[dict[str, CellValue], int]]:
    if not outer_ids:
        return {_outer_fingerprint({}): ({}, len(catalog.points))}
    if catalog.contract.domain_layout == "product_grid":
        axes = {axis.id: axis for axis in catalog.contract.domain_axes}
        if set(outer_ids).issubset(axes):
            outer_values = tuple(
                tuple(
                    point_axis_value(axes[axis_id].source, index)
                    for index in range(point_axis_size(axes[axis_id].source))
                )
                for axis_id in outer_ids
            )
            region_count = 1
            for values in outer_values:
                region_count *= len(values)
            if region_count < 1 or len(catalog.points) % region_count:
                raise ValueError("initial points do not partition over outer axes")
            points_per_region = len(catalog.points) // region_count
            return {
                _outer_fingerprint(coordinates): (coordinates, points_per_region)
                for values in product(*outer_values)
                for coordinates in (dict(zip(outer_ids, values, strict=True)),)
            }
    grouped: dict[str, tuple[dict[str, CellValue], int]] = {}
    for point in catalog.points:
        outer = {
            coordinate_id: point.coordinates[coordinate_id]
            for coordinate_id in outer_ids
        }
        fingerprint = _outer_fingerprint(outer)
        coordinates, count = grouped.get(fingerprint, (outer, 0))
        grouped[fingerprint] = (coordinates, count + 1)
    return grouped


__all__ = [
    "AdaptiveDomainCoordinator",
    "AdaptiveRegionLayout",
    "BoundDomainProposal",
    "derive_adaptive_region_layout",
]
