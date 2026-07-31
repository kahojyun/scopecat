"""Project bound compiler results into closed runtime measurement catalogs."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.typed.point_domain import MaterializedPointDomain
from scopecat.measurements.points import RunPoint, RunPointCatalog, RunPointContract
from scopecat.measurements.records import point_coordinate_ids
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.planning.point_materialization import MaterializedBoundPoints


def project_measurement_catalog(
    bound_points: MaterializedBoundPoints,
    point_ordinals: Sequence[int] | None = None,
) -> MeasurementValueCatalog:
    """Close compiler point and product inventories at the run boundary."""

    return project_measurement_catalog_from_domain(
        bound_points.bound_plan,
        bound_points.point_domain,
        point_ordinals,
    )


def project_measurement_catalog_from_domain(
    bound: BoundPlan,
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
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            coordinate_ids=coordinate_ids,
        ),
        bound.bindings.product_uses,
        bound.bindings.product_defs,
    )


def project_run_point_catalog(
    bound_points: MaterializedBoundPoints,
    point_ordinals: Sequence[int] | None = None,
) -> RunPointCatalog:
    return project_run_point_catalog_from_domain(
        bound_points.bound_plan,
        bound_points.point_domain,
        point_ordinals,
    )


def project_run_point_catalog_from_domain(
    bound: BoundPlan,
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
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            coordinate_ids=coordinate_ids,
        ),
        points=tuple(
            RunPoint(
                point.logical_id,
                {
                    coordinate_id: point.row[coordinate_id]
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
