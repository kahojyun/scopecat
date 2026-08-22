"""Stable instrument interface identities."""

from __future__ import annotations

from scopecat.kernel.schema_identity import (
    VERSIONED_SCHEMA_ID_PATTERN,
    VersionedSchemaId,
    require_versioned_schema_id,
)

INTERFACE_ID_PATTERN = VERSIONED_SCHEMA_ID_PATTERN

type InterfaceId = VersionedSchemaId


def require_interface_id(value: str) -> str:
    """Reject identities that cannot carry a stable namespace and major version."""

    return require_versioned_schema_id(value, kind="interface")


__all__ = ["INTERFACE_ID_PATTERN", "InterfaceId", "require_interface_id"]
