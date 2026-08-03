"""Project bound compiler results into closed runtime measurement catalogs."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.point_domain import MaterializedPointDomain
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.compiler.value_resolution import BoundValueResolver
from scopecat.measurements.points import RunPoint, RunPointCatalog, RunPointContract
from scopecat.measurements.records import (
    ValueRecordCandidate,
    point_coordinate_ids,
)
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.planning.point_materialization import MaterializedBoundPoints
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpr


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
            domain_layout=point_domain.layout,
            domain_axis_sizes=point_domain.axis_sizes,
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
            domain_layout=point_domain.layout,
            domain_axis_sizes=point_domain.axis_sizes,
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


def project_static_value_record_candidates(
    bound_points: MaterializedBoundPoints,
) -> tuple[ValueRecordCandidate, ...]:
    """Evaluate plan-stage value records once for every materialized point."""

    bound = bound_points.bound_plan
    values = BoundValueResolver(bound.program, bound.bindings)
    candidates: list[ValueRecordCandidate] = []
    for record in bound.bindings.value_record_uses:
        if record.requires_execution:
            continue
        expression = values[record.value_id]
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
                    value_id=record.value_id,
                    value=evaluate_scalar(
                        expression,
                        EvalContext(params=parameters, point_row=point.row),
                        expected_type=record.value_type,
                    ),
                )
            )
    return tuple(candidates)


__all__ = [
    "project_measurement_catalog",
    "project_measurement_catalog_from_domain",
    "project_run_point_catalog",
    "project_run_point_catalog_from_domain",
    "project_static_value_record_candidates",
]
