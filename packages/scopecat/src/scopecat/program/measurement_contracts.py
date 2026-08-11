"""Static program contract for one point-local measurement calculation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scopecat.records.measurement import MeasurementValue

type MeasurementComputeKernel = Callable[
    [Mapping[str, object]],
    Mapping[str, "MeasurementValue"],
]
type SingleMeasurementComputeKernel = Callable[
    ["MeasurementValue"],
    Mapping[str, "MeasurementValue"],
]

__all__ = ["MeasurementComputeKernel", "SingleMeasurementComputeKernel"]
