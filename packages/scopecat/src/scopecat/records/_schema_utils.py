"""Shared schema validation mechanics for typed data models."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.kernel.units import is_supported_unit


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
