"""Neutral measurement value types shared before durable dataset models."""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import GetJsonSchemaHandler, TypeAdapter, WithJsonSchema
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from scopecat.kernel.value_types import Bool, Entity, Float, Int, Scalar, String
from scopecat.kernel.value_types import Quantity as QuantityType

type MeasurementVariableRole = Literal["coordinate", "observable"]
type MeasurementDType = Literal["float64", "int64", "complex128", "bool", "string"]
type MeasurementArrayElement = (
    np.bool_ | np.int64 | np.float64 | np.complex128 | np.str_
)

type MeasurementComplexJson = Annotated[
    dict[str, float],
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "real": {"type": "number"},
                "imag": {"type": "number"},
            },
            "required": ["real", "imag"],
            "additionalProperties": False,
        }
    ),
]
type MeasurementArrayJsonLeaf = bool | int | float | str | MeasurementComplexJson
type MeasurementArrayJsonItem = (
    MeasurementArrayJsonLeaf | list[MeasurementArrayJsonItem]
)
type MeasurementArrayJson = list[MeasurementArrayJsonItem]

_MEASUREMENT_ARRAY_JSON_CORE_SCHEMA = TypeAdapter(MeasurementArrayJson).core_schema


class _MeasurementArrayJsonSchema:
    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return handler(_MEASUREMENT_ARRAY_JSON_CORE_SCHEMA)


MeasurementArrayData = Annotated[
    NDArray[MeasurementArrayElement],
    _MeasurementArrayJsonSchema,
]
type NativeMeasurementScalar = bool | int | float | complex | str
type NativeMeasurementValue = NativeMeasurementScalar | MeasurementArrayData


def measurement_value_spec_from_scalar(
    value_type: Scalar,
) -> tuple[MeasurementDType, str | None]:
    """Project one program scalar type into its durable measurement schema."""

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
