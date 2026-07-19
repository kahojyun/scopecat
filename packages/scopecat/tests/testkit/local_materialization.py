from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.linking.linked import LinkedPlan, materialize_linked_points
from scopecat.compiler.typed.records import point_coordinate_ids
from scopecat.execution.local.program import ComputeOperation, LocalOperation
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.results import CoordinateValue
from scopecat.planning.local_effects import local_operation_resource_claims
from scopecat.planning.local_materialization import (
    materialize_local_execution as lower_local_execution,
)
from scopecat.planning.local_materialization import (
    prepare_local_target,
)


@dataclass(frozen=True, slots=True)
class MaterializedPointEffects:
    """Test view pairing production operations with canonical point metadata."""

    point_index: int
    logical_id: LogicalPointId
    coordinates: Mapping[str, CoordinateValue]
    operations: tuple[LocalOperation, ...]


@dataclass(frozen=True, slots=True)
class MaterializedLocalEffects:
    """Test-only inspection view of canonical point effects."""

    points: tuple[MaterializedPointEffects, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]
    run_compute_operations: tuple[ComputeOperation, ...] = ()


def materialize_local_execution(
    linked: LinkedPlan,
    *,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
    instrument_order: Sequence[str] = (),
) -> MaterializedLocalEffects:
    """Test convenience for linking-era tests that do not inspect point closure."""

    linked_points = materialize_linked_points(linked)
    selected_product_use_ids = (
        frozenset(use.id for use in linked.program.product_uses)
        if product_use_ids is None
        else frozenset(product_use_ids)
    )
    target = prepare_local_target(
        linked,
        product_use_ids=selected_product_use_ids,
        instrument_order=instrument_order,
    )
    lowered = lower_local_execution(
        linked_points,
        target=target,
        point_count=len(linked_points.point_domain.points),
    )
    coordinate_ids = set(point_coordinate_ids(linked_points.point_domain.points))
    operations_by_point: dict[int, list[LocalOperation]] = {
        point.logical_ordinal: [] for point in linked_points.point_domain.points
    }
    ordered_effects = (
        *lowered.compute_operations,
        *(effect for group in lowered.effect_operations for effect in group),
        *lowered.collect_operations,
    )
    for effect in ordered_effects:
        for point_index in effect.point_indices:
            operations_by_point[point_index].append(effect.operation)
    claims = tuple(
        dict.fromkeys(
            claim
            for effect in ordered_effects
            for claim in local_operation_resource_claims(effect.operation)
        )
    )
    instrument_ids = {claim.id for claim in claims if claim.kind == "instrument"}
    resource_order = (
        *(item for item in target.instrument_order if item in instrument_ids),
        *sorted(instrument_ids - set(target.instrument_order)),
    )
    return MaterializedLocalEffects(
        points=tuple(
            MaterializedPointEffects(
                point_index=point.logical_ordinal,
                logical_id=point.logical_id,
                coordinates={
                    name: cast("CoordinateValue", value)
                    for name, value in point.row.items()
                    if name in coordinate_ids
                },
                operations=tuple(operations_by_point[point.logical_ordinal]),
            )
            for point in linked_points.point_domain.points
        ),
        resource_order=resource_order,
        resource_claims=claims,
        run_compute_operations=target.run_operations,
    )


def operations_of_type[T: LocalOperation](
    point: MaterializedPointEffects | Sequence[LocalOperation],
    operation_type: type[T],
) -> tuple[T, ...]:
    """Select concrete point operations for focused test assertions."""

    operations = (
        point.operations if isinstance(point, MaterializedPointEffects) else point
    )
    return tuple(
        operation for operation in operations if isinstance(operation, operation_type)
    )
