"""Compiler-only projection into the closed measurement value catalog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from scopecat.compiler.linking.linked import MaterializedLinkedPoints
from scopecat.compiler.typed.records import point_coordinate_ids
from scopecat.execution.points import RunPoint, RunPointCatalog
from scopecat.measurements.results import CoordinateValue
from scopecat.measurements.values import MeasurementValueCatalog


def project_measurement_catalog(
    linked_points: MaterializedLinkedPoints,
    point_ordinals: Sequence[int] | None = None,
) -> MeasurementValueCatalog:
    """Close compiler point and product inventories at the run boundary."""

    linked = linked_points.linked_plan
    points = (
        linked_points.point_domain.points
        if point_ordinals is None
        else tuple(
            linked_points.point_domain.points[ordinal] for ordinal in point_ordinals
        )
    )
    coordinate_ids = tuple(point_coordinate_ids(points))
    return MeasurementValueCatalog(
        RunPointCatalog(
            experiment_id=linked.program.id,
            experiment_kind=linked.program.kind,
            coordinate_ids=coordinate_ids,
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
        ),
        linked.product_uses,
        linked.product_defs,
    )


__all__ = ["project_measurement_catalog"]
