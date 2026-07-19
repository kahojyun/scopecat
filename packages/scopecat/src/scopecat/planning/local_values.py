"""Evaluate typed planning values against one materialized point."""

from __future__ import annotations

from typing import cast

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.model import RelationExpr, ScalarExpr, SeriesExpr
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
)


def evaluate_value_expr(
    value: ValueExpr | object,
    relation_plan: VerifiedRelationPlan[PlanNode],
    ctx: EvalContext,
) -> object:
    if isinstance(value, ScalarValueExpr):
        return evaluate_scalar(
            cast("VerifiedRelationPlan[ScalarExpr]", relation_plan),
            ctx,
        )
    if isinstance(value, SeriesValueExpr):
        return evaluate_series(
            cast("VerifiedRelationPlan[SeriesExpr]", relation_plan),
            ctx,
        )
    if isinstance(value, TableValueExpr):
        return evaluate_relation_in_context(
            cast("VerifiedRelationPlan[RelationExpr]", relation_plan),
            ctx,
        )
    msg = f"unsupported typed value expression: {value!r}"
    raise TypeError(msg)
