"""Stable namespaced identities for versioned public schemas."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field

VERSIONED_SCHEMA_ID_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+/v[1-9][0-9]*$"
_VERSIONED_SCHEMA_ID = re.compile(VERSIONED_SCHEMA_ID_PATTERN)

type VersionedSchemaId = Annotated[str, Field(pattern=VERSIONED_SCHEMA_ID_PATTERN)]


def require_versioned_schema_id(value: str, *, kind: str = "schema") -> str:
    """Reject identities without a stable namespace and major version."""

    if _VERSIONED_SCHEMA_ID.fullmatch(value) is None:
        raise ValueError(
            f"instrument {kind} ids must be namespaced and versioned, "
            "for example 'vendor.device/v1'"
        )
    return value


__all__ = [
    "VERSIONED_SCHEMA_ID_PATTERN",
    "VersionedSchemaId",
    "require_versioned_schema_id",
]
