"""Opaque runtime payload values shared across experiment layers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadValue:
    """An opaque, in-memory value tagged with its authoring schema.

    The immutable wrapper follows the same transient boundary as in-memory
    compute functions. Its opaque body is unwrapped immediately before a
    compute function is called.
    """

    schema_id: str
    payload: object = None


def unwrap_payload_values(value: object) -> object:
    """Remove transient payload wrappers before invoking user computation."""

    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        return [unwrap_payload_values(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(
            unwrap_payload_values(item) for item in cast("tuple[object, ...]", value)
        )
    if isinstance(value, dict):
        return {
            name: unwrap_payload_values(item)
            for name, item in cast("Mapping[object, object]", value).items()
        }
    return value
