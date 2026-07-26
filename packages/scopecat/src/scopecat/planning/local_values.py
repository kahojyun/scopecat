"""Evaluate typed planning values against one materialized point."""

from __future__ import annotations

from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_relation,
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    ValueExpr,
)
from scopecat.graph.relations.analysis import PlanNode
from scopecat.graph.relations.model import RelationExpr, ScalarExpr, SeriesExpr


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
        return evaluate_relation(
            cast("VerifiedRelationPlan[RelationExpr]", relation_plan),
            ctx,
        )
    msg = f"unsupported typed value expression: {value!r}"
    raise TypeError(msg)
