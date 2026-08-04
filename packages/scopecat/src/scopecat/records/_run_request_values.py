"""Internal normalization for durable run-request values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel

from scopecat.kernel.quantity import Quantity


class DurableRunRequestModel(BaseModel):
    """Marker base for models in the closed run-request value domain."""


def normalize_json_value(value: object) -> object:
    """Normalize the small closed value domain accepted by request metadata."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = "run request JSON values must contain only finite numbers"
            raise ValueError(msg)
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        normalized: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = "run request JSON object keys must be strings"
                raise ValueError(msg)
            normalized[key] = normalize_json_value(item)
        return normalized
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return [normalize_json_value(item) for item in sequence]
    msg = f"unsupported run request JSON value: {type(value).__name__}"
    raise ValueError(msg)


def normalize_run_request_value(value: object) -> object:
    """Validate values already projected into the durable request wire domain."""

    if isinstance(value, DurableRunRequestModel):
        return value
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = "run request values must contain only finite numbers"
            raise ValueError(msg)
        return value
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            msg = "run request quantities must contain only finite numbers"
            raise ValueError(msg)
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        normalized: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                msg = "run request object keys must be strings"
                raise ValueError(msg)
            normalized[key] = normalize_run_request_value(item)
        return normalized
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return [normalize_run_request_value(item) for item in sequence]
    msg = f"unsupported durable run request value: {type(value).__name__}"
    raise ValueError(msg)
