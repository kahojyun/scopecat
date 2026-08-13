"""Logical point contracts shared by planning, execution, and measurement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.kernel.point_identity import LogicalPointId, PointDomainLayout
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import TableColumn
from scopecat.program.point_domain import PointAxes, point_axis_size


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
    """Complete planned point identity and coordinate contract for one run."""

    experiment_id: str
    experiment_kind: str
    point_count: int
    coordinate_columns: tuple[TableColumn, ...]
    domain_layout: PointDomainLayout = "product_grid"
    domain_axes: PointAxes[Quantity] = ()

    def __post_init__(self) -> None:
        if self.point_count < 0:
            raise ValueError("run point count must be non-negative")

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return tuple(column.id for column in self.coordinate_columns)

    @property
    def domain_axis_sizes(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (axis.id, point_axis_size(axis.source)) for axis in self.domain_axes
        )


@dataclass(frozen=True, slots=True)
class RunPointCatalog:
    """Run-owned point inventory, which may project a subset of the full contract."""

    contract: RunPointContract
    points: Sequence[RunPoint]

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
