"""Route-private declared table-preview metadata for handoff package manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import (
    validate_handoff_preview_ready_metadata,
)


@dataclass(frozen=True)
class HandoffPackagePreviewColumn:
    name: str
    role: str
    label: str
    unit: str

    def to_manifest(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "label": self.label,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class HandoffPackagePreviewMetadata:
    status: str
    metadata_authority: str
    declared_columns: tuple[HandoffPackagePreviewColumn, ...]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metadata_authority": self.metadata_authority,
            "declared_columns": [column.to_manifest() for column in self.declared_columns],
        }


def coerce_handoff_package_preview_metadata(
    source: object,
    *,
    primary_path: str,
    owner: str,
) -> HandoffPackagePreviewMetadata:
    """Normalize caller or manifest-shaped declared table-preview metadata."""

    if isinstance(source, HandoffPackagePreviewMetadata):
        manifest = source.to_manifest()
        validate_handoff_preview_ready_metadata(
            manifest,
            primary_path=primary_path,
            owner=owner,
        )
        return source
    if not isinstance(source, dict):
        raise ValueError(f"{owner} declared_preview_metadata must be an object")
    validate_handoff_preview_ready_metadata(
        source,
        primary_path=primary_path,
        owner=owner,
    )
    return _preview_metadata_from_manifest(source, owner=owner)


def _preview_metadata_from_manifest(
    source: dict[str, Any],
    *,
    owner: str,
) -> HandoffPackagePreviewMetadata:
    declared_columns = source.get("declared_columns")
    if not isinstance(declared_columns, list):
        raise ValueError(f"{owner} declared_columns must be a list")
    return HandoffPackagePreviewMetadata(
        status=_require_text(source, "status", owner=owner),
        metadata_authority=_require_text(source, "metadata_authority", owner=owner),
        declared_columns=tuple(_preview_column(column, owner=owner) for column in declared_columns),
    )


def _preview_column(source: Any, *, owner: str) -> HandoffPackagePreviewColumn:
    column = _require_mapping(source, f"{owner} preview column")
    return HandoffPackagePreviewColumn(
        name=_require_text(column, "name", owner=owner),
        role=_require_text(column, "role", owner=owner),
        label=_require_text(column, "label", owner=owner),
        unit=_require_text(column, "unit", owner=owner),
    )


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_text(source: dict[str, Any], key: str, *, owner: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} {key} must be a non-empty string")
    return value
