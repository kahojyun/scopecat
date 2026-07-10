"""Generic entity references used by experiment authoring and planning."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntityRef(BaseModel):
    """Reference to a domain entity without making the domain core vocabulary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


def entity_ref(entity: EntityRef | str, *, kind: str | None = None) -> EntityRef:
    if isinstance(entity, EntityRef):
        return entity
    return EntityRef(id=entity, kind=kind)


__all__ = ["EntityRef", "entity_ref"]
