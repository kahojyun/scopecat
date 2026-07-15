"""Opaque runtime payload values shared across experiment layers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PayloadValue(BaseModel):
    """An opaque, in-memory value tagged with its authoring schema.

    The payload itself is deliberately excluded from durable model dumps.  It
    follows the same transient boundary as in-memory compute functions and is
    unwrapped immediately before a compute function is called.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    schema_id: str
    payload: object = Field(default=None, exclude=True)


__all__ = ["PayloadValue"]
