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
from scopecat.kernel.value_types import Scalar
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


@dataclass(frozen=True, slots=True)
class ParameterLookupUse:
    """One selected typed lookup occurrence on a table parameter."""

    table_id: str
    key_input_types: tuple[tuple[str, Scalar], ...]
    literal_key_columns: frozenset[str]
    column_id: str
    result_type: Scalar

    def __post_init__(self) -> None:
        if not self.table_id or not self.column_id:
            msg = "parameter lookup table and result column ids must be non-empty"
            raise ValueError(msg)
        key_input_types = tuple(sorted(self.key_input_types, key=lambda item: item[0]))
        key_ids = tuple(key for key, _value_type in key_input_types)
        if any(not key for key in key_ids) or len(key_ids) != len(set(key_ids)):
            msg = "parameter lookup key column ids must be non-empty and unique"
            raise ValueError(msg)
        literal_key_columns = frozenset(self.literal_key_columns)
        if not literal_key_columns <= set(key_ids):
            msg = "literal parameter lookup keys must belong to the lookup key"
            raise ValueError(msg)
        object.__setattr__(self, "key_input_types", key_input_types)
        object.__setattr__(self, "literal_key_columns", literal_key_columns)


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
    row_scope_id: RowScopeId


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
    use: ParameterLookupUse
    key: dict[str, ScalarExpression]


@dataclass(frozen=True, slots=True)
class BinaryScalarExpr(ScalarExpr):
    op: ScalarOperator
    left: ScalarExpression
    right: ScalarExpression


type ScalarExpression = (
    LiteralScalarExpr
    | ColumnScalarExpr
    | PointColumnScalarExpr
    | InputScalarExpr
    | ParameterScalarExpr
    | ParameterLookupScalarExpr
    | BinaryScalarExpr
)


class SeriesExpr:
    """Common base for one-dimensional series plan variants."""


@dataclass(frozen=True, slots=True)
class ValuesSeriesExpr(SeriesExpr):
    items: list[CellValue]


@dataclass(frozen=True, slots=True)
class InputSeriesExpr(SeriesExpr):
    name: str


@dataclass(frozen=True, slots=True)
class ParameterSeriesExpr(SeriesExpr):
    name: str


@dataclass(frozen=True, slots=True)
class RelationEntitiesSeriesExpr(SeriesExpr):
    source: RelationExpression
    columns: list[str]


type SeriesExpression = (
    ValuesSeriesExpr
    | InputSeriesExpr
    | ParameterSeriesExpr
    | RelationEntitiesSeriesExpr
)


class RelationExpr:
    """Common base for relation plan variants."""

    def select(self, *columns: str) -> SelectRelationExpr:
        return SelectRelationExpr(
            source=cast("RelationExpression", self),
            select_columns=list(columns),
        )

    def with_columns(
        self,
        *,
        row_scope_id: RowScopeId,
        **columns: object,
    ) -> WithColumnsRelationExpr:
        return WithColumnsRelationExpr(
            source=cast("RelationExpression", self),
            new_columns={
                name: as_scalar_expr(value) for name, value in columns.items()
            },
            row_scope_id=row_scope_id,
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
class SelectRelationExpr(RelationExpr):
    source: RelationExpression
    select_columns: list[str]


@dataclass(frozen=True, slots=True)
class WithColumnsRelationExpr(RelationExpr):
    source: RelationExpression
    new_columns: dict[str, ScalarExpression]
    row_scope_id: RowScopeId


type RelationExpression = (
    LiteralRowsRelationExpr
    | TableRelationExpr
    | InputRelationExpr
    | SelectRelationExpr
    | WithColumnsRelationExpr
)


def lit(value: CellValue) -> LiteralScalarExpr:
    return LiteralScalarExpr(value=value)


def col(name: str, *, row_scope_id: RowScopeId) -> ColumnScalarExpr:
    return ColumnScalarExpr(name=name, row_scope_id=row_scope_id)


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


def param(parameter_id: str) -> ParameterScalarExpr:
    return ParameterScalarExpr(name=parameter_id)


def parameter_lookup(
    use: ParameterLookupUse,
    *,
    key: Mapping[str, object],
) -> ParameterLookupScalarExpr:
    key_ids = set(key)
    expected_key_ids = {name for name, _value_type in use.key_input_types}
    if key_ids != expected_key_ids:
        msg = "parameter lookup key expressions must exactly match its typed key inputs"
        raise ValueError(msg)
    return ParameterLookupScalarExpr(
        use=use,
        key={name: as_scalar_expr(value) for name, value in key.items()},
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


def literal_rows(rows: Sequence[Mapping[str, CellValue]]) -> LiteralRowsRelationExpr:
    return LiteralRowsRelationExpr(rows=[dict(row) for row in rows])


def table(table_id: str) -> TableRelationExpr:
    return TableRelationExpr(table_id=table_id)
