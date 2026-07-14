"""Shared entity canonicalization against an accepted topology."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from scopecat.records.config import Topology
from scopecat.records.entity import EntityRef, entity_ref

type EntityResolutionCode = Literal["unknown_entity", "kind_mismatch"]


@dataclass(frozen=True, slots=True)
class EntityResolutionIssue:
    """One structured reason an entity reference cannot bind to a topology."""

    code: EntityResolutionCode
    entity_id: str
    actual_kind: str | None = None
    requested_kind: str | None = None

    @property
    def message(self) -> str:
        if self.code == "unknown_entity":
            return f"unknown entity {self.entity_id}"
        return (
            f"entity {self.entity_id} has kind {self.actual_kind}, "
            f"not {self.requested_kind}"
        )


class EntityResolutionError(ValueError):
    """An entity reference cannot be canonicalized by the supplied topology."""

    def __init__(self, issue: EntityResolutionIssue) -> None:
        self.issue = issue
        super().__init__(issue.message)


def resolve_entity(topology: Topology, value: EntityRef | str) -> EntityRef:
    """Return the canonical topology-backed snapshot for one entity reference."""

    selected = entity_ref(value)
    known = topology.entity(selected.id)
    if known is None:
        raise EntityResolutionError(
            EntityResolutionIssue(
                code="unknown_entity",
                entity_id=selected.id,
                requested_kind=selected.kind,
            )
        )
    if (
        selected.kind is not None
        and known.kind is not None
        and selected.kind != known.kind
    ):
        raise EntityResolutionError(
            EntityResolutionIssue(
                code="kind_mismatch",
                entity_id=selected.id,
                actual_kind=known.kind,
                requested_kind=selected.kind,
            )
        )
    return EntityRef(
        id=selected.id,
        kind=selected.kind or known.kind,
        metadata={**known.metadata, **selected.metadata},
    )


def resolve_entities(
    topology: Topology,
    values: Sequence[EntityRef | str],
) -> tuple[EntityRef, ...]:
    """Canonicalize an ordered collection of entity references."""

    return tuple(resolve_entity(topology, value) for value in values)


__all__ = [
    "EntityResolutionCode",
    "EntityResolutionError",
    "EntityResolutionIssue",
    "resolve_entities",
    "resolve_entity",
]
