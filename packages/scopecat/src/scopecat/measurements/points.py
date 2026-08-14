"""Logical point contracts shared by planning, execution, and measurement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.kernel.point_identity import PointDomainLayout
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import TableColumn
from scopecat.program.point_domain import PointAxes, point_axis_size


@dataclass(frozen=True, slots=True)
class RunPointContract:
    """Complete planned point identity and coordinate contract for one run."""

    experiment_id: str
    experiment_kind: str
    point_count: int | None
    point_limit: int
    coordinate_columns: tuple[TableColumn, ...]
    domain_layout: PointDomainLayout = "product_grid"
    domain_axes: PointAxes[Quantity] = ()

    def __post_init__(self) -> None:
        if self.point_count is not None and self.point_count < 0:
            raise ValueError("run point count must be non-negative")
        if self.point_limit < 0:
            raise ValueError("run point limit must be non-negative")
        if self.point_count is not None and self.point_count > self.point_limit:
            raise ValueError("run point count cannot exceed its limit")

    @property
    def open_length(self) -> bool:
        return self.point_count is None

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
    points: Sequence[AcceptedRunPoint]

    @property
    def experiment_id(self) -> str:
        return self.contract.experiment_id

    @property
    def experiment_kind(self) -> str:
        return self.contract.experiment_kind

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self.contract.coordinate_ids


__all__ = [
    "RunPointCatalog",
    "RunPointContract",
]
