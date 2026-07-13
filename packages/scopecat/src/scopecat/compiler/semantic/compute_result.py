"""Symbolic references to point-local compute results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from scopecat.compiler.semantic.model import ValueId


class ComputeResultRef(BaseModel):
    """Internal symbolic reference to one point-local compute result."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    value_id: ValueId


__all__ = ["ComputeResultRef"]
