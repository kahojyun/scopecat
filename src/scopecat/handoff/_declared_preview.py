"""Route-private declared preview metadata for handoff package manifests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scopecat.handoff._contracts import (
    validate_handoff_preview_ready_metadata,
    validate_public_identifier,
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
class HandoffPackagePreviewPlotCandidate:
    x: str
    y: str
    source: str

    def to_manifest(self) -> dict[str, str]:
        return {
            "x": self.x,
            "y": self.y,
            "source": self.source,
        }


@dataclass(frozen=True)
class HandoffPackagePreviewMetadata:
    status: str
    metadata_authority: str
    data_shape_kind: str
    data_shape_axis_order: tuple[str, ...]
    declared_columns: tuple[HandoffPackagePreviewColumn, ...]
    plot_candidates: tuple[HandoffPackagePreviewPlotCandidate, ...]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metadata_authority": self.metadata_authority,
            "data_shape": {
                "kind": self.data_shape_kind,
                "axis_order": list(self.data_shape_axis_order),
            },
            "declared_columns": [column.to_manifest() for column in self.declared_columns],
            "plot_candidates": [candidate.to_manifest() for candidate in self.plot_candidates],
        }


def coerce_handoff_package_preview_metadata(
    source: object,
    *,
    primary_path: str,
    owner: str,
) -> HandoffPackagePreviewMetadata:
    """Normalize caller or manifest-shaped declared preview metadata."""

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
    data_shape = _require_dict(source, "data_shape", owner=owner)
    declared_columns = source.get("declared_columns")
    if not isinstance(declared_columns, list):
        raise ValueError(f"{owner} declared_columns must be a list")
    plot_candidates = source.get("plot_candidates")
    if not isinstance(plot_candidates, list):
        raise ValueError(f"{owner} plot_candidates must be a list")
    axis_order = data_shape.get("axis_order")
    if not isinstance(axis_order, list):
        raise ValueError(f"{owner} data_shape axis_order must be a list")
    return HandoffPackagePreviewMetadata(
        status=_require_text(source, "status", owner=owner),
        metadata_authority=_require_text(source, "metadata_authority", owner=owner),
        data_shape_kind=_require_text(data_shape, "kind", owner=owner),
        data_shape_axis_order=tuple(
            validate_public_identifier(item, f"{owner} data_shape axis") for item in axis_order
        ),
        declared_columns=tuple(_preview_column(column, owner=owner) for column in declared_columns),
        plot_candidates=tuple(
            _preview_plot_candidate(candidate, owner=owner) for candidate in plot_candidates
        ),
    )


def _preview_column(source: Any, *, owner: str) -> HandoffPackagePreviewColumn:
    column = _require_mapping(source, f"{owner} preview column")
    return HandoffPackagePreviewColumn(
        name=_require_text(column, "name", owner=owner),
        role=_require_text(column, "role", owner=owner),
        label=_require_text(column, "label", owner=owner),
        unit=_require_text(column, "unit", owner=owner),
    )


def _preview_plot_candidate(source: Any, *, owner: str) -> HandoffPackagePreviewPlotCandidate:
    candidate = _require_mapping(source, f"{owner} preview plot candidate")
    return HandoffPackagePreviewPlotCandidate(
        x=_require_text(candidate, "x", owner=owner),
        y=_require_text(candidate, "y", owner=owner),
        source=_require_text(candidate, "source", owner=owner),
    )


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_dict(source: dict[str, Any], key: str, *, owner: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{owner} {key} must be an object")
    return value


def _require_text(source: dict[str, Any], key: str, *, owner: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} {key} must be a non-empty string")
    return value
