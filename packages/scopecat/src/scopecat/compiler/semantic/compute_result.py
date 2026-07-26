"""Shared identities for typed and executable compute results."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.semantic.model import ValueId
from scopecat.kernel.value_types import ValueType


@dataclass(frozen=True, slots=True)
class ComputeOutput:
    """One explicitly typed value produced by a compute operation."""

    id: ValueId
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class ComputeResultRef:
    """Internal symbolic reference to one point-local compute result."""

    value_id: ValueId
