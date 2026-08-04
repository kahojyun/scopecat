"""Concrete numeric quantities shared by durable and runtime contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from scopecat.kernel.units import (
    compatible_units,
    from_base_value,
    is_supported_unit,
    to_base_value,
)


class Quantity(BaseModel):
    """A numeric value with an explicit unit."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    value: float
    unit: str

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> object:
        if not isinstance(value, int | float) or isinstance(value, bool):
            msg = "quantity value must be an int or float"
            raise ValueError(msg)
        return value

    def __init__(
        self,
        value: float | None = None,
        unit: str | None = None,
        **data: object,
    ) -> None:
        if value is not None:
            if "value" in data:
                msg = "Quantity value was provided twice"
                raise TypeError(msg)
            data["value"] = value
        if unit is not None:
            if "unit" in data:
                msg = "Quantity unit was provided twice"
                raise TypeError(msg)
            data["unit"] = unit
        super().__init__(**data)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        if not is_supported_unit(value):
            msg = f"unsupported unit: {value}"
            raise ValueError(msg)
        return value

    def to(self, unit: str) -> Quantity:
        """Return this quantity converted to another compatible linear unit."""

        if not is_supported_unit(unit):
            msg = f"unsupported unit: {unit}"
            raise ValueError(msg)
        if self.unit == unit:
            return self
        if not compatible_units(self.unit, unit):
            msg = f"cannot convert {self.unit!r} to {unit!r}"
            raise ValueError(msg)
        base_value = to_base_value(self.value, self.unit)
        converted = None if base_value is None else from_base_value(base_value, unit)
        if converted is None:
            msg = f"unit conversion is not linear: {self.unit!r} to {unit!r}"
            raise ValueError(msg)
        return Quantity(value=converted, unit=unit)

    def __add__(self, other: object) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        converted = other.to(self.unit)
        return Quantity(value=self.value + converted.value, unit=self.unit)

    def __sub__(self, other: object) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        converted = other.to(self.unit)
        return Quantity(value=self.value - converted.value, unit=self.unit)

    def __mul__(self, other: object) -> Quantity:
        if not isinstance(other, int | float) or isinstance(other, bool):
            return NotImplemented
        return Quantity(value=self.value * float(other), unit=self.unit)

    def __rmul__(self, other: object) -> Quantity:
        return self.__mul__(other)

    def __truediv__(self, other: object) -> Quantity:
        if not isinstance(other, int | float) or isinstance(other, bool):
            return NotImplemented
        if other == 0:
            msg = "cannot divide quantity by zero"
            raise ZeroDivisionError(msg)
        return Quantity(value=self.value / float(other), unit=self.unit)
