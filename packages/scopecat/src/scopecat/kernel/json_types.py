"""Closed JSON-like values used before durable Pydantic serialization."""

from __future__ import annotations

from collections.abc import Mapping

type JsonValue = (
    str
    | bool
    | int
    | float
    | list[JsonValue]
    | tuple[JsonValue, ...]
    | Mapping[str, JsonValue]
    | None
)
