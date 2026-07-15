"""Proof-carrying compiler envelopes for relation-plan values."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import ClassVar, Literal, Self, cast, overload, override

from scopecat.compiler.relations.model import RelationExpr, ScalarExpr, SeriesExpr
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.kernel.value_types import Scalar, Series, Table, ValueType


class _FrozenProofEnvelope:
    __slots__ = ()

    @override
    def __setattr__(self, name: str, _value: object) -> None:
        msg = f"cannot assign to field {name!r}"
        raise FrozenInstanceError(msg)

    @override
    def __delattr__(self, name: str) -> None:
        msg = f"cannot delete field {name!r}"
        raise FrozenInstanceError(msg)

    def __copy__(self) -> Self:
        return self

    def __deepcopy__(self, _memo: dict[int, object]) -> Self:
        return self


class ScalarValueExpr(_FrozenProofEnvelope):
    """A scalar plan together with its backend-neutral static proof."""

    __slots__ = ("_plan",)

    shape: ClassVar[Literal["scalar"]] = "scalar"

    def __init__(self) -> None:
        msg = "scalar value expressions are created by verify_scalar_value_expr"
        raise TypeError(msg)

    @property
    def plan(self) -> VerifiedRelationPlan[ScalarExpr]:
        return self._plan

    @property
    def value_type(self) -> Scalar:
        return cast("Scalar", self._plan.certified_type)


class SeriesValueExpr(_FrozenProofEnvelope):
    """A series plan together with its backend-neutral static proof."""

    __slots__ = ("_plan",)

    shape: ClassVar[Literal["series"]] = "series"

    def __init__(self) -> None:
        msg = "series value expressions are created by verify_series_value_expr"
        raise TypeError(msg)

    @property
    def plan(self) -> VerifiedRelationPlan[SeriesExpr]:
        return self._plan

    @property
    def value_type(self) -> Series:
        return cast("Series", self._plan.certified_type)


class TableValueExpr(_FrozenProofEnvelope):
    """A relation plan together with its backend-neutral static proof."""

    __slots__ = ("_plan",)

    shape: ClassVar[Literal["table"]] = "table"

    def __init__(self) -> None:
        msg = "table value expressions are created by verify_table_value_expr"
        raise TypeError(msg)

    @property
    def plan(self) -> VerifiedRelationPlan[RelationExpr]:
        return self._plan

    @property
    def value_type(self) -> Table:
        return cast("Table", self._plan.certified_type)


type ScalarOrSeriesValueExpr = ScalarValueExpr | SeriesValueExpr
type ValueExpr = ScalarValueExpr | SeriesValueExpr | TableValueExpr


def _scalar_value_expr_from_plan(
    plan: VerifiedRelationPlan[ScalarExpr],
) -> ScalarValueExpr:
    if not isinstance(plan.certified_type, Scalar):
        msg = "scalar value expressions require a scalar plan proof"
        raise TypeError(msg)
    value = object.__new__(ScalarValueExpr)
    object.__setattr__(value, "_plan", plan)
    return value


def _series_value_expr_from_plan(
    plan: VerifiedRelationPlan[SeriesExpr],
) -> SeriesValueExpr:
    if not isinstance(plan.certified_type, Series):
        msg = "series value expressions require a series plan proof"
        raise TypeError(msg)
    value = object.__new__(SeriesValueExpr)
    object.__setattr__(value, "_plan", plan)
    return value


def _table_value_expr_from_plan(
    plan: VerifiedRelationPlan[RelationExpr],
) -> TableValueExpr:
    if not isinstance(plan.certified_type, Table):
        msg = "table value expressions require a relation plan proof"
        raise TypeError(msg)
    value = object.__new__(TableValueExpr)
    object.__setattr__(value, "_plan", plan)
    return value


def verify_scalar_value_expr(
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Scalar | None = None,
) -> ScalarValueExpr:
    """Verify one transformed scalar expression before it enters compiler IR."""

    return _scalar_value_expr_from_plan(
        verify_relation_plan(expression, bindings=bindings, expected_type=expected_type)
    )


def verify_series_value_expr(
    expression: SeriesExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Series | None = None,
) -> SeriesValueExpr:
    """Verify one transformed series expression before it enters compiler IR."""

    return _series_value_expr_from_plan(
        verify_relation_plan(expression, bindings=bindings, expected_type=expected_type)
    )


def verify_table_value_expr(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Table | None = None,
) -> TableValueExpr:
    """Verify one transformed relation before it enters compiler IR."""

    return _table_value_expr_from_plan(
        verify_relation_plan(expression, bindings=bindings, expected_type=expected_type)
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
    expression: SeriesExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Series,
) -> SeriesValueExpr: ...


@overload
def verify_value_expr(
    expression: RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Table,
) -> TableValueExpr: ...


@overload
def verify_value_expr(
    expression: ScalarExpr | SeriesExpr | RelationExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: ValueType,
) -> ValueExpr: ...


def verify_value_expr(
    expression: ScalarExpr | SeriesExpr | RelationExpr,
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
    if isinstance(expression, SeriesExpr) and isinstance(expected_type, Series):
        return verify_series_value_expr(
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


__all__ = [
    "ScalarOrSeriesValueExpr",
    "ScalarValueExpr",
    "SeriesValueExpr",
    "TableValueExpr",
    "ValueExpr",
    "verify_scalar_value_expr",
    "verify_series_value_expr",
    "verify_table_value_expr",
    "verify_value_expr",
]
