"""Deterministic implementation of relation evaluation semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CellValue,
    ColumnScalarExpr,
    FilterRelationExpr,
    InputRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    RelationEntitiesSeriesExpr,
    RelationExpr,
    RelationExpression,
    Row,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    SelectRelationExpr,
    SeriesExpr,
    SeriesExpression,
    TableRelationExpr,
    ValuesSeriesExpr,
    WithColumnsRelationExpr,
)
from scopecat.compiler.relations.scalar_eval import (
    cell_matches,
    eval_binary,
    is_cell_value,
    read_path,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity


def evaluate_scalar_expression(expression: ScalarExpr, ctx: EvalContext) -> CellValue:
    scalar = cast("ScalarExpression", expression)
    match scalar:
        case LiteralScalarExpr():
            return scalar.value
        case ColumnScalarExpr():
            row_scope_id = scalar.row_scope_id
            row = (
                ctx.row_scopes.get(row_scope_id)
                if row_scope_id is not None
                else ctx.row
            )
            if row is None:
                scope_name = (
                    row_scope_id.qualified_name
                    if row_scope_id is not None
                    else "<implicit-current-row>"
                )
                msg = f"row column references an inactive scope: {scope_name!r}"
                raise ValueError(msg)
            return read_path(row, scalar.name)
        case PointColumnScalarExpr():
            return read_path(ctx.point_row, scalar.name)
        case InputScalarExpr():
            return read_path(ctx.inputs, scalar.name)
        case ParameterScalarExpr():
            return ctx.params.scalar(scalar.name)
        case ParameterLookupScalarExpr():
            resolved_key = {
                name: evaluate_scalar_expression(value, ctx)
                for name, value in scalar.key.items()
            }
            row = ctx.params.lookup_row(scalar.table_id, resolved_key)
            return read_path(row, scalar.column)
        case BinaryScalarExpr():
            return eval_binary(
                scalar.op,
                evaluate_scalar_expression(scalar.left, ctx),
                evaluate_scalar_expression(scalar.right, ctx),
            )


def evaluate_series_expression(
    expression: SeriesExpr, ctx: EvalContext
) -> list[CellValue]:
    series = cast("SeriesExpression", expression)
    match series:
        case ValuesSeriesExpr():
            return list(series.items)
        case InputSeriesExpr():
            return _input_series(ctx.inputs, series.name)
        case ParameterSeriesExpr():
            return ctx.params.series_values(series.name)
        case RelationEntitiesSeriesExpr():
            entities: list[CellValue] = []
            for row in evaluate_relation_expression(series.source, ctx):
                for column in series.columns:
                    value = read_path(row, column)
                    if not any(cell_matches(existing, value) for existing in entities):
                        entities.append(value)
            return entities


def evaluate_relation_expression(
    expression: RelationExpr, ctx: EvalContext
) -> list[Row]:
    relation = cast("RelationExpression", expression)
    match relation:
        case LiteralRowsRelationExpr():
            return [dict(row) for row in relation.rows]
        case TableRelationExpr():
            return ctx.params.table_rows(relation.table_id)
        case InputRelationExpr():
            return _input_table(ctx.inputs, relation.name)
        case SelectRelationExpr():
            return [
                {
                    column: read_path(source_row, column)
                    for column in relation.select_columns
                }
                for source_row in evaluate_relation_expression(relation.source, ctx)
            ]
        case FilterRelationExpr():
            selected: list[Row] = []
            for source_row in evaluate_relation_expression(relation.source, ctx):
                child_ctx = _child_context(
                    ctx,
                    row=source_row,
                    row_scope_id=relation.row_scope_id,
                )
                if evaluate_scalar_expression(relation.condition, child_ctx) is True:
                    selected.append(source_row)
            return selected
        case WithColumnsRelationExpr():
            derived: list[Row] = []
            for source_row in evaluate_relation_expression(relation.source, ctx):
                next_row = dict(source_row)
                child_ctx = _child_context(
                    ctx,
                    row=next_row,
                    row_scope_id=relation.row_scope_id,
                )
                for name, scalar in relation.new_columns.items():
                    next_row[name] = evaluate_scalar_expression(scalar, child_ctx)
                derived.append(next_row)
            return derived


def _child_context(
    ctx: EvalContext,
    *,
    row: Row,
    point_row: Row | None = None,
    row_scope_id: RowScopeId | None = None,
) -> EvalContext:
    row_scopes = dict(ctx.row_scopes)
    if row_scope_id is not None:
        row_scopes[row_scope_id] = row
    return EvalContext(
        params=ctx.params,
        row=row,
        point_row=ctx.point_row if point_row is None else point_row,
        row_scopes=row_scopes,
        inputs=ctx.inputs,
    )


def _input_series(inputs: Mapping[str, object], name: str) -> list[CellValue]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown series input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"series input {name!r} must be a sequence"
        raise TypeError(msg)
    items: list[CellValue] = []
    for item in value:
        if not is_cell_value(item):
            msg = f"series input {name!r} contains unsupported value {item!r}"
            raise TypeError(msg)
        items.append(item)
    return items


def _input_table(inputs: Mapping[str, object], name: str) -> list[Row]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown table input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {name!r} must be a sequence of rows"
        raise TypeError(msg)
    rows: list[Row] = []
    for row in value:
        if not isinstance(row, Mapping):
            msg = f"table input {name!r} contains non-row value {row!r}"
            raise TypeError(msg)
        mapping = cast("Mapping[object, object]", row)
        if not all(isinstance(key, str) for key in mapping):
            msg = f"table input {name!r} row keys must be strings"
            raise TypeError(msg)
        rows.append(
            {
                cast("str", key): _normalize_input_cell(item)
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
    return dict(cast("Mapping[str, object]", mapping))
