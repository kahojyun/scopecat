"""Generic entity references used by experiment authoring and planning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from scopecat._frozen import (
    FrozenMapping,
    freeze_json_mapping,
    thaw_json_value,
)


def _empty_entity_metadata() -> Mapping[str, object]:
    return FrozenMapping()


class EntityRef(BaseModel):
    """Reference to a domain entity without making the domain core vocabulary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    id: str
    kind: str | None = None
    metadata: Mapping[str, object] = Field(default_factory=_empty_entity_metadata)

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata(
        cls,
        value: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Normalize metadata into an immutable finite JSON object."""

        return normalize_entity_metadata(value)

    @field_serializer("metadata")
    def serialize_metadata(self, value: object) -> object:
        """Serialize immutable authoring snapshots as ordinary JSON containers."""

        return thaw_json_value(normalize_entity_metadata(value))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> EntityRef:
        """Copy through validation so metadata remains recursively immutable."""

        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


def entity_identity(value: EntityRef) -> tuple[str | None, str]:
    """Return the durable entity identity; metadata is descriptive only."""

    return value.kind, value.id


def same_entity_identity(left: EntityRef, right: EntityRef) -> bool:
    """Compare the complete durable identity while ignoring metadata."""

    return entity_identity(left) == entity_identity(right)


def normalize_entity_metadata(value: object) -> FrozenMapping[str, object]:
    """Return a recursively immutable finite JSON metadata object."""

    if not isinstance(value, Mapping):
        msg = "entity metadata must be a JSON object"
        raise ValueError(msg)
    return freeze_json_mapping(
        cast("Mapping[str, object]", value),
        path="entity metadata",
    )


def entity_ref(entity: EntityRef | str, *, kind: str | None = None) -> EntityRef:
    if isinstance(entity, EntityRef):
        return entity
    return EntityRef(id=entity, kind=kind)


__all__ = [
    "EntityRef",
    "entity_identity",
    "entity_ref",
    "normalize_entity_metadata",
    "same_entity_identity",
]
