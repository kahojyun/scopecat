"""Exact symbolic point domains and stable logical point identity."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import cast, overload, override

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
    PointAxisRange,
    PointAxisValues,
    PointDomainPath,
    PointDomainShape,
    PointDomainShapeError,
    analyze_point_domain,
    is_point_coordinate_type,
    point_axis_linear_value,
    point_axis_range_value,
    point_axis_size,
)
from scopecat.program.scans import ScanRangeValue

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
                point_axis_size(axis.source),
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
    """One point domain backed by evaluated compact axis sources."""

    id: PointDomainId
    points: Sequence[MaterializedPoint]
    axes: PointAxes[QuantityValue] = ()
    layout: PointDomainLayout = "product_grid"

    @property
    def axis_sizes(self) -> tuple[tuple[str, int], ...]:
        return tuple((axis.id, point_axis_size(axis.source)) for axis in self.axes)


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

    prepared = prepare_point_domain(
        verified,
        params,
        row_normalizer=row_normalizer,
    )
    return MaterializedPointDomain(
        prepared.id,
        tuple(prepared.points),
        axes=prepared.axes,
        layout=prepared.layout,
    )


def prepare_point_domain(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    *,
    row_normalizer: PointRowNormalizer | None = None,
) -> MaterializedPointDomain:
    """Prepare exact point identity without retaining every concrete row."""

    axes = tuple(
        _prepare_axis(
            axis,
            params=params,
            path=("axes", index),
        )
        for index, axis in enumerate(verified.axes)
    )
    points = _PreparedPointSequence(
        verified,
        axes,
        row_normalizer=row_normalizer,
    )
    return MaterializedPointDomain(
        verified.id,
        points,
        axes=axes,
        layout=verified.layout,
    )


class _PreparedPointSequence(Sequence[MaterializedPoint]):
    """Random-access point rows derived from compact product factors."""

    __slots__ = ("_axes", "_row_normalizer", "_verified")

    def __init__(
        self,
        verified: VerifiedPointDomain,
        axes: PointAxes[QuantityValue],
        *,
        row_normalizer: PointRowNormalizer | None,
    ) -> None:
        self._verified = verified
        self._axes = axes
        self._row_normalizer = row_normalizer

    @override
    def __len__(self) -> int:
        return self._verified.cardinality

    @overload
    def __getitem__(self, index: int) -> MaterializedPoint: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[MaterializedPoint, ...]: ...

    @override
    def __getitem__(
        self,
        index: int | slice,
    ) -> MaterializedPoint | tuple[MaterializedPoint, ...]:
        if isinstance(index, slice):
            return tuple(self[ordinal] for ordinal in range(*index.indices(len(self))))
        ordinal = index + len(self) if index < 0 else index
        if not 0 <= ordinal < len(self):
            raise IndexError(index)
        row = _point_row(
            self._axes,
            layout=self._verified.layout,
            ordinal=ordinal,
        )
        if self._row_normalizer is not None:
            row = dict(self._row_normalizer(dict(row)))
        [typed_row] = _coerce_rows(
            self._verified.value_type,
            (row,),
            path=("points", ordinal),
        )
        return MaterializedPoint(
            LogicalPointId(self._verified.id, ordinal),
            typed_row,
        )

    @override
    def __iter__(self) -> Iterator[MaterializedPoint]:
        return (self[ordinal] for ordinal in range(len(self)))


def _point_row(
    axes: PointAxes[QuantityValue],
    *,
    layout: PointDomainLayout,
    ordinal: int,
) -> Row:
    if layout == "point_cloud":
        return {axis.id: _axis_value(axis, ordinal) for axis in axes}
    selected: dict[str, CellValue] = {}
    remaining = ordinal
    for axis in reversed(axes):
        remaining, value_index = divmod(
            remaining,
            point_axis_size(axis.source),
        )
        selected[axis.id] = _axis_value(axis, value_index)
    return {axis.id: selected[axis.id] for axis in axes}


def _prepare_axis(
    axis: PointAxis[ScalarExpr],
    *,
    params: ParameterRelationData,
    path: PointDomainPath,
) -> PointAxis[QuantityValue]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        selected_source = PointAxisValues(
            tuple(
                _coerce_axis_value(axis, value, index=index)
                for index, value in enumerate(source.values)
            )
        )
    elif isinstance(source, PointAxisRange):
        start = cast(
            "ScanRangeValue",
            coerce_literal(
                axis.value_type,
                source.start,
                path=("axes", axis.id, "source", "start"),
            ),
        )
        stop = cast(
            "ScanRangeValue",
            coerce_literal(
                axis.value_type,
                source.stop,
                path=("axes", axis.id, "source", "stop"),
            ),
        )
        try:
            point_axis_range_value(
                start,
                stop,
                source.count,
                0,
            )
            selected_source = PointAxisRange(start, stop, source.count)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise PointDomainEvaluationError(
                (*path, "source"),
                error,
            ) from error
    else:
        try:
            center = evaluate_scalar(
                source.center,
                EvalContext(params=params),
                expected_type=axis.value_type,
            )
            if not isinstance(center, QuantityValue):
                msg = "linear point axis center must materialize as a quantity"
                raise TypeError(msg)
            span = source.span.to(center.unit)
            endpoint_values = tuple(
                (
                    index,
                    point_axis_linear_value(center, span, source.count, index),
                )
                for index in (0, source.count - 1)
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            raise PointDomainEvaluationError(
                (*path, "source", "center"),
                error,
            ) from error
        for index, value in endpoint_values:
            _coerce_axis_value(axis, value, index=index)
        selected_source = PointAxisLinear(
            center=center,
            span=span,
            count=source.count,
        )
    return PointAxis(axis.id, axis.value_type, selected_source)


def _axis_value(
    axis: PointAxis[QuantityValue],
    index: int,
) -> CellValue:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return source.values[index]
    if isinstance(source, PointAxisRange):
        value = point_axis_range_value(
            source.start,
            source.stop,
            source.count,
            index,
        )
    else:
        value = point_axis_linear_value(
            source.center,
            source.span,
            source.count,
            index,
        )
    return cast("CellValue", value)


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
    "prepare_point_domain",
    "verify_point_domain",
]
