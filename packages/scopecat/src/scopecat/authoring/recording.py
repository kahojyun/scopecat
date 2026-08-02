"""Typed acquisition-result projections for experiment recording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scopecat.measurements.results import MeasurementVariableRole
from scopecat.program.products import ProductRef


@dataclass(frozen=True, slots=True)
class RecordingTarget:
    """One product and its dataset role inside a typed result bundle."""

    product: ProductRef
    role: MeasurementVariableRole = "observable"


class RecordableProducts(Protocol):
    """A typed acquisition result that can be recorded as one dataset fragment."""

    def recording_targets(self) -> tuple[RecordingTarget, ...]: ...


__all__ = ["RecordableProducts", "RecordingTarget"]
