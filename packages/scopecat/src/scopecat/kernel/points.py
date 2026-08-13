"""Canonical proposed, requested, and accepted run point models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.value_data import CellValue

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


__all__ = [
    "AcceptedRunPoint",
    "OperatorPointRequest",
    "PointProposalAttempt",
    "PointProposalSource",
]
