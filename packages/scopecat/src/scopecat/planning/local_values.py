"""Evaluate scalar planning values against one materialized point."""

from __future__ import annotations

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import evaluate_scalar
from scopecat.kernel.value_types import Scalar
from scopecat.program.expressions import ScalarExpr


def evaluate_scalar_value(
    value: ScalarExpr,
    ctx: EvalContext,
    *,
    expected_type: Scalar | None = None,
) -> object:
    return evaluate_scalar(value, ctx, expected_type=expected_type)
