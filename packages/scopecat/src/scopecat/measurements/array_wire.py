"""Portable binary encoding for one measurement array."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray

from scopecat.program.measurement_types import MeasurementDType
from scopecat.records.measurement import MeasurementArray

type BinaryBuffer = bytes | bytearray | memoryview
type EncodedMeasurementArray = bytes | memoryview


class MeasurementArrayWireError(ValueError):
    """A binary measurement-array payload violates its declared contract."""


def encode_measurement_array(value: MeasurementArray) -> EncodedMeasurementArray:
    """Encode one canonical measurement array without Python scalar expansion."""

    expected_count = math.prod(value.shape)
    if value.values.size != expected_count or value.values.shape != value.shape:
        raise MeasurementArrayWireError(
            "measurement array shape does not match its values"
        )
    if value.dtype == "float64":
        if (
            value.values.dtype != np.dtype(np.float64)
            or not np.isfinite(value.values).all()
        ):
            raise MeasurementArrayWireError("float64 measurement array is invalid")
        return _array_bytes(value.values.astype("<f8", copy=False))
    if value.dtype == "int64":
        if value.values.dtype != np.dtype(np.int64):
            raise MeasurementArrayWireError("int64 measurement array is invalid")
        return _array_bytes(value.values.astype("<i8", copy=False))
    if value.dtype == "complex128":
        if (
            value.values.dtype != np.dtype(np.complex128)
            or not np.isfinite(value.values).all()
        ):
            raise MeasurementArrayWireError("complex128 measurement array is invalid")
        return _array_bytes(value.values.astype("<c16", copy=False))
    if value.dtype == "bool":
        if value.values.dtype != np.dtype(np.bool_):
            raise MeasurementArrayWireError("bool measurement array is invalid")
        return _array_bytes(value.values.view("u1"))
    if value.values.dtype.kind != "U":
        raise MeasurementArrayWireError("string measurement array is invalid")
    return _encode_strings(cast("NDArray[np.str_]", value.values))


def decode_measurement_array(
    content: BinaryBuffer,
    *,
    dtype: MeasurementDType,
    unit: str | None,
    shape: tuple[int, ...],
    metadata: Mapping[str, object],
) -> MeasurementArray:
    """Decode one binary payload into the canonical immutable array model."""

    count = math.prod(shape)
    if dtype == "float64":
        leaves = _decode_numeric_array(content, count=count, dtype="<f8")
    elif dtype == "int64":
        leaves = _decode_numeric_array(content, count=count, dtype="<i8")
    elif dtype == "complex128":
        leaves = _decode_numeric_array(content, count=count, dtype="<c16")
    elif dtype == "bool":
        raw_bools = cast(
            "NDArray[np.uint8]",
            _decode_numeric_array(content, count=count, dtype="u1"),
        )
        if np.any(raw_bools > 1):
            raise MeasurementArrayWireError("bool measurement array is invalid")
        leaves = raw_bools.view(np.bool_)
    else:
        leaves = np.asarray(_decode_strings(content, count=count), dtype=np.str_)

    try:
        return MeasurementArray.create(
            dtype=dtype,
            unit=unit,
            values=leaves.reshape(shape),
            metadata=metadata,
        )
    except ValueError as error:
        raise MeasurementArrayWireError(
            "measurement array payload does not match its descriptor"
        ) from error


def _decode_numeric_array(
    content: BinaryBuffer,
    *,
    count: int,
    dtype: Literal["<c16", "<f8", "<i8", "<u8", "u1"],
) -> NDArray[np.generic]:
    selected_dtype = np.dtype(dtype)
    if len(content) != count * selected_dtype.itemsize:
        raise MeasurementArrayWireError("measurement array payload has invalid size")
    return np.frombuffer(content, dtype=selected_dtype, count=count)


def _array_bytes(values: NDArray[np.generic]) -> memoryview:
    if values.size == 0:
        return memoryview(b"")
    return memoryview(values).cast("B")


def _encode_strings(values: NDArray[np.str_]) -> bytes:
    offsets = [0]
    chunks: list[bytes] = []
    size = 0
    selected = cast("NDArray[np.str_]", values.reshape(-1))
    for index in range(selected.size):
        item = cast("np.str_", selected[index])
        try:
            encoded = str(item).encode("utf-8")
        except UnicodeEncodeError as error:
            raise MeasurementArrayWireError(
                "string measurement array is not valid UTF-8"
            ) from error
        chunks.append(encoded)
        size += len(encoded)
        offsets.append(size)
    return np.asarray(offsets, dtype="<u8").tobytes() + b"".join(chunks)


def _decode_strings(content: BinaryBuffer, *, count: int) -> tuple[str, ...]:
    offset_bytes = (count + 1) * 8
    if len(content) < offset_bytes:
        raise MeasurementArrayWireError("string measurement array has invalid size")
    offsets = cast(
        "NDArray[np.uint64]",
        _decode_numeric_array(
            memoryview(content)[:offset_bytes],
            count=count + 1,
            dtype="<u8",
        ),
    )
    encoded = memoryview(content)[offset_bytes:]
    if (
        int(cast("np.uint64", offsets[0])) != 0
        or int(cast("np.uint64", offsets[-1])) != len(encoded)
        or any(
            int(cast("np.uint64", offsets[index]))
            > int(cast("np.uint64", offsets[index + 1]))
            for index in range(count)
        )
    ):
        raise MeasurementArrayWireError("string measurement array offsets are invalid")
    try:
        return tuple(
            bytes(
                encoded[
                    int(cast("np.uint64", offsets[index])) : int(
                        cast("np.uint64", offsets[index + 1])
                    )
                ]
            ).decode("utf-8")
            for index in range(count)
        )
    except UnicodeDecodeError as error:
        raise MeasurementArrayWireError(
            "string measurement array is not valid UTF-8"
        ) from error


__all__ = [
    "EncodedMeasurementArray",
    "MeasurementArrayWireError",
    "decode_measurement_array",
    "encode_measurement_array",
]
