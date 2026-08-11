"""Project bound compiler results into closed runtime measurement catalogs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.compiler.value_resolution import BoundValueResolver
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Scalar
from scopecat.measurements.points import RunPoint, RunPointCatalog, RunPointContract
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.planning.point_materialization import MaterializedBoundPoints
from scopecat.program.expressions import (
    ComputeResultArrayExpr,
    ComputeResultScalarExpr,
    LiteralArrayExpr,
    ScalarExpr,
)


def project_measurement_catalog(
    bound_points: MaterializedBoundPoints,
) -> MeasurementValueCatalog:
    """Close typed point-domain and product contracts at the run boundary."""

    bound = bound_points.bound_plan
    point_domain = bound_points.point_domain
    coordinate_columns = bound.point_domain.coordinate_columns
    axis_values = _product_grid_axis_values(bound_points)
    return MeasurementValueCatalog(
        RunPointContract(
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            point_count=len(point_domain.points),
            coordinate_columns=coordinate_columns,
            domain_layout=point_domain.layout,
            domain_axis_sizes=point_domain.axis_sizes,
            domain_axis_values=axis_values,
        ),
        bound.bindings.product_uses,
        bound.bindings.product_defs,
    )


def project_run_point_catalog(
    bound_points: MaterializedBoundPoints,
    point_ordinals: Sequence[int] | None = None,
) -> RunPointCatalog:
    """Project runtime points and their typed coordinate contract."""

    bound = bound_points.bound_plan
    point_domain = bound_points.point_domain
    all_points = point_domain.points
    points_by_ordinal = {point.logical_ordinal: point for point in all_points}
    points = (
        all_points
        if point_ordinals is None
        else tuple(points_by_ordinal[ordinal] for ordinal in point_ordinals)
    )
    coordinate_columns = bound.point_domain.coordinate_columns
    coordinate_ids = tuple(column.id for column in coordinate_columns)
    axis_values = _product_grid_axis_values(bound_points)
    return RunPointCatalog(
        contract=RunPointContract(
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            point_count=len(all_points),
            coordinate_columns=coordinate_columns,
            domain_layout=point_domain.layout,
            domain_axis_sizes=point_domain.axis_sizes,
            domain_axis_values=axis_values,
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


def _product_grid_axis_values(
    bound_points: MaterializedBoundPoints,
) -> tuple[tuple[str, tuple[CellValue, ...]], ...]:
    point_domain = bound_points.point_domain
    return point_domain.axis_values if point_domain.layout == "product_grid" else ()


def project_static_value_record_candidates(
    bound_points: MaterializedBoundPoints,
    additional_value_ids: Sequence[ValueId] = (),
) -> tuple[ValueRecordCandidate, ...]:
    """Evaluate demanded plan-stage values once for every materialized point."""

    bound = bound_points.bound_plan
    values = BoundValueResolver(bound.program, bound.bindings)
    candidates: list[ValueRecordCandidate] = []
    selected_value_ids = tuple(
        dict.fromkeys(
            (
                *(record.value_id for record in bound.bindings.value_record_uses),
                *additional_value_ids,
            )
        )
    )
    for value_id in selected_value_ids:
        expression = values[value_id]
        if isinstance(expression, ComputeResultScalarExpr | ComputeResultArrayExpr):
            continue
        if isinstance(expression, LiteralArrayExpr):
            candidates.extend(
                ValueRecordCandidate(
                    logical_point_id=point.logical_id,
                    value_id=value_id,
                    value=expression.value,
                )
                for point in bound_points.point_domain.points
            )
            continue
        if not isinstance(expression, ScalarExpr) or isinstance(
            expression,
            ComputeResultScalarExpr,
        ):
            raise AssertionError("static value records must resolve to scalar plans")
        for point, parameters in zip(
            bound_points.point_domain.points,
            bound_points.point_parameters,
            strict=True,
        ):
            candidates.append(
                ValueRecordCandidate(
                    logical_point_id=point.logical_id,
                    value_id=value_id,
                    value=evaluate_scalar(
                        expression,
                        EvalContext(params=parameters, point_row=point.row),
                        expected_type=cast(
                            "Scalar",
                            bound.program.value_types[value_id],
                        ),
                    ),
                )
            )
    return tuple(candidates)


__all__ = [
    "project_measurement_catalog",
    "project_run_point_catalog",
    "project_static_value_record_candidates",
]
