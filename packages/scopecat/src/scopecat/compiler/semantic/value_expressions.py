"""Compiler carriers for scalar expressions and direct whole-table values."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.graph.relations.model import ScalarExpr
from scopecat.graph.table_values import TableSource
from scopecat.kernel.value_types import Scalar, Table


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ScalarValueExpr:
    """A scalar plan together with its backend-neutral static proof."""

    _plan: VerifiedRelationPlan

    @property
    def plan(self) -> VerifiedRelationPlan:
        return self._plan

    @property
    def value_type(self) -> Scalar:
        return self._plan.certified_type


@dataclass(frozen=True, slots=True)
class TableValue:
    """A typed whole table passed directly to a domain compiler."""

    source: TableSource
    value_type: Table


type CompilerValue = ScalarValueExpr | TableValue


def verify_scalar_value_expr(
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Scalar | None = None,
) -> ScalarValueExpr:
    """Verify one transformed scalar expression before it enters compiler IR."""

    return ScalarValueExpr(
        _plan=verify_relation_plan(
            expression,
            bindings=bindings,
            expected_type=expected_type,
        )
    )
