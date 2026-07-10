"""Payload references and runtime values shared across experiment layers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComputeResultRef(BaseModel):
    """Durable reference to one point-local compute result."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    node_id: str = Field(min_length=1)


class PayloadValue(BaseModel):
    """An opaque, in-memory value tagged with its authoring schema.

    The payload itself is deliberately excluded from durable model dumps.  It
    follows the same transient boundary as in-memory compute functions and is
    unwrapped immediately before a compute function is called.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_id: str
    payload: Any = Field(default=None, exclude=True)


__all__ = ["ComputeResultRef", "PayloadValue"]
