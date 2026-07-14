"""Closed JSON-like values used before durable Pydantic serialization."""

from __future__ import annotations

from collections.abc import Mapping

type JsonValue = (
    str
    | bool
    | int
    | float
    | None
    | list[JsonValue]
    | tuple[JsonValue, ...]
    | Mapping[str, JsonValue]
)

__all__ = ["JsonValue"]
