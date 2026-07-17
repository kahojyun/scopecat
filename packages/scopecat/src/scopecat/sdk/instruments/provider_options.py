"""Shared provider descriptor models."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import JsonValue


@dataclass(frozen=True)
class ProviderOptionDescription:
    id: str
    dtype: str
    required: bool = False
    default: object | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)
