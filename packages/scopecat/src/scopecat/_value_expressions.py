"""Transient compiler envelopes for scalar, series, and table expressions."""

from __future__ import annotations

from typing import Annotated, Literal, overload

from pydantic import BaseModel, ConfigDict, Field

from scopecat._relations import RelationExpr, ScalarExpr, SeriesExpr


class ScalarValueExpr(BaseModel):
    """Scalar-shaped expression retained until runtime lowering."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    shape: Literal["scalar"] = "scalar"
    expr: ScalarExpr


class SeriesValueExpr(BaseModel):
    """Series-shaped expression retained until runtime lowering."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    shape: Literal["series"] = "series"
    expr: SeriesExpr


class TableValueExpr(BaseModel):
    """Table-shaped expression retained until runtime lowering."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    shape: Literal["table"] = "table"
    expr: RelationExpr


type ScalarOrSeriesValueExpr = Annotated[
    ScalarValueExpr | SeriesValueExpr,
    Field(discriminator="shape"),
]
type ValueExpr = Annotated[
    ScalarValueExpr | SeriesValueExpr | TableValueExpr,
    Field(discriminator="shape"),
]


@overload
def as_value_expr(value: ScalarValueExpr | ScalarExpr) -> ScalarValueExpr: ...


@overload
def as_value_expr(value: SeriesValueExpr | SeriesExpr) -> SeriesValueExpr: ...


@overload
def as_value_expr(value: TableValueExpr | RelationExpr) -> TableValueExpr: ...


def as_value_expr(
    value: ValueExpr | ScalarExpr | SeriesExpr | RelationExpr,
) -> ValueExpr:
    """Wrap one typed expression in its durable shape envelope."""

    if isinstance(value, ScalarValueExpr | SeriesValueExpr | TableValueExpr):
        return value
    if isinstance(value, ScalarExpr):
        return ScalarValueExpr(expr=value)
    if isinstance(value, SeriesExpr):
        return SeriesValueExpr(expr=value)
    return TableValueExpr(expr=value)


def as_scalar_or_series_value_expr(
    value: ScalarOrSeriesValueExpr | ScalarExpr | SeriesExpr,
) -> ScalarOrSeriesValueExpr:
    """Wrap a scalar- or series-shaped expression, rejecting tables."""

    if isinstance(value, ScalarValueExpr | SeriesValueExpr):
        return value
    if isinstance(value, ScalarExpr):
        return ScalarValueExpr(expr=value)
    return SeriesValueExpr(expr=value)


__all__ = [
    "ScalarOrSeriesValueExpr",
    "ScalarValueExpr",
    "SeriesValueExpr",
    "TableValueExpr",
    "ValueExpr",
    "as_scalar_or_series_value_expr",
    "as_value_expr",
]
