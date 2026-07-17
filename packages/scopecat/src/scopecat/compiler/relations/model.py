"""Backend-neutral relation, series, and scalar plan nodes.

Nodes contain declared semantics and construction helpers only. Traversal and
reference analysis live in :mod:`scopecat.compiler.relations.analysis`;
materialization belongs to an explicitly selected
:mod:`scopecat.compiler.relations.evaluation`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.operators import ScalarOperator
from scopecat.compiler.relations.scalar_eval import is_cell_value
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.symbols import SymbolId
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type ScalarValue = str | int | float | bool | None | Quantity | EntityRef | PayloadValue
type CellValue = ScalarValue | dict[str, object]
type Row = dict[str, CellValue]


@dataclass(frozen=True, slots=True)
class RowScopeId:
    """Nominal lexical identity for one relation-row callback binder."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> RowScopeId:
        return RowScopeId(self.symbol.prefixed(*scope))


class ScalarExpr:
    """Common base for scalar plan variants."""

    def _binary(self, op: ScalarOperator, other: object) -> BinaryScalarExpr:
        return BinaryScalarExpr(
            op=op,
            left=cast("ScalarExpression", self),
            right=as_scalar_expr(other),
        )

    def __add__(self, other: object) -> BinaryScalarExpr:
        return self._binary("+", other)

    def __radd__(self, other: object) -> BinaryScalarExpr:
        return BinaryScalarExpr(
            op="+",
            left=as_scalar_expr(other),
            right=cast("ScalarExpression", self),
        )

    def __sub__(self, other: object) -> BinaryScalarExpr:
        return self._binary("-", other)

    def __rsub__(self, other: object) -> BinaryScalarExpr:
        return BinaryScalarExpr(
            op="-",
            left=as_scalar_expr(other),
            right=cast("ScalarExpression", self),
        )

    def __mul__(self, other: object) -> BinaryScalarExpr:
        return self._binary("*", other)

    def __rmul__(self, other: object) -> BinaryScalarExpr:
        return BinaryScalarExpr(
            op="*",
            left=as_scalar_expr(other),
            right=cast("ScalarExpression", self),
        )

    def __truediv__(self, other: object) -> BinaryScalarExpr:
        return self._binary("/", other)

    def eq(self, other: object) -> BinaryScalarExpr:
        return self._binary("==", other)

    def ne(self, other: object) -> BinaryScalarExpr:
        return self._binary("!=", other)

    def lt(self, other: object) -> BinaryScalarExpr:
        return self._binary("<", other)

    def le(self, other: object) -> BinaryScalarExpr:
        return self._binary("<=", other)

    def gt(self, other: object) -> BinaryScalarExpr:
        return self._binary(">", other)

    def ge(self, other: object) -> BinaryScalarExpr:
        return self._binary(">=", other)

    def and_(self, other: object) -> BinaryScalarExpr:
        return self._binary("and", other)

    def or_(self, other: object) -> BinaryScalarExpr:
        return self._binary("or", other)


@dataclass(frozen=True, slots=True)
class LiteralScalarExpr(ScalarExpr):
    value: CellValue


@dataclass(frozen=True, slots=True)
class ColumnScalarExpr(ScalarExpr):
    name: str
    row_scope_id: RowScopeId | None = None


@dataclass(frozen=True, slots=True)
class OuterColumnScalarExpr(ScalarExpr):
    name: str


@dataclass(frozen=True, slots=True)
class PointColumnScalarExpr(ScalarExpr):
    name: str


@dataclass(frozen=True, slots=True)
class InputScalarExpr(ScalarExpr):
    name: str


@dataclass(frozen=True, slots=True)
class ParameterScalarExpr(ScalarExpr):
    name: str


@dataclass(frozen=True, slots=True)
class ParameterLookupScalarExpr(ScalarExpr):
    table_id: str
    key: dict[str, ScalarExpression]
    column: str


@dataclass(frozen=True, slots=True)
class BinaryScalarExpr(ScalarExpr):
    op: ScalarOperator
    left: ScalarExpression
    right: ScalarExpression


@dataclass(frozen=True, slots=True)
class CaseBranch:
    condition: ScalarExpression
    value: ScalarExpression


@dataclass(frozen=True, slots=True)
class CaseScalarExpr(ScalarExpr):
    cases: list[CaseBranch]
    fallback: ScalarExpression


type ScalarExpression = (
    LiteralScalarExpr
    | ColumnScalarExpr
    | OuterColumnScalarExpr
    | PointColumnScalarExpr
    | InputScalarExpr
    | ParameterScalarExpr
    | ParameterLookupScalarExpr
    | BinaryScalarExpr
    | CaseScalarExpr
)


class SeriesExpr:
    """Common base for one-dimensional series plan variants."""


@dataclass(frozen=True, slots=True)
class ValuesSeriesExpr(SeriesExpr):
    items: list[CellValue]


@dataclass(frozen=True, slots=True)
class LinspaceSeriesExpr(SeriesExpr):
    start: ScalarExpression
    stop: ScalarExpression
    count: int
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class RangeSeriesExpr(SeriesExpr):
    start: ScalarExpression
    stop: ScalarExpression
    step: ScalarExpression
    unit: str | None = None
    include_stop: bool = False


@dataclass(frozen=True, slots=True)
class InputSeriesExpr(SeriesExpr):
    name: str


@dataclass(frozen=True, slots=True)
class ParameterSeriesExpr(SeriesExpr):
    name: str


@dataclass(frozen=True, slots=True)
class RelationColumnSeriesExpr(SeriesExpr):
    source: RelationExpression
    column: str


@dataclass(frozen=True, slots=True)
class RelationEntitiesSeriesExpr(SeriesExpr):
    source: RelationExpression
    columns: list[str]


type SeriesExpression = (
    ValuesSeriesExpr
    | LinspaceSeriesExpr
    | RangeSeriesExpr
    | InputSeriesExpr
    | ParameterSeriesExpr
    | RelationColumnSeriesExpr
    | RelationEntitiesSeriesExpr
)


class _GridColumn:
    pass


@dataclass(frozen=True, slots=True)
class ScalarGridColumn(_GridColumn):
    """One scalar-valued `grid` output column."""

    scalar: ScalarExpression


@dataclass(frozen=True, slots=True)
class SeriesGridColumn(_GridColumn):
    """One series-valued `grid` output column."""

    series: SeriesExpression


@dataclass(frozen=True, slots=True)
class RelationGridColumn(_GridColumn):
    """One relation-valued `grid` output column."""

    relation: RelationExpression


@dataclass(frozen=True, slots=True)
class ValuesGridColumn(_GridColumn):
    """One literal-values `grid` output column."""

    values: list[CellValue]


type GridColumn = (
    ScalarGridColumn | SeriesGridColumn | RelationGridColumn | ValuesGridColumn
)


class RelationExpr:
    """Common base for relation plan variants."""

    def select(self, *columns: str) -> SelectRelationExpr:
        return SelectRelationExpr(
            source=cast("RelationExpression", self),
            select_columns=list(columns),
        )

    def filter(
        self,
        condition: ScalarExpression,
        *,
        row_scope_id: RowScopeId | None = None,
    ) -> FilterRelationExpr:
        return FilterRelationExpr(
            source=cast("RelationExpression", self),
            condition=condition,
            row_scope_id=row_scope_id,
        )

    def join(self, other: RelationExpr, *, on: Mapping[str, str]) -> JoinRelationExpr:
        return JoinRelationExpr(
            left=cast("RelationExpression", self),
            right=cast("RelationExpression", other),
            on=dict(on),
        )

    def cross(self, other: RelationExpr) -> CrossRelationExpr:
        return CrossRelationExpr(
            left=cast("RelationExpression", self),
            right=cast("RelationExpression", other),
        )

    def lateral_cross(self, other: RelationExpr) -> LateralCrossRelationExpr:
        """Cross with a right plan that may reference the current left row."""

        return LateralCrossRelationExpr(
            left=cast("RelationExpression", self),
            right=cast("RelationExpression", other),
        )

    def point_cross(self, other: RelationExpr) -> PointCrossRelationExpr:
        """Cross partial point rows while extending the right point scope."""

        return PointCrossRelationExpr(
            left=cast("RelationExpression", self),
            right=cast("RelationExpression", other),
        )

    def with_columns(
        self,
        *,
        row_scope_id: RowScopeId | None = None,
        **columns: object,
    ) -> WithColumnsRelationExpr:
        return WithColumnsRelationExpr(
            source=cast("RelationExpression", self),
            new_columns={
                name: as_scalar_expr(value) for name, value in columns.items()
            },
            row_scope_id=row_scope_id,
        )

    def sort(self, *columns: str) -> SortRelationExpr:
        return SortRelationExpr(
            source=cast("RelationExpression", self),
            sort_columns=list(columns),
        )

    def limit(self, count: int) -> LimitRelationExpr:
        return LimitRelationExpr(
            source=cast("RelationExpression", self),
            limit_count=count,
        )

    def column(self, column: str) -> RelationColumnSeriesExpr:
        """Project one relation column as an ordered, duplicate-preserving series."""

        return RelationColumnSeriesExpr(
            source=cast("RelationExpression", self),
            column=column,
        )

    def entities(self, *columns: str) -> RelationEntitiesSeriesExpr:
        """Flatten entity columns row-major and remove duplicates stably."""

        return RelationEntitiesSeriesExpr(
            source=cast("RelationExpression", self),
            columns=list(columns),
        )


@dataclass(frozen=True, slots=True)
class LiteralRowsRelationExpr(RelationExpr):
    rows: list[Row]


@dataclass(frozen=True, slots=True)
class TableRelationExpr(RelationExpr):
    table_id: str


@dataclass(frozen=True, slots=True)
class InputRelationExpr(RelationExpr):
    name: str


@dataclass(frozen=True, slots=True)
class GridRelationExpr(RelationExpr):
    columns: dict[str, GridColumn]


@dataclass(frozen=True, slots=True)
class SelectRelationExpr(RelationExpr):
    source: RelationExpression
    select_columns: list[str]


@dataclass(frozen=True, slots=True)
class FilterRelationExpr(RelationExpr):
    source: RelationExpression
    condition: ScalarExpression
    row_scope_id: RowScopeId | None = None


@dataclass(frozen=True, slots=True)
class JoinRelationExpr(RelationExpr):
    left: RelationExpression
    right: RelationExpression
    on: dict[str, str]


@dataclass(frozen=True, slots=True)
class CrossRelationExpr(RelationExpr):
    left: RelationExpression
    right: RelationExpression


@dataclass(frozen=True, slots=True)
class LateralCrossRelationExpr(RelationExpr):
    left: RelationExpression
    right: RelationExpression


@dataclass(frozen=True, slots=True)
class PointCrossRelationExpr(RelationExpr):
    left: RelationExpression
    right: RelationExpression


@dataclass(frozen=True, slots=True)
class ZipRelationExpr(RelationExpr):
    sources: list[RelationExpression]


@dataclass(frozen=True, slots=True)
class WithColumnsRelationExpr(RelationExpr):
    source: RelationExpression
    new_columns: dict[str, ScalarExpression]
    row_scope_id: RowScopeId | None = None


@dataclass(frozen=True, slots=True)
class SortRelationExpr(RelationExpr):
    source: RelationExpression
    sort_columns: list[str]


@dataclass(frozen=True, slots=True)
class LimitRelationExpr(RelationExpr):
    source: RelationExpression
    limit_count: int


type RelationExpression = (
    LiteralRowsRelationExpr
    | TableRelationExpr
    | InputRelationExpr
    | GridRelationExpr
    | SelectRelationExpr
    | FilterRelationExpr
    | JoinRelationExpr
    | CrossRelationExpr
    | LateralCrossRelationExpr
    | PointCrossRelationExpr
    | ZipRelationExpr
    | WithColumnsRelationExpr
    | SortRelationExpr
    | LimitRelationExpr
)


def zip_relations(*sources: RelationExpr) -> ZipRelationExpr:
    """Combine relation rows positionally without evaluating either source."""

    return ZipRelationExpr(
        sources=[cast("RelationExpression", source) for source in sources]
    )


def lit(value: CellValue) -> LiteralScalarExpr:
    return LiteralScalarExpr(value=value)


def col(name: str, *, row_scope_id: RowScopeId | None = None) -> ColumnScalarExpr:
    return ColumnScalarExpr(name=name, row_scope_id=row_scope_id)


def outer(name: str) -> OuterColumnScalarExpr:
    return OuterColumnScalarExpr(name=name)


def point_col(name: str) -> PointColumnScalarExpr:
    """Reference a field from the experiment point independently of row scope."""

    return PointColumnScalarExpr(name=name)


def input_ref(name: str) -> InputScalarExpr:
    return InputScalarExpr(name=name)


def input_series(name: str) -> InputSeriesExpr:
    """Reference a series-shaped input."""

    return InputSeriesExpr(name=name)


def parameter_series(name: str) -> ParameterSeriesExpr:
    """Reference one series-shaped parameter."""

    return ParameterSeriesExpr(name=name)


def input_table(name: str) -> InputRelationExpr:
    """Reference a table-shaped input."""

    return InputRelationExpr(name=name)


def param(
    parameter_or_table_id: str,
    *,
    key: Mapping[str, object] | None = None,
    column: str | None = None,
) -> ScalarExpression:
    if key is None and column is None:
        return ParameterScalarExpr(name=parameter_or_table_id)
    if key is None or column is None:
        msg = "parameter table lookup requires both key and column"
        raise ValueError(msg)
    return ParameterLookupScalarExpr(
        table_id=parameter_or_table_id,
        key={name: as_scalar_expr(value) for name, value in key.items()},
        column=column,
    )


def when(condition: ScalarExpression, value: object) -> CaseScalarExpr:
    return CaseScalarExpr(
        cases=[CaseBranch(condition=condition, value=as_scalar_expr(value))],
        fallback=lit(None),
    )


def case(
    *branches: tuple[ScalarExpression, object],
    fallback: object,
) -> CaseScalarExpr:
    return CaseScalarExpr(
        cases=[
            CaseBranch(condition=condition, value=as_scalar_expr(value))
            for condition, value in branches
        ],
        fallback=as_scalar_expr(fallback),
    )


def as_scalar_expr(value: object) -> ScalarExpression:
    if isinstance(value, ScalarExpr):
        return cast("ScalarExpression", value)
    if is_cell_value(value):
        return lit(value)
    msg = f"cannot convert {value!r} to scalar expression"
    raise TypeError(msg)


def values(items: Sequence[object], *, unit: str | None = None) -> ValuesSeriesExpr:
    if unit is None:
        return ValuesSeriesExpr(
            items=[cast("CellValue", item) for item in items],
        )
    return ValuesSeriesExpr(
        items=[
            Quantity(value=float(cast("int | float", item)), unit=unit)
            for item in items
        ],
    )


def linspace(
    start: object,
    stop: object,
    count: int,
    *,
    unit: str | None = None,
) -> LinspaceSeriesExpr:
    return LinspaceSeriesExpr(
        start=as_scalar_expr(_unit_literal(start, unit=unit)),
        stop=as_scalar_expr(_unit_literal(stop, unit=unit)),
        count=count,
        unit=unit,
    )


def range_values(
    start: object,
    stop: object,
    step: object,
    *,
    unit: str | None = None,
    include_stop: bool = False,
) -> RangeSeriesExpr:
    return RangeSeriesExpr(
        start=as_scalar_expr(_unit_literal(start, unit=unit)),
        stop=as_scalar_expr(_unit_literal(stop, unit=unit)),
        step=as_scalar_expr(_unit_literal(step, unit=unit)),
        unit=unit,
        include_stop=include_stop,
    )


def literal_rows(rows: Sequence[Mapping[str, CellValue]]) -> LiteralRowsRelationExpr:
    return LiteralRowsRelationExpr(rows=[dict(row) for row in rows])


def table(table_id: str) -> TableRelationExpr:
    return TableRelationExpr(table_id=table_id)


def grid(**columns: object) -> GridRelationExpr:
    return GridRelationExpr(
        columns={name: _grid_column(source) for name, source in columns.items()},
    )


def _grid_column(source: object) -> GridColumn:
    if isinstance(source, _GridColumn):
        return cast("GridColumn", source)
    if isinstance(source, ScalarExpr):
        return ScalarGridColumn(scalar=cast("ScalarExpression", source))
    if isinstance(source, SeriesExpr):
        return SeriesGridColumn(series=cast("SeriesExpression", source))
    if isinstance(source, RelationExpr):
        return RelationGridColumn(relation=cast("RelationExpression", source))
    if isinstance(source, Sequence) and not isinstance(source, str | bytes):
        source_items = source
        column_values: list[CellValue] = []
        for item in source_items:
            if not is_cell_value(item):
                msg = f"grid column contains unsupported values: {source!r}"
                raise TypeError(msg)
            column_values.append(item)
        return ValuesGridColumn(values=column_values)
    if is_cell_value(source):
        return ValuesGridColumn(values=[source])
    msg = f"unsupported grid column source: {source!r}"
    raise TypeError(msg)


def _unit_literal(value: object, *, unit: str | None) -> object:
    if unit is None or isinstance(value, ScalarExpr | Quantity):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return Quantity(value=float(value), unit=unit)
    return value
