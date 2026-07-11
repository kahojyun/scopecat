"""Private transient relation and scalar expression graph.

This module is the production foundation for the shared relation
language. It is intentionally small: it gives typed authoring and planner
snapshots a shared expression graph plus a deterministic local evaluator without
depending on pandas, Polars, notebooks, or domain packages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import cmp_to_key
from itertools import product
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._relation_scalar_eval import (
    eval_binary,
    is_cell_value,
    read_path,
)
from scopecat._scalar_operators import (
    ScalarOperator,
    compare_ordered_values,
    runtime_values_equal,
)
from scopecat.models.entity import EntityRef, same_entity_identity
from scopecat.models.parameter import Quantity
from scopecat.models.value import PayloadValue

type ScalarValue = str | int | float | bool | None | Quantity | EntityRef | PayloadValue
type CellValue = ScalarValue | dict[str, Any]
type Row = dict[str, CellValue]
type ScalarExprKind = Literal[
    "literal",
    "column",
    "outer_column",
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
    "zip",
    "with_columns",
    "sort",
    "limit",
]
type GridColumnKind = Literal["scalar", "series", "relation", "values"]


class ParameterRelationData(BaseModel):
    """Resolved scalar, series, and table values for relation evaluation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    scalars: dict[str, CellValue] = Field(default_factory=dict)
    series: dict[str, list[CellValue]] = Field(default_factory=dict)
    tables: dict[str, list[Row]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unified_namespace(self) -> ParameterRelationData:
        collisions = sorted(
            (self.scalars.keys() & self.series.keys())
            | (self.scalars.keys() & self.tables.keys())
            | (self.series.keys() & self.tables.keys())
        )
        if collisions:
            msg = (
                "parameter ids must be unique across scalar, series, and table "
                f"shapes: {', '.join(collisions)}"
            )
            raise ValueError(msg)
        return self

    def scalar(self, parameter_id: str) -> CellValue:
        try:
            return self.scalars[parameter_id]
        except KeyError as exc:
            msg = f"unknown scalar parameter {parameter_id!r}"
            raise KeyError(msg) from exc

    def value(self, parameter_id: str) -> object:
        """Return one value from the unified parameter namespace."""

        if parameter_id in self.scalars:
            return self.scalars[parameter_id]
        if parameter_id in self.series:
            return list(self.series[parameter_id])
        if parameter_id in self.tables:
            return [dict(row) for row in self.tables[parameter_id]]
        msg = f"unknown parameter {parameter_id!r}"
        raise KeyError(msg)

    def table_rows(self, table_id: str) -> list[Row]:
        try:
            return [dict(row) for row in self.tables[table_id]]
        except KeyError as exc:
            msg = f"unknown parameter table {table_id!r}"
            raise KeyError(msg) from exc

    def series_values(self, parameter_id: str) -> list[CellValue]:
        try:
            return list(self.series[parameter_id])
        except KeyError as exc:
            msg = f"unknown series parameter {parameter_id!r}"
            raise KeyError(msg) from exc

    def lookup_row(self, table_id: str, key: Mapping[str, CellValue]) -> Row:
        matches = [
            row
            for row in self.table_rows(table_id)
            if all(
                _cell_matches(row.get(column), value) for column, value in key.items()
            )
        ]
        if len(matches) != 1:
            msg = f"{table_id!r} key {dict(key)!r} matched {len(matches)} rows"
            raise ValueError(msg)
        return matches[0]

    def to_context(
        self,
        *,
        row: Row | None = None,
        outer_row: Row | None = None,
        inputs: Mapping[str, object] | None = None,
    ) -> EvalContext:
        return EvalContext(
            params=self,
            row=row or {},
            outer_row=outer_row,
            inputs=dict(inputs or {}),
        )


class EvalContext(BaseModel):
    """Current row, optional outer row, and resolved parameters."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    params: ParameterRelationData = Field(default_factory=ParameterRelationData)
    row: Row = Field(default_factory=dict)
    outer_row: Row | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class CaseBranch(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    condition: ScalarExpr
    value: ScalarExpr


class ScalarExpr(BaseModel):
    """Transient scalar expression used by relation evaluation."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: ScalarExprKind
    value: CellValue | None = None
    name: str | None = None
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
            self._reject("name", "table_id", "key", "column", "op", "left", "right")
            self._reject("cases", "fallback")
        elif self.kind in {"column", "outer_column", "input", "param_scalar"}:
            if not self.name:
                msg = f"{self.kind} expression requires name"
                raise ValueError(msg)
            self._reject("value", "table_id", "key", "column", "op", "left", "right")
            self._reject("cases", "fallback")
        elif self.kind == "param_lookup":
            if self.table_id is None or self.key is None or self.column is None:
                msg = "parameter table lookup requires table_id, key, and column"
                raise ValueError(msg)
            self._reject("value", "name", "op", "left", "right", "cases", "fallback")
        elif self.kind == "binary":
            if self.op is None or self.left is None or self.right is None:
                msg = "binary expression requires op, left, and right"
                raise ValueError(msg)
            self._reject("value", "name", "table_id", "key", "column")
            self._reject("cases", "fallback")
        elif self.kind == "case":
            if not self.cases or self.fallback is None:
                msg = "case expression requires cases and fallback"
                raise ValueError(msg)
            self._reject("value", "name", "table_id", "key", "column", "op")
            self._reject("left", "right")
        return self

    def eval(self, ctx: EvalContext) -> CellValue:
        if self.kind == "literal":
            return self.value
        if self.kind == "column":
            return read_path(ctx.row, _required(self.name))
        if self.kind == "outer_column":
            if ctx.outer_row is None:
                msg = f"outer column {_required(self.name)!r} used outside scope"
                raise ValueError(msg)
            return read_path(ctx.outer_row, _required(self.name))
        if self.kind == "input":
            return read_path(ctx.inputs, _required(self.name))
        if self.kind == "param_scalar":
            return ctx.params.scalar(_required(self.name))
        if self.kind == "param_lookup":
            resolved_key = {
                name: expr.eval(ctx) for name, expr in _required(self.key).items()
            }
            row = ctx.params.lookup_row(_required(self.table_id), resolved_key)
            return read_path(row, _required(self.column))
        if self.kind == "binary":
            return eval_binary(
                _required(self.op),
                _required(self.left).eval(ctx),
                _required(self.right).eval(ctx),
            )
        if self.kind == "case":
            for branch in _required(self.cases):
                if branch.condition.eval(ctx) is True:
                    return branch.value.eval(ctx)
            return _required(self.fallback).eval(ctx)
        msg = f"unsupported scalar expression kind: {self.kind}"
        raise ValueError(msg)

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
    """One-dimensional deterministic series used by `grid` columns."""

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

    def evaluate(self, ctx: EvalContext) -> list[CellValue]:
        if self.kind == "values":
            return list(_required(self.items))
        if self.kind == "linspace":
            count = _required(self.count)
            start_value = _required(self.start).eval(ctx)
            stop_value = _required(self.stop).eval(ctx)
            unit = self.unit or _quantity_unit(start_value)
            start = _series_float(start_value, unit=unit)
            stop = _series_float(stop_value, unit=unit)
            if count == 1:
                return _series_values([start], unit=unit)
            step_value = (stop - start) / (count - 1)
            return _series_values(
                [start + index * step_value for index in range(count)],
                unit=unit,
            )
        if self.kind == "range":
            start_value = _required(self.start).eval(ctx)
            stop_value = _required(self.stop).eval(ctx)
            step_value = _required(self.step).eval(ctx)
            unit = self.unit or _quantity_unit(start_value)
            start = _series_float(start_value, unit=unit)
            stop = _series_float(stop_value, unit=unit)
            step = _series_float(step_value, unit=unit)
            if step == 0:
                msg = "range step must not be zero"
                raise ValueError(msg)
            values: list[float] = []
            current = start
            if step > 0:
                while current < stop or (
                    self.include_stop and _float_almost_equal(current, stop)
                ):
                    values.append(current)
                    current += step
            else:
                while current > stop or (
                    self.include_stop and _float_almost_equal(current, stop)
                ):
                    values.append(current)
                    current += step
            return _series_values(values, unit=unit)
        if self.kind == "input":
            return _input_series(ctx.inputs, _required(self.name))
        if self.kind == "param_series":
            return ctx.params.series_values(_required(self.name))
        if self.kind == "relation_column":
            return [
                read_path(row, _required(self.column))
                for row in _required(self.source).evaluate_in_context(ctx)
            ]
        if self.kind == "relation_entities":
            entities: list[CellValue] = []
            for row in _required(self.source).evaluate_in_context(ctx):
                for column in _required(self.columns):
                    value = read_path(row, column)
                    if not any(_cell_matches(existing, value) for existing in entities):
                        entities.append(value)
            return entities
        msg = f"unsupported series kind: {self.kind}"
        raise ValueError(msg)

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

    def evaluate(self, ctx: EvalContext) -> list[CellValue]:
        if self.kind == "scalar":
            return [_required(self.scalar).eval(ctx)]
        if self.kind == "series":
            return _required(self.series).evaluate(ctx)
        if self.kind == "relation":
            return cast(
                list[CellValue], _required(self.relation).evaluate_in_context(ctx)
            )
        if self.kind == "values":
            return list(_required(self.values))
        msg = f"unsupported grid column kind: {self.kind}"
        raise ValueError(msg)


class RelationExpr(BaseModel):
    """Transient relation expression with a deterministic local evaluator."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: RelationExprKind
    rows: list[Row] | None = None
    table_id: str | None = None
    name: str | None = None
    columns: dict[str, GridColumn] | None = None
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
            self._reject_common("source", "condition")
        elif self.kind == "join":
            if self.left is None or self.right is None or not self.on:
                msg = "join relation requires left, right, and at least one key"
                raise ValueError(msg)
            self._reject_common("left", "right", "on")
        elif self.kind == "cross":
            if self.left is None or self.right is None:
                msg = "cross relation requires left and right"
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
            self._reject_common("source", "new_columns")
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

    def evaluate(
        self,
        params: ParameterRelationData | None = None,
        *,
        row: Row | None = None,
        outer_row: Row | None = None,
        inputs: Mapping[str, object] | None = None,
    ) -> list[Row]:
        relation_params = _relation_params(params)
        return self.evaluate_in_context(
            EvalContext(
                params=relation_params,
                row=row or {},
                outer_row=outer_row,
                inputs=dict(inputs or {}),
            )
        )

    def evaluate_in_context(self, ctx: EvalContext) -> list[Row]:
        if self.kind == "literal_rows":
            return [dict(row) for row in _required(self.rows)]
        if self.kind == "table":
            return ctx.params.table_rows(_required(self.table_id))
        if self.kind == "input":
            return _input_table(ctx.inputs, _required(self.name))
        if self.kind == "grid":
            names = tuple(_required(self.columns))
            choices = [_required(self.columns)[name].evaluate(ctx) for name in names]
            grid_rows: list[Row] = []
            for combination in product(*choices):
                grid_rows.append(dict(zip(names, combination, strict=True)))
            return grid_rows
        if self.kind == "select":
            return [
                {
                    column: read_path(source_row, column)
                    for column in _required(self.select_columns)
                }
                for source_row in _required(self.source).evaluate_in_context(ctx)
            ]
        if self.kind == "filter":
            filtered_rows: list[Row] = []
            for source_row in _required(self.source).evaluate_in_context(ctx):
                child_ctx = EvalContext(
                    params=ctx.params,
                    row=source_row,
                    outer_row=ctx.outer_row,
                    inputs=ctx.inputs,
                )
                if _required(self.condition).eval(child_ctx) is True:
                    filtered_rows.append(source_row)
            return filtered_rows
        if self.kind == "join":
            left_rows = _required(self.left).evaluate_in_context(ctx)
            right_rows = _required(self.right).evaluate_in_context(ctx)
            on = _required(self.on)
            allowed_shared = {
                left_column
                for left_column, right_column in on.items()
                if left_column == right_column
            }
            _require_disjoint_row_columns(
                left_rows,
                right_rows,
                operation="join",
                allowed_shared=allowed_shared,
            )
            joined: list[Row] = []
            for left_row in left_rows:
                for right_row in right_rows:
                    if _join_keys_match(left_row, right_row, on):
                        joined.append(
                            _merge_rows(
                                left_row,
                                right_row,
                                operation="join",
                                allowed_shared=allowed_shared,
                            )
                        )
            return joined
        if self.kind == "cross":
            crossed: list[Row] = []
            for left_row in _required(self.left).evaluate_in_context(ctx):
                child_ctx = EvalContext(
                    params=ctx.params,
                    row=(
                        _merge_rows(ctx.row, left_row, operation="cross")
                        if ctx.row
                        else left_row
                    ),
                    outer_row=ctx.outer_row,
                    inputs=ctx.inputs,
                )
                right_rows = _required(self.right).evaluate_in_context(child_ctx)
                _require_disjoint_row_columns(
                    [left_row],
                    right_rows,
                    operation="cross",
                )
                for right_row in right_rows:
                    crossed.append(_merge_rows(left_row, right_row, operation="cross"))
            return crossed
        if self.kind == "zip":
            rows_by_source = [
                source.evaluate_in_context(ctx) for source in _required(self.sources)
            ]
            lengths = {len(rows) for rows in rows_by_source}
            if len(lengths) != 1:
                msg = "zip relation requires sources with equal length"
                raise ValueError(msg)
            zipped: list[Row] = []
            for row_group in zip(*rows_by_source, strict=True):
                merged: Row = {}
                for row in row_group:
                    overlap = set(merged).intersection(row)
                    if overlap:
                        msg = "zip relation contains duplicate columns: " + ", ".join(
                            sorted(overlap)
                        )
                        raise ValueError(msg)
                    merged.update(row)
                zipped.append(merged)
            return zipped
        if self.kind == "with_columns":
            derived_rows: list[Row] = []
            for source_row in _required(self.source).evaluate_in_context(ctx):
                next_row = dict(source_row)
                child_ctx = EvalContext(
                    params=ctx.params,
                    row=next_row,
                    outer_row=ctx.outer_row,
                    inputs=ctx.inputs,
                )
                for name, expr in _required(self.new_columns).items():
                    next_row[name] = expr.eval(child_ctx)
                derived_rows.append(next_row)
            return derived_rows
        if self.kind == "sort":
            source_rows = _required(self.source).evaluate_in_context(ctx)
            columns = tuple(_required(self.sort_columns))
            return sorted(
                source_rows,
                key=cmp_to_key(
                    lambda left, right: _compare_rows(left, right, columns=columns)
                ),
            )
        if self.kind == "limit":
            return _required(self.source).evaluate_in_context(ctx)[
                : _required(self.limit_count)
            ]
        msg = f"unsupported relation kind: {self.kind}"
        raise ValueError(msg)

    def select(self, *columns: str) -> RelationExpr:
        return RelationExpr(
            kind="select",
            source=self,
            select_columns=list(columns),
        )

    def filter(self, condition: ScalarExpr) -> RelationExpr:
        return RelationExpr(kind="filter", source=self, condition=condition)

    def join(self, other: RelationExpr, *, on: Mapping[str, str]) -> RelationExpr:
        return RelationExpr(kind="join", left=self, right=other, on=dict(on))

    def cross(self, other: RelationExpr) -> RelationExpr:
        return RelationExpr(kind="cross", left=self, right=other)

    def with_columns(self, **columns: object) -> RelationExpr:
        return RelationExpr(
            kind="with_columns",
            source=self,
            new_columns={
                name: as_scalar_expr(value) for name, value in columns.items()
            },
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


def col(name: str) -> ScalarExpr:
    return ScalarExpr(kind="column", name=name)


def outer(name: str) -> ScalarExpr:
    return ScalarExpr(kind="outer_column", name=name)


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


def _cell_matches(left: CellValue, right: CellValue) -> bool:
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    if isinstance(left, EntityRef) and isinstance(right, str):
        return left.id == right
    if isinstance(left, str) and isinstance(right, EntityRef):
        return left == right.id
    try:
        return runtime_values_equal(left, right)
    except TypeError:
        return False


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
        source_items = cast(Sequence[object], source)
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


def _relation_params(params: ParameterRelationData | None) -> ParameterRelationData:
    if params is None:
        return ParameterRelationData()
    return params


def _unit_literal(value: object, *, unit: str | None) -> object:
    if unit is None or isinstance(value, ScalarExpr | Quantity):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return Quantity(value=float(value), unit=unit)
    return value


def _quantity_unit(value: CellValue) -> str | None:
    if isinstance(value, Quantity):
        return value.unit
    return None


def _series_float(value: CellValue, *, unit: str | None) -> float:
    if isinstance(value, Quantity):
        if unit is None:
            return value.value
        return value.to(unit).value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = f"series bound must be numeric or quantity, got {value!r}"
    raise TypeError(msg)


def _series_values(raw_values: Sequence[float], *, unit: str | None) -> list[CellValue]:
    values_list = [round(value, 12) for value in raw_values]
    if unit is None:
        return [cast(CellValue, value) for value in values_list]
    return [Quantity(value=value, unit=unit) for value in values_list]


def _float_almost_equal(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12


def _join_keys_match(left: Row, right: Row, on: Mapping[str, str]) -> bool:
    for left_column, right_column in on.items():
        left_value = read_path(left, left_column)
        right_value = read_path(right, right_column)
        if left_value is None or right_value is None:
            msg = "join key values must be non-null"
            raise TypeError(msg)
        if not runtime_values_equal(left_value, right_value):
            return False
    return True


def _compare_rows(left: Row, right: Row, *, columns: tuple[str, ...]) -> int:
    for column in columns:
        result = compare_ordered_values(
            read_path(left, column),
            read_path(right, column),
        )
        if result:
            return result
    return 0


def _require_disjoint_row_columns(
    left_rows: Sequence[Row],
    right_rows: Sequence[Row],
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> None:
    left_columns = {column for row in left_rows for column in row}
    right_columns = {column for row in right_rows for column in row}
    conflicts = sorted((left_columns & right_columns) - (allowed_shared or set()))
    if conflicts:
        msg = f"{operation} column collision: {', '.join(conflicts)}"
        raise ValueError(msg)


def _merge_rows(
    left: Row,
    right: Row,
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> Row:
    merged = dict(left)
    for key, value in right.items():
        if key in merged:
            if key not in (allowed_shared or set()):
                msg = f"{operation} column collision for {key!r}"
                raise ValueError(msg)
            if not runtime_values_equal(merged[key], value):
                msg = (
                    f"{operation} shared key {key!r} differs: "
                    f"{merged[key]!r} != {value!r}"
                )
                raise ValueError(msg)
            # The combined typed schema retains the left shared column. Keep
            # its normalized representation as well (for example Int instead
            # of equal Float, or GHz instead of equal MHz).
            continue
        merged[key] = value
    return merged


def _input_series(inputs: Mapping[str, object], name: str) -> list[CellValue]:
    try:
        value = inputs[name]
    except KeyError as exc:
        msg = f"unknown series input {name!r}"
        raise KeyError(msg) from exc
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"series input {name!r} must be a sequence"
        raise TypeError(msg)
    items: list[CellValue] = []
    for item in cast("Sequence[object]", value):
        if not is_cell_value(item):
            msg = f"series input {name!r} contains unsupported value {item!r}"
            raise TypeError(msg)
        items.append(item)
    return items


def _input_table(inputs: Mapping[str, object], name: str) -> list[Row]:
    try:
        value = inputs[name]
    except KeyError as exc:
        msg = f"unknown table input {name!r}"
        raise KeyError(msg) from exc
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {name!r} must be a sequence of rows"
        raise TypeError(msg)
    rows: list[Row] = []
    for row in cast("Sequence[object]", value):
        if not isinstance(row, Mapping):
            msg = f"table input {name!r} contains non-row value {row!r}"
            raise TypeError(msg)
        mapping = cast("Mapping[object, object]", row)
        if not all(isinstance(key, str) for key in mapping):
            msg = f"table input {name!r} row keys must be strings"
            raise TypeError(msg)
        rows.append(
            {
                cast(str, key): _normalize_input_cell(item)
                for key, item in mapping.items()
            }
        )
    return rows


def _normalize_input_cell(value: object) -> CellValue:
    if not isinstance(value, Mapping):
        if is_cell_value(value):
            return value
        msg = f"input table cell contains unsupported value {value!r}"
        raise TypeError(msg)
    mapping = cast("Mapping[object, object]", value)
    if set(mapping) == {"value", "unit"}:
        return Quantity.model_validate(mapping)
    if "id" in mapping and set(mapping) <= {"id", "kind", "metadata"}:
        return EntityRef.model_validate(mapping)
    if not all(isinstance(key, str) for key in mapping):
        msg = "input table mapping cells must use string keys"
        raise TypeError(msg)
    return dict(cast("Mapping[str, Any]", mapping))


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


ScalarExpr.model_rebuild()
SeriesExpr.model_rebuild()
GridColumn.model_rebuild()
RelationExpr.model_rebuild()

__all__ = [
    "CaseBranch",
    "CellValue",
    "EvalContext",
    "GridColumn",
    "ParameterRelationData",
    "RelationExpr",
    "Row",
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
    "range_values",
    "table",
    "values",
    "when",
    "zip_relations",
]
