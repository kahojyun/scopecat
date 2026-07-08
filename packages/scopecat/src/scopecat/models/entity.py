"""Generic entity references used by experiment authoring and planning."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class EntityRef(BaseModel):
    """Reference to a domain entity without making the domain core vocabulary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class EntityArray(BaseModel):
    """Ordered entity set for simultaneous operations and entity-shaped records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entities: tuple[EntityRef, ...]
    kind: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(entity.id for entity in self.entities)

    @property
    def size(self) -> int:
        return len(self.entities)


def entity_ref(entity: EntityRef | str, *, kind: str | None = None) -> EntityRef:
    if isinstance(entity, EntityRef):
        return entity
    return EntityRef(id=entity, kind=kind)


def entity_array(
    entities: Sequence[EntityRef | str],
    *,
    kind: str | None = None,
) -> EntityArray:
    return EntityArray(
        entities=tuple(entity_ref(entity, kind=kind) for entity in entities),
        kind=kind,
    )


__all__ = ["EntityArray", "EntityRef", "entity_array", "entity_ref"]
