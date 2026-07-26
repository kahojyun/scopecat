"""Proof-carrying compiler envelopes for relation-plan values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, cast, overload

from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.graph.relations.model import RelationExpr, ScalarExpr
from scopecat.kernel.value_types import Scalar, Table, ValueType


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ScalarValueExpr:
    """A scalar plan together with its backend-neutral static proof."""

    _plan: VerifiedRelationPlan[ScalarExpr]

    shape: ClassVar[Literal["scalar"]] = "scalar"

    def __post_init__(self) -> None:
        if not isinstance(self._plan.certified_type, Scalar):
            msg = "scalar value expressions require a scalar plan proof"
            raise TypeError(msg)

    @property
    def plan(self) -> VerifiedRelationPlan[ScalarExpr]:
        return self._plan

    @property
    def value_type(self) -> Scalar:
        return cast("Scalar", self._plan.certified_type)


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class TableValueExpr:
    """A relation plan together with its backend-neutral static proof."""

    _plan: VerifiedRelationPlan[RelationExpr]

    shape: ClassVar[Literal["table"]] = "table"

    def __post_init__(self) -> None:
        if not isinstance(self._plan.certified_type, Table):
            msg = "table value expressions require a relation plan proof"
            raise TypeError(msg)

    @property
    def plan(self) -> VerifiedRelationPlan[RelationExpr]:
        return self._plan

    @property
    def value_type(self) -> Table:
        return cast("Table", self._plan.certified_type)


type ValueExpr = ScalarValueExpr | TableValueExpr


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


def verify_table_value_expr(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Table | None = None,
) -> TableValueExpr:
    """Verify one transformed relation before it enters compiler IR."""

    return TableValueExpr(
        _plan=verify_relation_plan(
            expression,
            bindings=bindings,
            expected_type=expected_type,
        )
    )


@overload
def verify_value_expr(
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Scalar,
) -> ScalarValueExpr: ...


@overload
def verify_value_expr(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Table,
) -> TableValueExpr: ...


@overload
def verify_value_expr(
    expression: ScalarExpr | RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: ValueType,
) -> ValueExpr: ...


def verify_value_expr(
    expression: ScalarExpr | RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: ValueType,
) -> ValueExpr:
    """Verify and shape-pack one transformed plan for compiler ownership."""

    if isinstance(expression, ScalarExpr) and isinstance(expected_type, Scalar):
        return verify_scalar_value_expr(
            expression,
            bindings=bindings,
            expected_type=expected_type,
        )
    if isinstance(expression, RelationExpr) and isinstance(expected_type, Table):
        return verify_table_value_expr(
            expression,
            bindings=bindings,
            expected_type=expected_type,
        )
    msg = (
        f"expression shape {type(expression).__name__} does not match "
        f"declared type {expected_type!r}"
    )
    raise TypeError(msg)
