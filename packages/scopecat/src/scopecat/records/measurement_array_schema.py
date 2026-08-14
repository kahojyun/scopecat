"""Pydantic schema adapter for durable NumPy measurement arrays."""

from __future__ import annotations

from typing import Annotated

import numpy as np
from numpy.typing import NDArray
from pydantic import GetJsonSchemaHandler, TypeAdapter, WithJsonSchema
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from scopecat.program.measurement_types import MeasurementArrayData

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


MeasurementArrayPayload = Annotated[
    MeasurementArrayData,
    _MeasurementArrayJsonSchema,
]

type MeasurementBooleanArrayJsonItem = bool | list[MeasurementBooleanArrayJsonItem]
type MeasurementBooleanArrayJson = list[MeasurementBooleanArrayJsonItem]

_MEASUREMENT_BOOLEAN_ARRAY_JSON_CORE_SCHEMA = TypeAdapter(
    MeasurementBooleanArrayJson
).core_schema


class _MeasurementBooleanArrayJsonSchema:
    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return handler(_MEASUREMENT_BOOLEAN_ARRAY_JSON_CORE_SCHEMA)


MeasurementBooleanArrayPayload = Annotated[
    NDArray[np.bool_],
    _MeasurementBooleanArrayJsonSchema,
]

__all__ = ["MeasurementArrayPayload", "MeasurementBooleanArrayPayload"]
