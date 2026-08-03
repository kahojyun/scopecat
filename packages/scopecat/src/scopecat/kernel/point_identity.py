"""Stable logical point identities shared by compilation and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.kernel.content_identity import stable_content_hash

type PointDomainLayout = Literal["product_grid", "point_cloud"]


@dataclass(frozen=True, slots=True)
class PointDomainId:
    """Nominal identity of one point domain inside a program."""

    program_id: str
    domain_id: str

    def __post_init__(self) -> None:
        if not self.program_id or not self.domain_id:
            msg = "point domain program and local ids must be non-empty"
            raise ValueError(msg)

    @property
    def value(self) -> str:
        """Return a stable transport-safe projection of this nominal identity."""

        return stable_content_hash(
            {
                "kind": "scopecat.point_domain.v1",
                "program_id": self.program_id,
                "domain_id": self.domain_id,
            }
        )


@dataclass(frozen=True, slots=True)
class LogicalPointId:
    """Stable identity derived only from a domain namespace and ordinal."""

    domain_id: PointDomainId
    logical_ordinal: int

    def __post_init__(self) -> None:
        if self.logical_ordinal < 0:
            msg = "logical point ordinal must be non-negative"
            raise ValueError(msg)

    @property
    def value(self) -> str:
        """Return the stable durable projection used by runtime records."""

        return stable_content_hash(
            {
                "point_domain": {
                    "program_id": self.domain_id.program_id,
                    "domain_id": self.domain_id.domain_id,
                },
                "kind": "scopecat.logical_point.v1",
                "logical_ordinal": self.logical_ordinal,
            }
        )


__all__ = ["LogicalPointId", "PointDomainId", "PointDomainLayout"]
