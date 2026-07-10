"""Authoring expression, variable, and binding helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.models.parameter import Quantity
from scopecat.models.value import ComputeResultRef
from scopecat.relations import ScalarExpr
from scopecat.units import compatible_units, is_supported_unit

ExpressionKind = Literal[
    "quantity",
    "number",
    "variable",
    "parameter",
    "binary",
]
BinaryOperator = Literal["+", "-", "*", "/"]
VariableKind = Literal["points", "range", "linspace", "derived"]


class Expression(BaseModel):
    """Small serializable expression IR for experiment definitions."""

    model_config = ConfigDict(extra="forbid")

    kind: ExpressionKind
    quantity: Quantity | None = None
    value: float | None = None
    name: str | None = None
    op: BinaryOperator | None = None
    left: Expression | None = None
    right: Expression | None = None

    @classmethod
    def from_value(cls, value: Expression | Quantity | float) -> Expression:
        if isinstance(value, Expression):
            return value
        if isinstance(value, Quantity):
            return cls(kind="quantity", quantity=value)
        return cls(kind="number", value=float(value))

    @model_validator(mode="after")
    def validate_shape(self) -> Expression:
        if self.kind == "quantity":
            if self.quantity is None:
                msg = "quantity expression requires quantity"
                raise ValueError(msg)
            if any(
                item is not None
                for item in (
                    self.value,
                    self.name,
                    self.op,
                    self.left,
                    self.right,
                )
            ):
                msg = "quantity expression cannot contain other expression fields"
                raise ValueError(msg)
            return self
        if self.kind == "number":
            if self.value is None:
                msg = "number expression requires value"
                raise ValueError(msg)
            if any(
                item is not None
                for item in (
                    self.quantity,
                    self.name,
                    self.op,
                    self.left,
                    self.right,
                )
            ):
                msg = "number expression cannot contain other expression fields"
                raise ValueError(msg)
            return self
        if self.kind in {"variable", "parameter"}:
            if not self.name:
                msg = f"{self.kind} expression requires name"
                raise ValueError(msg)
            if any(
                item is not None
                for item in (
                    self.quantity,
                    self.value,
                    self.op,
                    self.left,
                    self.right,
                )
            ):
                msg = f"{self.kind} expression cannot contain other expression fields"
                raise ValueError(msg)
            return self
        if self.kind == "binary":
            if self.op is None or self.left is None or self.right is None:
                msg = "binary expression requires op, left, and right"
                raise ValueError(msg)
            if any(item is not None for item in (self.quantity, self.value, self.name)):
                msg = "binary expression cannot contain scalar expression fields"
                raise ValueError(msg)
            return self
        msg = f"unsupported expression kind: {self.kind}"
        raise ValueError(msg)

    def __add__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("+", self, other)

    def __radd__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("+", other, self)

    def __sub__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("-", self, other)

    def __rsub__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("-", other, self)

    def __mul__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("*", self, other)

    def __rmul__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("*", other, self)

    def __truediv__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("/", self, other)

    def __rtruediv__(self, other: Expression | Quantity | float) -> Expression:
        return _binary("/", other, self)


class ExperimentVariable(BaseModel):
    """Named experiment variable, scan source, or derived value."""

    model_config = ConfigDict(extra="forbid")

    kind: VariableKind
    points: list[Quantity] | None = None
    start: Quantity | None = None
    stop: Quantity | None = None
    step: Quantity | None = None
    count: int | None = Field(default=None, ge=2)
    expression: Expression | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self) -> ExperimentVariable:
        if self.kind == "points":
            if not self.points:
                msg = "points variable requires non-empty points"
                raise ValueError(msg)
            first_unit = self.points[0].unit
            for point in self.points:
                if not compatible_units(first_unit, point.unit):
                    msg = "points variable values must use compatible units"
                    raise ValueError(msg)
            if any(
                value is not None
                for value in (
                    self.start,
                    self.stop,
                    self.step,
                    self.count,
                    self.expression,
                )
            ):
                msg = "points variable cannot contain range or expression fields"
                raise ValueError(msg)
            return self
        if self.kind == "range":
            if self.start is None or self.stop is None or self.step is None:
                msg = "range variable requires start, stop, and step"
                raise ValueError(msg)
            if not compatible_units(
                self.start.unit, self.stop.unit
            ) or not compatible_units(self.start.unit, self.step.unit):
                msg = "range variable start, stop, and step must use compatible units"
                raise ValueError(msg)
            if self.step.value == 0:
                msg = "range variable step must not be zero"
                raise ValueError(msg)
            if self.start.value < self.stop.value and self.step.value < 0:
                msg = "range variable step must be positive for ascending ranges"
                raise ValueError(msg)
            if self.start.value > self.stop.value and self.step.value > 0:
                msg = "range variable step must be negative for descending ranges"
                raise ValueError(msg)
            if (
                self.points is not None
                or self.count is not None
                or self.expression is not None
            ):
                msg = "range variable cannot contain points, count, or expression"
                raise ValueError(msg)
            return self
        if self.kind == "linspace":
            if self.start is None or self.stop is None or self.count is None:
                msg = "linspace variable requires start, stop, and count"
                raise ValueError(msg)
            if not compatible_units(self.start.unit, self.stop.unit):
                msg = "linspace variable start and stop must use compatible units"
                raise ValueError(msg)
            if (
                self.points is not None
                or self.step is not None
                or self.expression is not None
            ):
                msg = "linspace variable cannot contain points, step, or expression"
                raise ValueError(msg)
            return self
        if self.kind == "derived":
            if self.expression is None:
                msg = "derived variable requires expression"
                raise ValueError(msg)
            if any(
                value is not None
                for value in (self.points, self.start, self.stop, self.step, self.count)
            ):
                msg = "derived variable cannot contain scan source fields"
                raise ValueError(msg)
            return self
        msg = f"unsupported variable kind: {self.kind}"
        raise ValueError(msg)


class BindingSpec(BaseModel):
    """Mapping from an expression to one desired-state field."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    capability_id: str
    field_path: str
    value: Expression | ScalarExpr | ComputeResultRef
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("resource_id", "capability_id", "field_path")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value:
            msg = "binding identifiers must be non-empty"
            raise ValueError(msg)
        return value


def qty(value: float, unit: str) -> Expression:
    """Create a quantity literal expression."""

    return Expression(kind="quantity", quantity=Quantity(value=float(value), unit=unit))


def var(name: str) -> Expression:
    """Reference an experiment variable."""

    return Expression(kind="variable", name=name)


def param(name: str) -> Expression:
    """Reference a parameter value from the active config snapshot."""

    return Expression(kind="parameter", name=name)


def linspace(
    start: float,
    stop: float,
    count: int,
    *,
    unit: str,
) -> ExperimentVariable:
    """Create an evenly-spaced scan variable."""

    return ExperimentVariable(
        kind="linspace",
        start=Quantity(value=float(start), unit=unit),
        stop=Quantity(value=float(stop), unit=unit),
        count=count,
    )


def points(
    values: list[float | Quantity],
    *,
    unit: str | None = None,
) -> ExperimentVariable:
    """Create an explicit-point scan variable."""

    quantities = [_coerce_quantity(value, unit=unit) for value in values]
    return ExperimentVariable(kind="points", points=quantities)


def bind(
    resource_id: str,
    capability_id: str,
    field_path: str,
    value: Expression | ScalarExpr | ComputeResultRef | Quantity | float,
) -> BindingSpec:
    """Bind an expression to a desired-state field."""

    return BindingSpec(
        resource_id=resource_id,
        capability_id=capability_id,
        field_path=field_path,
        value=(
            value
            if isinstance(value, ScalarExpr | ComputeResultRef)
            else Expression.from_value(value)
        ),
    )


def _binary(
    op: BinaryOperator,
    left: Expression | Quantity | float,
    right: Expression | Quantity | float,
) -> Expression:
    return Expression(
        kind="binary",
        op=op,
        left=Expression.from_value(left),
        right=Expression.from_value(right),
    )


def _coerce_quantity(value: float | Quantity, *, unit: str | None) -> Quantity:
    if isinstance(value, Quantity):
        if unit is not None and not compatible_units(value.unit, unit):
            msg = f"point unit {value.unit} is not compatible with {unit}"
            raise ValueError(msg)
        return value
    if unit is None:
        msg = "numeric points require unit"
        raise ValueError(msg)
    if not is_supported_unit(unit):
        msg = f"unsupported unit: {unit}"
        raise ValueError(msg)
    return Quantity(value=float(value), unit=unit)


Expression.model_rebuild()
