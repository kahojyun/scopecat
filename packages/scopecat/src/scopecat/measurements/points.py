"""Logical point contracts shared by planning, execution, and measurement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.graph.relations.model import CellValue
from scopecat.kernel.point_identity import LogicalPointId


@dataclass(frozen=True, slots=True)
class RunPoint:
    """One closed logical point retained by the executable program."""

    logical_id: LogicalPointId
    coordinates: Mapping[str, CellValue]

    @property
    def ordinal(self) -> int:
        return self.logical_id.logical_ordinal

    @property
    def logical_ordinal(self) -> int:
        return self.ordinal

    @property
    def row(self) -> Mapping[str, CellValue]:
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


__all__ = ["RunPoint", "RunPointCatalog", "RunPointContract"]
