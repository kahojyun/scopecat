# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false
"""Shared Arrow types and buffer-backed measurement value columns."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

import numpy as np
import pyarrow as pa

from scopecat.program.measurement_types import MeasurementDType
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementValue,
)

MEASUREMENT_COMPLEX_ARROW_TYPE = pa.struct(
    [
        pa.field("real", pa.float64(), nullable=False),
        pa.field("imag", pa.float64(), nullable=False),
    ]
)


def measurement_arrow_scalar_type(dtype: MeasurementDType) -> pa.DataType:
    """Return the canonical Arrow leaf type for one measurement dtype."""

    if dtype == "bool":
        return pa.bool_()
    if dtype == "int64":
        return pa.int64()
    if dtype == "float64":
        return pa.float64()
    if dtype == "string":
        return pa.large_string()
    return MEASUREMENT_COMPLEX_ARROW_TYPE


def measurement_arrow_value_type(
    dtype: MeasurementDType,
    shape: Sequence[int | None],
    *,
    item_nullable: bool = True,
) -> pa.DataType:
    """Build one scalar or nested fixed/ragged Arrow value type."""

    selected = measurement_arrow_scalar_type(dtype)
    for extent in reversed(shape):
        item = pa.field("item", selected, nullable=item_nullable)
        selected = (
            pa.large_list(item) if extent is None else pa.list_(item, list_size=extent)
        )
    return selected


def measurement_values_to_arrow_array(
    values: Sequence[MeasurementValue],
    *,
    dtype: MeasurementDType,
    shape: Sequence[int | None],
    item_nullable: bool = True,
) -> pa.Array:
    """Encode one point-aligned value sequence without boxing numeric arrays."""

    expected_shape = tuple(shape)
    value_type = measurement_arrow_value_type(
        dtype,
        expected_shape,
        item_nullable=item_nullable,
    )
    if not expected_shape:
        return _encode_scalar_column(values, dtype=dtype, value_type=value_type)
    if not values:
        return pa.array([], type=value_type)
    encoded_rows = [
        (
            pa.nulls(1, type=value_type)
            if isinstance(value, MeasurementUnavailable)
            else _encode_array_row(
                _require_array(value),
                dtype=dtype,
                expected_shape=expected_shape,
                value_type=value_type,
                item_nullable=item_nullable,
            )
        )
        for value in values
    ]
    return pa.concat_arrays(encoded_rows)


def _encode_scalar_column(
    values: Sequence[MeasurementValue],
    *,
    dtype: MeasurementDType,
    value_type: pa.DataType,
) -> pa.Array:
    unavailable = np.fromiter(
        (isinstance(value, MeasurementUnavailable) for value in values),
        dtype=np.bool_,
        count=len(values),
    )
    if dtype == "string":
        return pa.array(
            [
                None
                if isinstance(value, MeasurementUnavailable)
                else _require_scalar(value).value
                for value in values
            ],
            type=value_type,
        )
    if dtype == "complex128":
        selected = np.fromiter(
            (
                0j
                if isinstance(value, MeasurementUnavailable)
                else _as_complex(_require_scalar(value).value)
                for value in values
            ),
            dtype=np.complex128,
            count=len(values),
        )
        return pa.StructArray.from_arrays(
            [pa.array(selected.real), pa.array(selected.imag)],
            fields=list(MEASUREMENT_COMPLEX_ARROW_TYPE),
            mask=pa.array(unavailable),
        )
    selected = np.fromiter(
        (
            0
            if isinstance(value, MeasurementUnavailable)
            else _require_scalar(value).value
            for value in values
        ),
        dtype=_numpy_dtype(dtype),
        count=len(values),
    )
    return pa.array(selected, mask=unavailable, type=value_type)


def _encode_array_row(
    value: MeasurementArray,
    *,
    dtype: MeasurementDType,
    expected_shape: tuple[int | None, ...],
    value_type: pa.DataType,
    item_nullable: bool,
) -> pa.Array:
    if value.dtype != dtype or not _shape_matches(expected_shape, value.shape):
        raise ValueError("measurement value does not match its Arrow column contract")
    shape = value.shape
    if any(
        actual == 0 and expected == 0
        for expected, actual in zip(expected_shape, shape, strict=True)
    ):
        return pa.array([_empty_array_tree(shape)], type=value_type)
    selected = value.values.reshape(-1)
    invalid = (
        None if value.availability is None else ~value.availability.valid.reshape(-1)
    )
    if dtype == "complex128":
        complex_values = cast(
            "np.ndarray[tuple[int], np.dtype[np.complex128]]",
            selected,
        )
        encoded: pa.Array = pa.StructArray.from_arrays(
            [
                pa.array(complex_values.real),
                pa.array(complex_values.imag),
            ],
            fields=list(MEASUREMENT_COMPLEX_ARROW_TYPE),
            mask=None if invalid is None else pa.array(invalid),
        )
    else:
        encoded = pa.array(
            selected,
            mask=invalid,
            type=measurement_arrow_scalar_type(dtype),
        )
    for index in reversed(range(len(shape))):
        expected_extent = expected_shape[index]
        actual_extent = shape[index]
        item = pa.field("item", encoded.type, nullable=item_nullable)
        if expected_extent is None:
            parent_count = math.prod(shape[:index])
            offsets = np.arange(parent_count + 1, dtype=np.int64) * actual_extent
            encoded = pa.LargeListArray.from_arrays(
                offsets,
                encoded,
                type=pa.large_list(item),
            )
        else:
            encoded = pa.FixedSizeListArray.from_arrays(
                encoded,
                type=pa.list_(item, actual_extent),
            )
    if len(encoded) != 1 or not encoded.type.equals(value_type):
        raise ValueError("measurement array shape cannot form its Arrow row type")
    return encoded


def _require_scalar(value: MeasurementValue) -> MeasurementScalar:
    if not isinstance(value, MeasurementScalar):
        raise ValueError("measurement Arrow scalar column requires scalar values")
    return value


def _require_array(value: MeasurementValue) -> MeasurementArray:
    if not isinstance(value, MeasurementArray):
        raise ValueError("measurement Arrow array column requires array values")
    return value


def _shape_matches(
    expected: tuple[int | None, ...],
    actual: tuple[int, ...],
) -> bool:
    return len(expected) == len(actual) and all(
        expected_extent is None or expected_extent == actual_extent
        for expected_extent, actual_extent in zip(expected, actual, strict=True)
    )


def _empty_array_tree(shape: Sequence[int]) -> list[object]:
    extent = shape[0]
    if len(shape) == 1:
        return [None] * extent
    return [_empty_array_tree(shape[1:]) for _ in range(extent)]


def _as_complex(value: object) -> complex:
    if isinstance(value, complex):
        return value
    raise ValueError("complex128 measurement values must be native complex numbers")


def _numpy_dtype(dtype: MeasurementDType) -> np.dtype[np.generic]:
    if dtype == "string":
        return np.dtype(np.str_)
    return np.dtype(dtype)


__all__ = [
    "MEASUREMENT_COMPLEX_ARROW_TYPE",
    "measurement_arrow_scalar_type",
    "measurement_arrow_value_type",
    "measurement_values_to_arrow_array",
]
