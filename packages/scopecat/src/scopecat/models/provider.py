"""Shared provider descriptor models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderOptionDescription:
    id: str
    dtype: str
    required: bool = False
    default: object | None = None
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["ProviderOptionDescription"]
