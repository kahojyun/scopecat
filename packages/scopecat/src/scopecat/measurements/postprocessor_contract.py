"""Static contract for one point-local measurement calculation."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from scopecat.records.measurement import MeasurementValue

type MeasurementPostprocessorKernel = Callable[
    [MeasurementValue],
    Mapping[str, MeasurementValue],
]

__all__ = ["MeasurementPostprocessorKernel"]
