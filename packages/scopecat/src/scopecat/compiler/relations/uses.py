"""Executable relation occurrences in transient compiler IR."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelationUse[ValueT]:
    """A relation value at one executable use site."""

    value: ValueT


def relation_use[ValueT](value: ValueT) -> RelationUse[ValueT]:
    return RelationUse(value)
