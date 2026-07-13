"""Proof-carrying compiler envelopes for relation-plan values."""

from __future__ import annotations

from typing import Annotated, Literal, cast, overload

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.compiler.relations.model import RelationExpr, ScalarExpr, SeriesExpr
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    VerifiedRelationPlan,
    verify_relation_plan,
)
from scopecat.kernel.value_types import Scalar, Series, Table, ValueType


class ScalarValueExpr(BaseModel):
    """A scalar plan together with its backend-neutral static proof."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    shape: Literal["scalar"] = "scalar"
    plan: VerifiedRelationPlan[ScalarExpr]

    @model_validator(mode="after")
    def validate_proof_shape(self) -> ScalarValueExpr:
        if not isinstance(cast("object", self.plan.root), ScalarExpr) or not isinstance(
            self.plan.certified_type, Scalar
        ):
            msg = "scalar value expressions require a scalar plan proof"
            raise TypeError(msg)
        return self

    @property
    def value_type(self) -> Scalar:
        return cast("Scalar", self.plan.certified_type)


class SeriesValueExpr(BaseModel):
    """A series plan together with its backend-neutral static proof."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    shape: Literal["series"] = "series"
    plan: VerifiedRelationPlan[SeriesExpr]

    @model_validator(mode="after")
    def validate_proof_shape(self) -> SeriesValueExpr:
        if not isinstance(cast("object", self.plan.root), SeriesExpr) or not isinstance(
            self.plan.certified_type, Series
        ):
            msg = "series value expressions require a series plan proof"
            raise TypeError(msg)
        return self

    @property
    def value_type(self) -> Series:
        return cast("Series", self.plan.certified_type)


class TableValueExpr(BaseModel):
    """A relation plan together with its backend-neutral static proof."""

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        frozen=True,
    )

    shape: Literal["table"] = "table"
    plan: VerifiedRelationPlan[RelationExpr]

    @model_validator(mode="after")
    def validate_proof_shape(self) -> TableValueExpr:
        root_is_relation = isinstance(cast("object", self.plan.root), RelationExpr)
        if not root_is_relation or not isinstance(self.plan.certified_type, Table):
            msg = "table value expressions require a relation plan proof"
            raise TypeError(msg)
        return self

    @property
    def value_type(self) -> Table:
        return cast("Table", self.plan.certified_type)


type ScalarOrSeriesValueExpr = Annotated[
    ScalarValueExpr | SeriesValueExpr,
    Field(discriminator="shape"),
]
type ValueExpr = Annotated[
    ScalarValueExpr | SeriesValueExpr | TableValueExpr,
    Field(discriminator="shape"),
]


def verify_scalar_value_expr(
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Scalar | None = None,
) -> ScalarValueExpr:
    """Verify one transformed scalar expression before it enters compiler IR."""

    return ScalarValueExpr(
        plan=verify_relation_plan(
            expression,
            bindings=bindings,
            expected_type=expected_type,
        )
    )


def verify_series_value_expr(
    expression: SeriesExpr,
    *,
    bindings: RelationTypeBindings,
    expected_type: Series | None = None,
) -> SeriesValueExpr:
    """Verify one transformed series expression before it enters compiler IR."""

    return SeriesValueExpr(
        plan=verify_relation_plan(
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
        plan=verify_relation_plan(
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
