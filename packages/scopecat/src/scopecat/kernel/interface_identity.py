"""Stable instrument interface identities."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field

INTERFACE_ID_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+/v[1-9][0-9]*$"
_INTERFACE_ID = re.compile(INTERFACE_ID_PATTERN)

type InterfaceId = Annotated[str, Field(pattern=INTERFACE_ID_PATTERN)]


def require_interface_id(value: str) -> str:
    """Reject identities that cannot carry a stable namespace and major version."""

    if _INTERFACE_ID.fullmatch(value) is None:
        raise ValueError(
            "instrument interface ids must be namespaced and versioned, "
            "for example 'scopecat.rf_output/v1'"
        )
    return value


__all__ = ["INTERFACE_ID_PATTERN", "InterfaceId", "require_interface_id"]
