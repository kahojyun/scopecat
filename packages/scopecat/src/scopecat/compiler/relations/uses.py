"""Nominal identity for executable relation occurrences in transient IR.

Relation-use identity answers only "is this the same executable occurrence?".
It deliberately carries no structural path, semantic role, backend choice, or
plan fingerprint; those are independent compiler facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, override
from uuid import uuid4

from pydantic import ConfigDict


@dataclass(frozen=True, slots=True)
class RelationUseId:
    """Opaque identity of one executable relation occurrence."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "relation-use identity must be non-empty"
            raise ValueError(msg)

    @classmethod
    def fresh(cls) -> RelationUseId:
        return cls(uuid4().hex)

    @override
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RelationUse[ValueT]:
    """A value paired with the identity of this particular use occurrence."""

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        revalidate_instances="always",
    )

    value: ValueT
    id: RelationUseId = field(default_factory=RelationUseId.fresh)


def relation_use[ValueT](value: ValueT) -> RelationUse[ValueT]:
    """Create a fresh executable occurrence for ``value``."""

    return RelationUse(value)


__all__ = ["RelationUse", "RelationUseId", "relation_use"]
