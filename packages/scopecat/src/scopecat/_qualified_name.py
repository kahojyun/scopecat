"""Injective display names for structurally scoped transient symbols."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote


def qualified_name(scope: Sequence[str], local_id: str) -> str:
    """Render a structural scope without allowing path-segment collisions."""

    return "/".join(quote(segment, safe="-._~[]") for segment in (*scope, local_id))


__all__ = ["qualified_name"]
