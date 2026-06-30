"""Shared schema validation mechanics for typed data models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from scopecat.units import is_supported_unit


def validate_supported_unit(value: str | None) -> str | None:
    if value is not None and not is_supported_unit(value):
        msg = f"unsupported unit: {value}"
        raise ValueError(msg)
    return value


def ensure_unique_ids(ids: Sequence[str], message: str) -> None:
    if len(set(ids)) != len(ids):
        raise ValueError(message)


def missing_references(values: Sequence[str], known: set[str]) -> list[str]:
    return [value for value in values if value not in known]


def validate_shape_rank(
    *, shape: Sequence[int], dims: Sequence[str], message: str
) -> None:
    if len(shape) != len(dims):
        raise ValueError(message)


def declared_shape_for_dims(
    *, dims: Sequence[str], sizes_by_dimension: dict[str, int]
) -> list[int]:
    return [sizes_by_dimension[dimension_id] for dimension_id in dims]


def array_shape(value: Any, path: str) -> list[int]:
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    if not items:
        return [0]
    child_shapes = [array_shape(item, path) for item in items]
    first_shape = child_shapes[0]
    for child_shape in child_shapes[1:]:
        if child_shape != first_shape:
            msg = f"{path} contains a ragged array"
            raise ValueError(msg)
    return [len(items), *first_shape]


def validate_array_dtype(value: Any, dtype: str, path: str) -> None:
    if isinstance(value, list):
        for index, item in enumerate(cast(list[Any], value)):
            validate_array_dtype(item, dtype, f"{path}[{index}]")
        return
    validate_scalar_dtype(value, dtype, path)


def validate_scalar_dtype(value: Any, dtype: str, path: str) -> None:
    if dtype == "float64":
        if isinstance(value, bool) or not isinstance(value, int | float):
            _raise_dtype_error(path, dtype)
        return
    if dtype == "int64":
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or int(value) != value
        ):
            _raise_dtype_error(path, dtype)
        return
    if dtype == "bool":
        if not isinstance(value, bool):
            _raise_dtype_error(path, dtype)
        return
    if dtype == "string":
        if not isinstance(value, str):
            _raise_dtype_error(path, dtype)
        return
    _raise_dtype_error(path, dtype)


def _raise_dtype_error(path: str, dtype: str) -> None:
    msg = f"{path} must be {dtype}"
    raise ValueError(msg)
