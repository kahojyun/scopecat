"""Deterministic implementation of relation evaluation semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.scalar_eval import (
    eval_binary,
    read_path,
)
from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    CellValue,
    InputRelationExpr,
    InputScalarExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    RelationExpr,
    RelationExpression,
    Row,
    ScalarExpr,
    ScalarExpression,
    TableRelationExpr,
    is_cell_value,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity


def evaluate_scalar_expression(expression: ScalarExpr, ctx: EvalContext) -> CellValue:
    scalar = cast("ScalarExpression", expression)
    match scalar:
        case LiteralScalarExpr():
            return scalar.value
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
            row = ctx.params.lookup_row(scalar.use.table_id, resolved_key)
            return read_path(row, scalar.use.column_id)
        case BinaryScalarExpr():
            return eval_binary(
                scalar.op,
                evaluate_scalar_expression(scalar.left, ctx),
                evaluate_scalar_expression(scalar.right, ctx),
            )


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
