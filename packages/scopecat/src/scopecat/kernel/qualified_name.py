"""Injective display names for structurally scoped transient symbols."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote, unquote


def qualified_name(scope: Sequence[str], local_id: str) -> str:
    """Render a structural scope without allowing path-segment collisions."""

    return "/".join(quote(segment, safe="-._~[]") for segment in (*scope, local_id))


def parse_qualified_name(value: str) -> tuple[tuple[str, ...], str]:
    """Parse one canonical display name back into structural path segments."""

    if not value:
        msg = "qualified names must be non-empty"
        raise ValueError(msg)
    segments = tuple(unquote(segment) for segment in value.split("/"))
    if any(not segment for segment in segments):
        msg = "qualified name segments must be non-empty"
        raise ValueError(msg)
    return segments[:-1], segments[-1]


__all__ = ["parse_qualified_name", "qualified_name"]
