"""Persistent instrument-state value contracts."""

from __future__ import annotations

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef

type StateBinding = Quantity | EntityRef | str | int | float | bool | ValueRef


__all__ = [
    "StateBinding",
]
