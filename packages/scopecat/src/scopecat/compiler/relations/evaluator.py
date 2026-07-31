"""Deterministic implementation of scalar evaluation semantics."""

from __future__ import annotations

from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.scalar_eval import (
    eval_binary,
    read_path,
)
from scopecat.kernel.value_data import CellValue
from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    LiteralScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
)


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
        case ComputeResultScalarExpr():
            msg = "compute results cannot be evaluated as pure scalar expressions"
            raise TypeError(msg)
        case ModuleExportScalarExpr():
            msg = "unresolved module exports cannot be evaluated"
            raise ValueError(msg)
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
