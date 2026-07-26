"""Admission state for closed logical points."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from scopecat.measurements.points import RunPoint


@dataclass(slots=True)
class AdmittedPointLedger:
    """Append-only logical points admitted to one running experiment."""

    coordinate_ids: tuple[str, ...]
    _points: list[RunPoint] = field(default_factory=list, repr=False)

    @property
    def points(self) -> tuple[RunPoint, ...]:
        return tuple(self._points)

    def admit(self, points: Sequence[RunPoint]) -> tuple[RunPoint, ...]:
        selected = tuple(points)
        expected = tuple(range(len(self._points), len(self._points) + len(selected)))
        if tuple(point.ordinal for point in selected) != expected:
            raise ValueError(
                "admitted points must extend canonical ordinals contiguously"
            )
        coordinate_ids = frozenset(self.coordinate_ids)
        if any(frozenset(point.coordinates) != coordinate_ids for point in selected):
            raise ValueError("admitted point coordinates do not match the run contract")
        self._points.extend(selected)
        return selected


__all__ = [
    "AdmittedPointLedger",
]
