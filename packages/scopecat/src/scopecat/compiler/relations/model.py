"""Backend-neutral relation, series, and scalar plan nodes.

Nodes contain declared semantics and construction helpers only. Traversal and
reference analysis live in :mod:`scopecat.compiler.relations.analysis`;
materialization belongs to an explicitly selected
:mod:`scopecat.compiler.relations.evaluation`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.compiler.relations.operators import ScalarOperator
from scopecat.compiler.relations.scalar_eval import is_cell_value
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.symbols import SymbolId
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type ScalarValue = str | int | float | bool | None | Quantity | EntityRef | PayloadValue
type CellValue = ScalarValue | dict[str, object]
type Row = dict[str, CellValue]
type ScalarExprKind = Literal[
    "literal",
    "column",
    "outer_column",
    "point_column",
    "input",
    "param_scalar",
    "param_lookup",
    "binary",
    "case",
]
type SeriesExprKind = Literal[
    "values",
    "linspace",
    "range",
    "input",
    "param_series",
    "relation_column",
    "relation_entities",
]
type RelationExprKind = Literal[
    "literal_rows",
    "table",
    "input",
    "grid",
    "select",
    "filter",
    "join",
    "cross",
    "lateral_cross",
    "point_cross",
    "zip",
    "with_columns",
    "sort",
    "limit",
]
type GridColumnKind = Literal["scalar", "series", "relation", "values"]


@dataclass(frozen=True, slots=True)
class RowScopeId:
    """Nominal lexical identity for one relation-row callback binder."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    def prefixed(self, *scope: str) -> RowScopeId:
        return RowScopeId(self.symbol.prefixed(*scope))


class CaseBranch(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    condition: ScalarExpr
    value: ScalarExpr


class ScalarExpr(BaseModel):
    """Data-only scalar plan node."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: ScalarExprKind
    value: CellValue | None = None
    name: str | None = None
    row_scope_id: RowScopeId | None = None
    table_id: str | None = None
    key: dict[str, ScalarExpr] | None = None
    column: str | None = None
    op: ScalarOperator | None = None
    left: ScalarExpr | None = None
    right: ScalarExpr | None = None
    cases: list[CaseBranch] | None = None
    fallback: ScalarExpr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ScalarExpr:
        if self.kind == "literal":
            if self.value is None and "value" not in self.model_fields_set:
                msg = "literal expression requires value"
                raise ValueError(msg)
            self._reject(
                "name",
                "row_scope_id",
                "table_id",
                "key",
                "column",
                "op",
                "left",
                "right",
            )
            self._reject("cases", "fallback")
        elif self.kind in {
            "column",
            "outer_column",
            "point_column",
            "input",
            "param_scalar",
        }:
            if not self.name:
                msg = f"{self.kind} expression requires name"
                raise ValueError(msg)
            self._reject("value", "table_id", "key", "column", "op", "left", "right")
            if self.kind != "column":
                self._reject("row_scope_id")
            self._reject("cases", "fallback")
        elif self.kind == "param_lookup":
            if self.table_id is None or self.key is None or self.column is None:
                msg = "parameter table lookup requires table_id, key, and column"
                raise ValueError(msg)
            self._reject(
                "value",
                "name",
                "row_scope_id",
                "op",
                "left",
                "right",
                "cases",
                "fallback",
            )
        elif self.kind == "binary":
            if self.op is None or self.left is None or self.right is None:
                msg = "binary expression requires op, left, and right"
                raise ValueError(msg)
            self._reject("value", "name", "row_scope_id", "table_id", "key", "column")
            self._reject("cases", "fallback")
        elif self.kind == "case":
            if not self.cases or self.fallback is None:
                msg = "case expression requires cases and fallback"
                raise ValueError(msg)
            self._reject(
                "value",
                "name",
                "row_scope_id",
                "table_id",
                "key",
                "column",
                "op",
            )
            self._reject("left", "right")
        return self

    def _binary(self, op: ScalarOperator, other: object) -> ScalarExpr:
        return ScalarExpr(
            kind="binary",
            op=op,
            left=self,
            right=as_scalar_expr(other),
        )

    def __add__(self, other: object) -> ScalarExpr:
        return self._binary("+", other)

    def __radd__(self, other: object) -> ScalarExpr:
        return ScalarExpr(
            kind="binary",
            op="+",
            left=as_scalar_expr(other),
            right=self,
        )

    def __sub__(self, other: object) -> ScalarExpr:
        return self._binary("-", other)

    def __rsub__(self, other: object) -> ScalarExpr:
        return ScalarExpr(
            kind="binary",
            op="-",
            left=as_scalar_expr(other),
            right=self,
        )

    def __mul__(self, other: object) -> ScalarExpr:
        return self._binary("*", other)

    def __rmul__(self, other: object) -> ScalarExpr:
        return ScalarExpr(
            kind="binary",
            op="*",
            left=as_scalar_expr(other),
            right=self,
        )

    def __truediv__(self, other: object) -> ScalarExpr:
        return self._binary("/", other)

    def eq(self, other: object) -> ScalarExpr:
        return self._binary("==", other)

    def ne(self, other: object) -> ScalarExpr:
        return self._binary("!=", other)

    def lt(self, other: object) -> ScalarExpr:
        return self._binary("<", other)

    def le(self, other: object) -> ScalarExpr:
        return self._binary("<=", other)

    def gt(self, other: object) -> ScalarExpr:
        return self._binary(">", other)

    def ge(self, other: object) -> ScalarExpr:
        return self._binary(">=", other)

    def and_(self, other: object) -> ScalarExpr:
        return self._binary("and", other)

    def or_(self, other: object) -> ScalarExpr:
        return self._binary("or", other)

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            msg = f"{self.kind} expression cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


class SeriesExpr(BaseModel):
    """Data-only one-dimensional series plan used by grid columns."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: SeriesExprKind
    items: list[CellValue] | None = None
    start: ScalarExpr | None = None
    stop: ScalarExpr | None = None
    step: ScalarExpr | None = None
    count: int | None = None
    unit: str | None = None
    include_stop: bool = False
    name: str | None = None
    source: RelationExpr | None = None
    column: str | None = None
    columns: list[str] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> SeriesExpr:
        if self.kind == "values":
            if self.items is None:
                msg = "values series requires items"
                raise ValueError(msg)
            self._reject(
                "start",
                "stop",
                "step",
                "count",
                "name",
                "source",
                "column",
                "columns",
            )
        elif self.kind == "linspace":
            if self.start is None or self.stop is None or self.count is None:
                msg = "linspace series requires start, stop, and count"
                raise ValueError(msg)
            if self.count < 1:
                msg = "linspace count must be positive"
                raise ValueError(msg)
            self._reject(
                "items",
                "step",
                "name",
                "source",
                "column",
                "columns",
            )
        elif self.kind == "range":
            if self.start is None or self.stop is None or self.step is None:
                msg = "range series requires start, stop, and step"
                raise ValueError(msg)
            self._reject(
                "items",
                "count",
                "name",
                "source",
                "column",
                "columns",
            )
        elif self.kind in {"input", "param_series"}:
            if not self.name:
                msg = f"{self.kind} series requires name"
                raise ValueError(msg)
            self._reject(
                "items",
                "start",
                "stop",
                "step",
                "count",
                "source",
                "column",
                "columns",
            )
        elif self.kind == "relation_column":
            if self.source is None or not self.column:
                msg = "relation column series requires source and column"
                raise ValueError(msg)
            self._reject(
                "items",
                "start",
                "stop",
                "step",
                "count",
                "name",
                "columns",
            )
        elif self.kind == "relation_entities":
            if self.source is None or not self.columns:
                msg = "relation entities series requires source and columns"
                raise ValueError(msg)
            if any(not column for column in self.columns):
                msg = "relation entities columns must be non-empty"
                raise ValueError(msg)
            self._reject(
                "items",
                "start",
                "stop",
                "step",
                "count",
                "name",
                "column",
            )
        return self

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            msg = f"{self.kind} series cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


class GridColumn(BaseModel):
    """Typed source for one `grid` output column."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: GridColumnKind
    scalar: ScalarExpr | None = None
    series: SeriesExpr | None = None
    relation: RelationExpr | None = None
    values: list[CellValue] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> GridColumn:
        expected = {
            "scalar": self.scalar,
            "series": self.series,
            "relation": self.relation,
            "values": self.values,
        }
        active = [name for name, value in expected.items() if value is not None]
        if active != [self.kind]:
            msg = f"grid column {self.kind!r} must only contain {self.kind}"
            raise ValueError(msg)
        return self


class RelationExpr(BaseModel):
    """Data-only relation plan node."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: RelationExprKind
    rows: list[Row] | None = None
    table_id: str | None = None
    name: str | None = None
    columns: dict[str, GridColumn] | None = None
    row_scope_id: RowScopeId | None = None
    source: RelationExpr | None = None
    left: RelationExpr | None = None
    right: RelationExpr | None = None
    sources: list[RelationExpr] | None = None
    select_columns: list[str] | None = None
    condition: ScalarExpr | None = None
    on: dict[str, str] | None = None
    new_columns: dict[str, ScalarExpr] | None = None
    sort_columns: list[str] | None = None
    limit_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> RelationExpr:
        if self.kind == "literal_rows":
            if self.rows is None:
                msg = "literal_rows relation requires rows"
                raise ValueError(msg)
            self._reject_common("rows")
        elif self.kind == "table":
            if self.table_id is None:
                msg = "table relation requires table_id"
                raise ValueError(msg)
            self._reject_common("table_id")
        elif self.kind == "input":
            if not self.name:
                msg = "input relation requires name"
                raise ValueError(msg)
            self._reject_common("name")
        elif self.kind == "grid":
            if self.columns is None:
                msg = "grid relation requires columns"
                raise ValueError(msg)
            self._reject_common("columns")
        elif self.kind == "select":
            if self.source is None or self.select_columns is None:
                msg = "select relation requires source and select_columns"
                raise ValueError(msg)
            self._reject_common("source", "select_columns")
        elif self.kind == "filter":
            if self.source is None or self.condition is None:
                msg = "filter relation requires source and condition"
                raise ValueError(msg)
            self._reject_common("source", "condition", "row_scope_id")
        elif self.kind == "join":
            if self.left is None or self.right is None or not self.on:
                msg = "join relation requires left, right, and at least one key"
                raise ValueError(msg)
            self._reject_common("left", "right", "on")
        elif self.kind in {"cross", "lateral_cross", "point_cross"}:
            if self.left is None or self.right is None:
                msg = f"{self.kind} relation requires left and right"
                raise ValueError(msg)
            self._reject_common("left", "right")
        elif self.kind == "zip":
            if not self.sources:
                msg = "zip relation requires at least one source"
                raise ValueError(msg)
            self._reject_common("sources")
        elif self.kind == "with_columns":
            if self.source is None or self.new_columns is None:
                msg = "with_columns relation requires source and new_columns"
                raise ValueError(msg)
            self._reject_common("source", "new_columns", "row_scope_id")
        elif self.kind == "sort":
            if self.source is None or not self.sort_columns:
                msg = "sort relation requires source and at least one sort column"
                raise ValueError(msg)
            self._reject_common("source", "sort_columns")
        elif self.kind == "limit":
            if self.source is None or self.limit_count is None:
                msg = "limit relation requires source and limit_count"
                raise ValueError(msg)
            self._reject_common("source", "limit_count")
        return self

    def select(self, *columns: str) -> RelationExpr:
        return RelationExpr(
            kind="select",
            source=self,
            select_columns=list(columns),
        )

    def filter(
        self,
        condition: ScalarExpr,
        *,
        row_scope_id: RowScopeId | None = None,
    ) -> RelationExpr:
        return RelationExpr(
            kind="filter",
            source=self,
            condition=condition,
            row_scope_id=row_scope_id,
        )

    def join(self, other: RelationExpr, *, on: Mapping[str, str]) -> RelationExpr:
        return RelationExpr(kind="join", left=self, right=other, on=dict(on))

    def cross(self, other: RelationExpr) -> RelationExpr:
        return RelationExpr(kind="cross", left=self, right=other)

    def lateral_cross(self, other: RelationExpr) -> RelationExpr:
        """Cross with a right plan that may reference the current left row."""

        return RelationExpr(kind="lateral_cross", left=self, right=other)

    def point_cross(self, other: RelationExpr) -> RelationExpr:
        """Cross partial point rows while extending the right point scope."""

        return RelationExpr(kind="point_cross", left=self, right=other)

    def with_columns(
        self,
        *,
        row_scope_id: RowScopeId | None = None,
        **columns: object,
    ) -> RelationExpr:
        return RelationExpr(
            kind="with_columns",
            source=self,
            new_columns={
                name: as_scalar_expr(value) for name, value in columns.items()
            },
            row_scope_id=row_scope_id,
        )

    def sort(self, *columns: str) -> RelationExpr:
        return RelationExpr(kind="sort", source=self, sort_columns=list(columns))

    def limit(self, count: int) -> RelationExpr:
        return RelationExpr(kind="limit", source=self, limit_count=count)

    def column(self, column: str) -> SeriesExpr:
        """Project one relation column as an ordered, duplicate-preserving series."""

        if not column:
            msg = "relation column must be non-empty"
            raise ValueError(msg)
        return SeriesExpr(kind="relation_column", source=self, column=column)

    def entities(self, *columns: str) -> SeriesExpr:
        """Flatten entity columns row-major and remove duplicates stably."""

        if not columns:
            msg = "relation entities requires at least one column"
            raise ValueError(msg)
        return SeriesExpr(kind="relation_entities", source=self, columns=list(columns))

    def _reject_common(self, *allowed: str) -> None:
        all_fields = {
            "rows",
            "table_id",
            "name",
            "columns",
            "row_scope_id",
            "source",
            "left",
            "right",
            "sources",
            "select_columns",
            "condition",
            "on",
            "new_columns",
            "sort_columns",
            "limit_count",
        }
        unexpected = [
            field_name
            for field_name in sorted(all_fields - set(allowed))
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            msg = f"{self.kind} relation cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


def zip_relations(*sources: RelationExpr) -> RelationExpr:
    """Combine relation rows positionally without evaluating either source."""

    return RelationExpr(kind="zip", sources=list(sources))


def lit(value: CellValue) -> ScalarExpr:
    return ScalarExpr(kind="literal", value=value)


def col(name: str, *, row_scope_id: RowScopeId | None = None) -> ScalarExpr:
    return ScalarExpr(kind="column", name=name, row_scope_id=row_scope_id)


def outer(name: str) -> ScalarExpr:
    return ScalarExpr(kind="outer_column", name=name)


def point_col(name: str) -> ScalarExpr:
    """Reference a field from the experiment point independently of row scope."""

    return ScalarExpr(kind="point_column", name=name)


def input_ref(name: str) -> ScalarExpr:
    return ScalarExpr(kind="input", name=name)


def input_series(name: str) -> SeriesExpr:
    """Reference a series-shaped input."""

    return SeriesExpr(kind="input", name=name)


def parameter_series(name: str) -> SeriesExpr:
    """Reference one series-shaped parameter."""

    return SeriesExpr(kind="param_series", name=name)


def input_table(name: str) -> RelationExpr:
    """Reference a table-shaped input."""

    return RelationExpr(kind="input", name=name)


def param(
    parameter_or_table_id: str,
    *,
    key: Mapping[str, object] | None = None,
    column: str | None = None,
) -> ScalarExpr:
    if key is None and column is None:
        return ScalarExpr(kind="param_scalar", name=parameter_or_table_id)
    if key is None or column is None:
        msg = "parameter table lookup requires both key and column"
        raise ValueError(msg)
    return ScalarExpr(
        kind="param_lookup",
        table_id=parameter_or_table_id,
        key={name: as_scalar_expr(value) for name, value in key.items()},
        column=column,
    )


def when(condition: ScalarExpr, value: object) -> ScalarExpr:
    return ScalarExpr(
        kind="case",
        cases=[CaseBranch(condition=condition, value=as_scalar_expr(value))],
        fallback=lit(None),
    )


def case(
    *branches: tuple[ScalarExpr, object],
    fallback: object,
) -> ScalarExpr:
    return ScalarExpr(
        kind="case",
        cases=[
            CaseBranch(condition=condition, value=as_scalar_expr(value))
            for condition, value in branches
        ],
        fallback=as_scalar_expr(fallback),
    )


def as_scalar_expr(value: object) -> ScalarExpr:
    if isinstance(value, ScalarExpr):
        return value
    converter = getattr(value, "__scopecat_scalar_expr__", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, ScalarExpr):
            return converted
        msg = "scalar expression conversion hook returned a non-scalar value"
        raise TypeError(msg)
    if is_cell_value(value):
        return lit(value)
    msg = f"cannot convert {value!r} to scalar expression"
    raise TypeError(msg)


def values(items: Sequence[object], *, unit: str | None = None) -> SeriesExpr:
    if unit is None:
        return SeriesExpr(
            kind="values",
            items=[cast(CellValue, item) for item in items],
        )
    return SeriesExpr(
        kind="values",
        items=[
            Quantity(value=float(cast(int | float, item)), unit=unit) for item in items
        ],
    )


def linspace(
    start: object,
    stop: object,
    count: int,
    *,
    unit: str | None = None,
) -> SeriesExpr:
    return SeriesExpr(
        kind="linspace",
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
) -> SeriesExpr:
    return SeriesExpr(
        kind="range",
        start=as_scalar_expr(_unit_literal(start, unit=unit)),
        stop=as_scalar_expr(_unit_literal(stop, unit=unit)),
        step=as_scalar_expr(_unit_literal(step, unit=unit)),
        unit=unit,
        include_stop=include_stop,
    )


def literal_rows(rows: Sequence[Mapping[str, CellValue]]) -> RelationExpr:
    return RelationExpr(kind="literal_rows", rows=[dict(row) for row in rows])


def table(table_id: str) -> RelationExpr:
    return RelationExpr(kind="table", table_id=table_id)


def parameter_table(table_id: str) -> RelationExpr:
    return RelationExpr(kind="table", table_id=table_id)


def grid(**columns: object) -> RelationExpr:
    return RelationExpr(
        kind="grid",
        columns={name: _grid_column(source) for name, source in columns.items()},
    )


def _grid_column(source: object) -> GridColumn:
    if isinstance(source, GridColumn):
        return source
    if isinstance(source, ScalarExpr):
        return GridColumn(kind="scalar", scalar=source)
    if isinstance(source, SeriesExpr):
        return GridColumn(kind="series", series=source)
    if isinstance(source, RelationExpr):
        return GridColumn(kind="relation", relation=source)
    if isinstance(source, Sequence) and not isinstance(source, str | bytes):
        source_items = source
        column_values: list[CellValue] = []
        for item in source_items:
            if not is_cell_value(item):
                msg = f"grid column contains unsupported values: {source!r}"
                raise TypeError(msg)
            column_values.append(item)
        return GridColumn(kind="values", values=column_values)
    if is_cell_value(source):
        return GridColumn(kind="values", values=[source])
    msg = f"unsupported grid column source: {source!r}"
    raise TypeError(msg)


def _unit_literal(value: object, *, unit: str | None) -> object:
    if unit is None or isinstance(value, ScalarExpr | Quantity):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return Quantity(value=float(value), unit=unit)
    return value


ScalarExpr.model_rebuild()
SeriesExpr.model_rebuild()
GridColumn.model_rebuild()
RelationExpr.model_rebuild()

__all__ = [
    "CaseBranch",
    "CellValue",
    "GridColumn",
    "RelationExpr",
    "Row",
    "RowScopeId",
    "ScalarExpr",
    "SeriesExpr",
    "as_scalar_expr",
    "case",
    "col",
    "grid",
    "input_ref",
    "input_series",
    "input_table",
    "linspace",
    "lit",
    "literal_rows",
    "outer",
    "param",
    "parameter_series",
    "parameter_table",
    "point_col",
    "range_values",
    "table",
    "values",
    "when",
    "zip_relations",
]
