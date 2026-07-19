"""Closed logical points owned by executable programs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
class RunPointCatalog:
    """Run-owned logical identity and coordinate inventory."""

    experiment_id: str
    experiment_kind: str
    coordinate_ids: tuple[str, ...]
    points: tuple[RunPoint, ...]


__all__ = ["RunPoint", "RunPointCatalog"]
