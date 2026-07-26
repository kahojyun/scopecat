"""Compiler-only projection into the closed measurement value catalog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from scopecat.compiler.linking.linked import LinkedPlan, MaterializedLinkedPoints
from scopecat.compiler.typed.point_domain import MaterializedPointDomain
from scopecat.compiler.typed.records import point_coordinate_ids
from scopecat.execution.points import RunPoint, RunPointCatalog, RunPointContract
from scopecat.measurements.results import CoordinateValue
from scopecat.measurements.values import MeasurementValueCatalog


def project_measurement_catalog(
    linked_points: MaterializedLinkedPoints,
    point_ordinals: Sequence[int] | None = None,
) -> MeasurementValueCatalog:
    """Close compiler point and product inventories at the run boundary."""

    return project_measurement_catalog_from_domain(
        linked_points.linked_plan,
        linked_points.point_domain,
        point_ordinals,
    )


def project_measurement_catalog_from_domain(
    linked: LinkedPlan,
    point_domain: MaterializedPointDomain,
    point_ordinals: Sequence[int] | None = None,
) -> MeasurementValueCatalog:
    """Project measurement contracts without materializing point parameters."""

    all_points = point_domain.points
    points_by_ordinal = {point.logical_ordinal: point for point in all_points}
    points = (
        all_points
        if point_ordinals is None
        else tuple(points_by_ordinal[ordinal] for ordinal in point_ordinals)
    )
    coordinate_ids = tuple(point_coordinate_ids(points))
    return MeasurementValueCatalog(
        RunPointContract(
            experiment_id=linked.program.id,
            experiment_kind=linked.program.kind,
            coordinate_ids=coordinate_ids,
        ),
        linked.program.product_uses,
        linked.program.product_defs,
    )


def project_run_point_catalog(
    linked_points: MaterializedLinkedPoints,
    point_ordinals: Sequence[int] | None = None,
) -> RunPointCatalog:
    return project_run_point_catalog_from_domain(
        linked_points.linked_plan,
        linked_points.point_domain,
        point_ordinals,
    )


def project_run_point_catalog_from_domain(
    linked: LinkedPlan,
    point_domain: MaterializedPointDomain,
    point_ordinals: Sequence[int] | None = None,
) -> RunPointCatalog:
    """Project runtime points without materializing point parameters."""

    all_points = point_domain.points
    points_by_ordinal = {point.logical_ordinal: point for point in all_points}
    points = (
        all_points
        if point_ordinals is None
        else tuple(points_by_ordinal[ordinal] for ordinal in point_ordinals)
    )
    coordinate_ids = tuple(point_coordinate_ids(points))
    return RunPointCatalog(
        contract=RunPointContract(
            experiment_id=linked.program.id,
            experiment_kind=linked.program.kind,
            coordinate_ids=coordinate_ids,
        ),
        points=tuple(
            RunPoint(
                point.logical_id,
                {
                    coordinate_id: cast("CoordinateValue", point.row[coordinate_id])
                    for coordinate_id in coordinate_ids
                },
            )
            for point in points
        ),
    )


__all__ = [
    "project_measurement_catalog",
    "project_measurement_catalog_from_domain",
    "project_run_point_catalog",
    "project_run_point_catalog_from_domain",
]
