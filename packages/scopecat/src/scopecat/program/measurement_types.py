"""Static measurement value types shared by programs and durable records."""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Scalar,
    String,
    ValueDType,
)
from scopecat.kernel.value_types import Quantity as QuantityType

type MeasurementVariableRole = Literal["coordinate", "observable"]
type MeasurementDType = ValueDType
type MeasurementArrayElement = (
    np.bool_ | np.int64 | np.float64 | np.complex128 | np.str_
)
type MeasurementArrayData = NDArray[MeasurementArrayElement]
type NativeMeasurementScalar = bool | int | float | complex | str
type NativeMeasurementValue = NativeMeasurementScalar | MeasurementArrayData


def measurement_value_spec_from_scalar(
    value_type: Scalar,
) -> tuple[MeasurementDType, str | None]:
    """Project one program scalar type into its measurement schema."""

    atom = value_type.atom
    if isinstance(atom, Bool):
        return "bool", None
    if isinstance(atom, Int):
        return "int64", None
    if isinstance(atom, Float):
        return "float64", None
    if isinstance(atom, QuantityType):
        return "float64", atom.unit
    if isinstance(atom, String | Entity):
        return "string", None
    raise TypeError("opaque payload scalars cannot be represented in a dataset")


__all__ = [
    "MeasurementArrayData",
    "MeasurementArrayElement",
    "MeasurementDType",
    "MeasurementVariableRole",
    "NativeMeasurementScalar",
    "NativeMeasurementValue",
    "measurement_value_spec_from_scalar",
]
