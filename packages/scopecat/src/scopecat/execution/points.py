"""Closed logical points owned by executable programs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.kernel.point_identity import LogicalPointId
from scopecat.measurements.results import CoordinateValue


@dataclass(frozen=True, slots=True)
class RunPoint:
    """One closed logical point retained by the executable program."""

    logical_id: LogicalPointId
    coordinates: Mapping[str, CoordinateValue]

    @property
    def ordinal(self) -> int:
        return self.logical_id.logical_ordinal

    @property
    def logical_ordinal(self) -> int:
        return self.ordinal

    @property
    def row(self) -> Mapping[str, CoordinateValue]:
        return self.coordinates


@dataclass(frozen=True, slots=True)
class RunPointContract:
    """Point identity and coordinate contract independent of admitted values."""

    experiment_id: str
    experiment_kind: str
    coordinate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunPointCatalog:
    """Run-owned logical identity and coordinate inventory."""

    contract: RunPointContract
    points: tuple[RunPoint, ...]

    @property
    def experiment_id(self) -> str:
        return self.contract.experiment_id

    @property
    def experiment_kind(self) -> str:
        return self.contract.experiment_kind

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self.contract.coordinate_ids


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
    "RunPoint",
    "RunPointCatalog",
    "RunPointContract",
]
