"""Project bound compiler results into closed runtime measurement catalogs."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import cast, overload, override

from scopecat.compiler.point_domain import MaterializedPoint
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar, evaluate_table_value
from scopecat.compiler.value_resolution import BoundValueResolver
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.kernel.value_types import Scalar, Table
from scopecat.measurements.points import RunPointCatalog, RunPointContract
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.planning.point_materialization import MaterializedBoundPoints
from scopecat.program.expressions import (
    ComputeResultArrayExpr,
    ComputeResultScalarExpr,
    LiteralArrayExpr,
    ScalarExpr,
)
from scopecat.program.table_values import TableSource


def project_measurement_catalog(
    bound_points: MaterializedBoundPoints,
    *,
    point_limit: int | None = None,
) -> MeasurementValueCatalog:
    """Close typed point-domain and product contracts at the run boundary."""

    bound = bound_points.bound_plan
    point_domain = bound_points.point_domain
    coordinate_columns = bound.point_domain.coordinate_columns
    return MeasurementValueCatalog(
        RunPointContract(
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            point_count=(len(point_domain.points) if point_limit is None else None),
            point_limit=(
                len(point_domain.points) if point_limit is None else point_limit
            ),
            coordinate_columns=coordinate_columns,
            domain_layout=point_domain.layout,
            domain_axes=point_domain.axes,
        ),
        bound.bindings.product_uses,
        bound.bindings.product_defs,
    )


def project_run_point_catalog(
    bound_points: MaterializedBoundPoints,
    point_ordinals: Sequence[int] | None = None,
    *,
    point_limit: int | None = None,
) -> RunPointCatalog:
    """Project runtime points and their typed coordinate contract."""

    bound = bound_points.bound_plan
    point_domain = bound_points.point_domain
    coordinate_columns = bound.point_domain.coordinate_columns
    coordinate_ids = tuple(column.id for column in coordinate_columns)
    return RunPointCatalog(
        contract=RunPointContract(
            experiment_id=bound.program.experiment_id,
            experiment_kind=bound.program.kind,
            point_count=(len(point_domain.points) if point_limit is None else None),
            point_limit=(
                len(point_domain.points) if point_limit is None else point_limit
            ),
            coordinate_columns=coordinate_columns,
            domain_layout=point_domain.layout,
            domain_axes=point_domain.axes,
        ),
        points=_RunPointSequence(
            point_domain.points,
            coordinate_ids=coordinate_ids,
            ordinals=(
                range(len(point_domain.points))
                if point_ordinals is None
                else tuple(point_ordinals)
            ),
        ),
    )


class _RunPointSequence(Sequence[AcceptedRunPoint]):
    __slots__ = ("_coordinate_ids", "_ordinals", "_points")

    def __init__(
        self,
        points: Sequence[MaterializedPoint],
        *,
        coordinate_ids: tuple[str, ...],
        ordinals: Sequence[int],
    ) -> None:
        self._points = points
        self._coordinate_ids = coordinate_ids
        self._ordinals = ordinals

    @override
    def __len__(self) -> int:
        return len(self._ordinals)

    @overload
    def __getitem__(self, index: int) -> AcceptedRunPoint: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[AcceptedRunPoint, ...]: ...

    @override
    def __getitem__(
        self, index: int | slice
    ) -> AcceptedRunPoint | tuple[AcceptedRunPoint, ...]:
        if isinstance(index, slice):
            return tuple(self[offset] for offset in range(*index.indices(len(self))))
        point = self._points[self._ordinals[index]]
        return AcceptedRunPoint.accept(
            PointProposalAttempt(
                {
                    coordinate_id: point.row[coordinate_id]
                    for coordinate_id in self._coordinate_ids
                }
            ),
            logical_id=point.logical_id,
        )

    @override
    def __iter__(self) -> Iterator[AcceptedRunPoint]:
        return (self[index] for index in range(len(self)))


def project_static_value_record_candidates(
    bound_points: MaterializedBoundPoints,
    additional_value_ids: Sequence[ValueId] = (),
    *,
    point_ordinals: Sequence[int] | None = None,
) -> tuple[ValueRecordCandidate, ...]:
    """Evaluate demanded plan-stage values for one selected point coverage."""

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
    ordinals = (
        range(len(bound_points.point_domain.points))
        if point_ordinals is None
        else point_ordinals
    )
    selected_points = tuple(
        bound_points.point_domain.points[ordinal] for ordinal in ordinals
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
                for point in selected_points
            )
            continue
        value_type = bound.program.value_types[value_id]
        if isinstance(value_type, Table):
            for point in selected_points:
                parameters = bound_points.point_parameters[point.logical_ordinal]
                candidates.append(
                    ValueRecordCandidate(
                        logical_point_id=point.logical_id,
                        value_id=value_id,
                        value=evaluate_table_value(
                            cast("TableSource", expression),
                            value_type,
                            EvalContext(params=parameters, point_row=point.row),
                        ),
                    )
                )
            continue
        if not isinstance(expression, ScalarExpr) or isinstance(
            expression,
            ComputeResultScalarExpr,
        ):
            raise AssertionError("static value records must resolve to scalar plans")
        for point in selected_points:
            parameters = bound_points.point_parameters[point.logical_ordinal]
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
