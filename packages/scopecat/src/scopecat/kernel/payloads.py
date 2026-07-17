"""Opaque runtime payload values shared across experiment layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadValue:
    """An opaque, in-memory value tagged with its authoring schema.

    The immutable wrapper follows the same transient boundary as in-memory
    compute functions. Its opaque body is unwrapped immediately before a
    compute function is called.
    """

    schema_id: str
    payload: object = None
