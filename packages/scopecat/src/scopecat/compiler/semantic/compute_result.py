"""Symbolic references to point-local compute results."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.semantic.model import ValueId


@dataclass(frozen=True, slots=True)
class ComputeResultRef:
    """Internal symbolic reference to one point-local compute result."""

    value_id: ValueId
