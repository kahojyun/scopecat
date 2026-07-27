"""Evaluate scalar planning values against one materialized point."""

from __future__ import annotations

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr


def evaluate_scalar_value(
    value: ScalarValueExpr,
    ctx: EvalContext,
) -> object:
    return evaluate_scalar(value.plan, ctx)
