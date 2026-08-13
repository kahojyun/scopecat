"""Logical point contracts shared by planning, execution, and measurement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.point_identity import LogicalPointId, PointDomainLayout
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import TableColumn
from scopecat.program.point_domain import PointAxes, point_axis_size

type PointProposalSource = Literal["author", "optimizer", "operator"]


@dataclass(frozen=True, slots=True)
class PointProposalAttempt:
    """One freshness-bearing coordinate proposal evaluated at a run boundary."""

    coordinates: Mapping[str, CellValue]
    source: PointProposalSource = "author"
    based_on_completed_point_count: int | None = None

    def __post_init__(self) -> None:
        if (
            self.based_on_completed_point_count is not None
            and self.based_on_completed_point_count < 0
        ):
            raise ValueError("completed point count must be non-negative")
        object.__setattr__(
            self,
            "coordinates",
            MappingProxyType(dict(self.coordinates)),
        )

    @property
    def coordinate_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(dict(self.coordinates))
        )

    @property
    def proposal_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(
                {
                    "schema": "scopecat.point_proposal_attempt.v1",
                    "coordinates": dict(self.coordinates),
                    "source": self.source,
                    "based_on_completed_point_count": (
                        self.based_on_completed_point_count
                    ),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class OperatorPointRequest:
    """One durable operator request, independent of proposal freshness."""

    request_id: str
    coordinate_mode: Literal["snap", "free"]
    requested_coordinates: Mapping[str, CellValue]
    coordinates: Mapping[str, CellValue]

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("operator point request id must be non-empty")
        object.__setattr__(
            self,
            "requested_coordinates",
            MappingProxyType(dict(self.requested_coordinates)),
        )
        object.__setattr__(
            self,
            "coordinates",
            MappingProxyType(dict(self.coordinates)),
        )

    @property
    def coordinate_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(dict(self.coordinates))
        )

    @property
    def request_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(
                {
                    "schema": "scopecat.operator_point_request.v1",
                    "request_id": self.request_id,
                    "coordinate_mode": self.coordinate_mode,
                    "requested_coordinates": dict(self.requested_coordinates),
                    "resolved_coordinates": dict(self.coordinates),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AcceptedRunPoint:
    """One closed logical point retained by the executable program."""

    logical_id: LogicalPointId
    coordinates: Mapping[str, CellValue]
    proposal_fingerprint: str | None = None
    source: PointProposalSource = "author"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coordinates",
            MappingProxyType(dict(self.coordinates)),
        )

    @classmethod
    def accept(
        cls,
        candidate: PointProposalAttempt,
        *,
        logical_id: LogicalPointId,
    ) -> AcceptedRunPoint:
        return cls(
            logical_id=logical_id,
            coordinates=candidate.coordinates,
            proposal_fingerprint=candidate.proposal_fingerprint,
            source=candidate.source,
        )

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
    "AcceptedRunPoint",
    "OperatorPointRequest",
    "PointProposalAttempt",
    "PointProposalSource",
    "RunPointCatalog",
    "RunPointContract",
]
