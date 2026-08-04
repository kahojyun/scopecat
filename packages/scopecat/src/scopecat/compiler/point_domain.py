"""Exact symbolic point domains and stable logical point identity."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import cast

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.verification import (
    ExpressionImportNamespace,
    scalar_expression_imports,
    scalar_expression_point_requirement,
)
from scopecat.kernel.point_identity import (
    LogicalPointId,
    PointDomainId,
    PointDomainLayout,
)
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.value_data import CellValue, Row
from scopecat.kernel.value_types import Entity, Table, TableColumn
from scopecat.kernel.value_validation import coerce_literal
from scopecat.program.expressions import ScalarExpr
from scopecat.program.point_domain import (
    PointAxes,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainPath,
    PointDomainShape,
    PointDomainShapeError,
    analyze_point_domain,
    is_point_coordinate_type,
    point_axis_linear_value,
)

type PointRowNormalizer = Callable[[Row], Mapping[str, object]]
type CompilerPointAxes = PointAxes[ScalarExpr]


@dataclass(frozen=True, slots=True)
class PointDomain:
    """One exact ordered logical point space."""

    axes: CompilerPointAxes
    id: str = "root"
    layout: PointDomainLayout = "product_grid"

    @property
    def value_type(self) -> Table:
        return analyze_point_domain(self.axes, layout=self.layout).value_type


@dataclass(frozen=True, slots=True)
class PointDomainVerificationIssue:
    """One static violation at the point-domain boundary."""

    code: str
    path: PointDomainPath
    message: str


class PointDomainVerificationError(ValueError):
    """A symbolic point domain is not closed and well typed."""

    def __init__(self, issues: Sequence[PointDomainVerificationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


class PointDomainEvaluationError(ValueError):
    """A dynamic linear-axis center failed during point evaluation."""

    def __init__(self, path: PointDomainPath, error: Exception) -> None:
        self.path = path
        self.error = error
        rendered = "/".join(str(part) for part in path)
        prefix = f"point domain {rendered}" if rendered else "point domain root"
        super().__init__(f"{prefix} failed: {error}")


@dataclass(frozen=True, slots=True)
class VerifiedPointDomain:
    """A shape-checked exact point domain."""

    id: PointDomainId
    axes: CompilerPointAxes
    shape: PointDomainShape
    layout: PointDomainLayout = "product_grid"

    @property
    def cardinality(self) -> int:
        return self.shape.cardinality

    @property
    def entity_columns(self) -> tuple[str, ...]:
        return tuple(
            column.id
            for column in self.value_type.columns
            if isinstance(column.value_type.atom, Entity)
        )

    @property
    def value_type(self) -> Table:
        return self.shape.value_type

    @property
    def coordinate_columns(self) -> tuple[TableColumn, ...]:
        return tuple(
            column
            for column in self.value_type.columns
            if is_point_coordinate_type(column.value_type)
        )

    @property
    def axis_sizes(self) -> tuple[tuple[str, int], ...]:
        """Return declaration-ordered source extents for durable layout metadata."""

        return tuple(
            (
                axis.id,
                axis.source.count
                if isinstance(axis.source, PointAxisLinear)
                else len(axis.source.values),
            )
            for axis in self.axes
        )


@dataclass(frozen=True, slots=True)
class MaterializedPoint:
    """One concrete point retaining its canonical logical identity."""

    logical_id: LogicalPointId
    row: Row

    @property
    def logical_ordinal(self) -> int:
        return self.logical_id.logical_ordinal


@dataclass(frozen=True, slots=True)
class MaterializedPointDomain:
    """One materialized coverage of an exact symbolic domain."""

    id: PointDomainId
    points: tuple[MaterializedPoint, ...]
    layout: PointDomainLayout = "product_grid"
    axis_sizes: tuple[tuple[str, int], ...] = ()
    axis_values: tuple[tuple[str, tuple[CellValue, ...]], ...] = ()


def verify_point_domain(
    domain: PointDomain,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    """Check exact shape and require every dynamic center to be closed."""

    domain_id = PointDomainId(program_id=program_id, domain_id=domain.id)
    try:
        shape = analyze_point_domain(domain.axes, layout=domain.layout)
    except PointDomainShapeError as error:
        raise PointDomainVerificationError(
            (
                PointDomainVerificationIssue(
                    error.code,
                    error.path,
                    error.message,
                ),
            )
        ) from error
    issues: list[PointDomainVerificationIssue] = []
    for axis_index, axis in enumerate(domain.axes):
        if isinstance(axis.source, PointAxisLinear):
            _verify_center_role(
                axis.source.center,
                path=("axes", axis_index, "source", "center"),
                issues=issues,
            )
    if issues:
        raise PointDomainVerificationError(issues)
    return VerifiedPointDomain(domain_id, domain.axes, shape, domain.layout)


def materialize_point_domain(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    *,
    row_normalizer: PointRowNormalizer | None = None,
) -> MaterializedPointDomain:
    """Materialize the exact domain and assign canonical ordinal identities."""

    factor_values = tuple(
        _axis_values(
            axis,
            params=params,
            path=("axes", index),
        )
        for index, axis in enumerate(verified.axes)
    )
    rows = _materialize_axes(
        verified.axes,
        factor_values=factor_values,
        layout=verified.layout,
    )
    normalized_rows: Sequence[Mapping[str, object]] = rows
    if row_normalizer is not None:
        normalized_rows = tuple(row_normalizer(dict(row)) for row in rows)
    typed_rows = _coerce_rows(
        verified.value_type,
        normalized_rows,
        path=("points",),
    )
    points = tuple(
        MaterializedPoint(
            LogicalPointId(verified.id, ordinal),
            row,
        )
        for ordinal, row in enumerate(typed_rows)
    )
    axis_values = (
        _materialized_product_axis_values(
            verified.axes,
            verified.axis_sizes,
            factor_values,
            typed_rows,
        )
        if verified.layout == "product_grid"
        else ()
    )
    return MaterializedPointDomain(
        verified.id,
        points,
        layout=verified.layout,
        axis_sizes=verified.axis_sizes,
        axis_values=axis_values,
    )


def _materialize_axes(
    axes: CompilerPointAxes,
    *,
    factor_values: Sequence[Sequence[CellValue]],
    layout: PointDomainLayout,
) -> list[Row]:
    factor_rows = tuple(
        [{axis.id: value} for value in values]
        for axis, values in zip(axes, factor_values, strict=True)
    )
    if layout == "point_cloud":
        return [_merge_rows(group) for group in zip(*factor_rows, strict=True)]
    return [_merge_rows(group) for group in product(*factor_rows)]


def _coerce_axis_value(
    axis: PointAxis[ScalarExpr],
    value: CellValue,
    *,
    index: int,
) -> CellValue:
    return cast(
        "CellValue",
        coerce_literal(
            axis.value_type,
            value,
            path=("axes", axis.id, "values", index),
        ),
    )


def _materialized_product_axis_values(
    axes: CompilerPointAxes,
    axis_sizes: tuple[tuple[str, int], ...],
    factor_values: Sequence[Sequence[CellValue]],
    typed_rows: Sequence[Row],
) -> tuple[tuple[str, tuple[CellValue, ...]], ...]:
    if typed_rows:
        selected: list[tuple[str, tuple[CellValue, ...]]] = []
        sizes = tuple(size for _axis_id, size in axis_sizes)
        for axis_index, (axis_id, size) in enumerate(axis_sizes):
            stride = 1
            for following_size in sizes[axis_index + 1 :]:
                stride *= following_size
            selected.append(
                (
                    axis_id,
                    tuple(
                        typed_rows[value_index * stride][axis_id]
                        for value_index in range(size)
                    ),
                )
            )
        return tuple(selected)
    return tuple(
        (
            axis.id,
            tuple(
                _coerce_axis_value(axis, value, index=value_index)
                for value_index, value in enumerate(values)
            ),
        )
        for axis, values in zip(axes, factor_values, strict=True)
    )


def _axis_values(
    axis: PointAxis[ScalarExpr],
    *,
    params: ParameterRelationData,
    path: PointDomainPath,
) -> tuple[CellValue, ...]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return source.values
    try:
        center = evaluate_scalar(
            source.center,
            EvalContext(params=params),
            expected_type=axis.value_type,
        )
        if not isinstance(center, QuantityValue):
            msg = "linear point axis center must materialize as a quantity"
            raise TypeError(msg)
        return tuple(
            point_axis_linear_value(center, source.span, source.count, index)
            for index in range(source.count)
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise PointDomainEvaluationError(
            (*path, "source", "center"),
            error,
        ) from error


def _verify_center_role(
    value: ScalarExpr,
    *,
    path: PointDomainPath,
    issues: list[PointDomainVerificationIssue],
) -> None:
    open_interface = scalar_expression_point_requirement(value) is not None
    if open_interface:
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_open_point",
                path,
                "point-axis center depends on the current experiment point",
            )
        )
    if any(
        imported.namespace is ExpressionImportNamespace.INPUT
        for imported in scalar_expression_imports(value)
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_open_input",
                path,
                "point-axis center depends on an unresolved input",
            )
        )


def _merge_rows(rows: Sequence[Mapping[str, CellValue]]) -> Row:
    return {key: value for row in rows for key, value in row.items()}


def _coerce_rows(
    value_type: Table,
    rows: Sequence[Mapping[str, object]],
    *,
    path: tuple[str | int, ...],
) -> tuple[Row, ...]:
    coerced = coerce_literal(value_type, rows, path=path)
    return cast("tuple[Row, ...]", coerced)


__all__ = [
    "CompilerPointAxes",
    "MaterializedPoint",
    "MaterializedPointDomain",
    "PointDomain",
    "PointDomainEvaluationError",
    "PointDomainVerificationError",
    "PointDomainVerificationIssue",
    "PointRowNormalizer",
    "VerifiedPointDomain",
    "materialize_point_domain",
    "verify_point_domain",
]
