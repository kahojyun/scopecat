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
    region_id: str | None = None
    domain_proposal_fingerprint: str | None = None
    based_on_region_revision: int | None = None

    def __post_init__(self) -> None:
        if (
            self.based_on_region_revision is not None
            and self.based_on_region_revision < 0
        ):
            raise ValueError("region revision must be non-negative")
        if (self.region_id is None) != (self.domain_proposal_fingerprint is None):
            raise ValueError(
                "normalized domain points require both region and proposal identity"
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
    def proposal_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(
                {
                    "schema": "scopecat.point_proposal_attempt.v2",
                    "coordinates": dict(self.coordinates),
                    "source": self.source,
                    "region_id": self.region_id,
                    "domain_proposal_fingerprint": (self.domain_proposal_fingerprint),
                    "based_on_region_revision": self.based_on_region_revision,
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
    region_id: str | None = None
    domain_proposal_fingerprint: str | None = None

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
            region_id=candidate.region_id,
            domain_proposal_fingerprint=candidate.domain_proposal_fingerprint,
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
    "PointProposalAttempt",
    "PointProposalSource",
]
