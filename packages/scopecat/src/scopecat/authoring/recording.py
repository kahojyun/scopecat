"""Typed acquisition-result projections for experiment recording."""

from __future__ import annotations

from typing import Protocol

from scopecat.program.products import ProductRef


class RecordableProducts(Protocol):
    """A typed acquisition result that can be recorded as one dataset fragment."""

    def recording_products(self) -> tuple[ProductRef, ...]: ...


__all__ = ["RecordableProducts"]
