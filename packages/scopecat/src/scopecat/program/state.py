"""Declarative desired-state contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.instrument_members import PropertyRef
from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef

type StateBinding = Quantity | EntityRef | str | int | float | bool | None | ValueRef


class DesiredState(Protocol):
    """A typed target state that can be fixed or resolved per scan point."""

    def target_assignments(self) -> Mapping[PropertyRef, StateBinding]:
        """Return the persistent property values required by this target."""
        ...


__all__ = [
    "DesiredState",
    "StateBinding",
]
