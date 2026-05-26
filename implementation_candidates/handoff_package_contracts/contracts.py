"""Handoff-package route contract helpers.

Most helpers describe route-level contracts already shared by the handoff
writer, contents preview, opener, and composition candidates. Receiving
root/continuity helpers are provisional composition support. All helpers stay
below a durable product schema: callers still own slice-specific policy,
file-system work, and workflow ordering.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts,
    validate_package_primary_data_path,
    validate_positive_integer,
    validate_public_identifier,
    validate_redacted_display_ref,
    validate_relative_path,
    validate_sha256_digest,
    validate_text,
)

MANIFEST_AUTHORITY = "scopecat_export_manifest"
HANDOFF_PACKAGE_CREATED_BY = "scopecat_selected_measurement_export"

PREVIEW_STATUSES = {
    "preview_ready",
    "degraded_preview",
}
PACKAGE_STATES = {
    "packaged",
    "not_packaged_visible_reference",
    "missing_from_package",
    "redacted",
}
INCLUDE_STATUSES = {
    "included_by_default",
    "included_by_user",
    "visible_excluded",
    "missing",
    "redacted",
}
PACKAGE_STATE_INCLUDE_STATUSES = {
    "packaged": {"included_by_default", "included_by_user"},
    "not_packaged_visible_reference": {"visible_excluded"},
    "missing_from_package": {"missing"},
    "redacted": {"redacted"},
}
EXPECTED_PRIMARY_DATA = {
    "kind": "primary_data",
    "include_status": "included_by_default",
    "relation": "selected_measurement_source",
    "authority": MANIFEST_AUTHORITY,
    "format": "csv_table",
    "package_state": "packaged",
    "reason": None,
}
EXPECTED_PRIMARY_BUNDLE = {
    "kind": "primary_data",
    "include_status": "included_by_default",
    "relation": "selected_measurement_source",
    "authority": MANIFEST_AUTHORITY,
    "package_state": "packaged",
    "reason": None,
}

_PRIVATE_PACKAGE_PATH_SEGMENTS = {"Users", "private"}


def _path_same_or_under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _validate_public_package_path(value: str, owner: str) -> None:
    for segment in relative_path_parts(value, owner):
        if segment in _PRIVATE_PACKAGE_PATH_SEGMENTS:
            raise ValueError(f"{owner} path segments must be public-safe")
        try:
            validate_public_identifier(segment, f"{owner} path segment")
        except ValueError as exc:
            raise ValueError(f"{owner} path segments must be public-safe") from exc


def validate_handoff_package_identity(
    identity: dict[str, Any],
    *,
    display_path: str,
) -> None:
    """Validate the managed identity fields shared by handoff-package slices."""
    if display_path not in {"required", "optional", "forbidden"}:
        raise ValueError("display_path mode must be required, optional, or forbidden")

    validate_public_identifier(identity["package_id"], "handoff package package_id")
    validate_text(identity["display_name"], "handoff package display_name")
    if identity["created_by"] != HANDOFF_PACKAGE_CREATED_BY:
        raise ValueError(f"handoff package created_by must be {HANDOFF_PACKAGE_CREATED_BY}")
    validate_public_identifier(
        identity["source_export_summary_id"],
        "handoff package source_export_summary_id",
    )
    if identity["local_path_redacted"] is not True:
        raise ValueError("handoff package local path must stay redacted")

    has_display_path = "display_path" in identity
    if display_path == "required" and not has_display_path:
        raise ValueError("handoff package display_path is required")
    if display_path == "forbidden" and has_display_path:
        raise ValueError("handoff package display_path must not be exported")
    if has_display_path:
        validate_redacted_display_ref(
            identity["display_path"],
            "handoff package display_path",
            prefix="HANDOFF_PACKAGE:",
        )


def validate_package_item_shape(item: dict[str, Any], owner: str) -> None:
    """Validate generic manifest item state, include status, and reason shape."""
    item_id = item.get("item_id", item.get("link_id"))
    if item_id is not None:
        validate_public_identifier(item_id, f"{owner} item_id")
    validate_public_identifier(item["kind"], f"{owner} kind")
    validate_text(item["label"], f"{owner} label")
    validate_public_identifier(item["include_status"], f"{owner} include_status")
    validate_public_identifier(item["relation"], f"{owner} relation")
    if item["include_status"] not in INCLUDE_STATUSES:
        raise ValueError(f"{owner} has unsupported include_status: {item['include_status']}")
    if item["authority"] != MANIFEST_AUTHORITY:
        raise ValueError(f"{owner} authority must stay {MANIFEST_AUTHORITY}")
    if item["package_state"] not in PACKAGE_STATES:
        raise ValueError(f"{owner} has unsupported package_state: {item['package_state']}")
    if item["include_status"] not in PACKAGE_STATE_INCLUDE_STATUSES[item["package_state"]]:
        raise ValueError(f"{owner} include_status must match package_state")

    package_path = item.get("package_path")
    if item["package_state"] == "packaged":
        if not package_path:
            raise ValueError(f"{owner} packaged item requires package_path")
        validate_relative_path(package_path, owner)
        _validate_public_package_path(package_path, owner)
        if "reason" not in item or item["reason"] is not None:
            raise ValueError(f"{owner} packaged item must not carry reason")
        return

    if package_path is not None:
        raise ValueError(f"{owner} non-packaged item must not carry package_path")
    if not item.get("reason"):
        raise ValueError(f"{owner} non-packaged item requires reason")
    validate_text(item["reason"], f"{owner} reason")


def validate_manifest_primary_data(
    primary: dict[str, Any],
    *,
    measurement_record_id: str,
    owner: str,
    digest_size: str,
) -> None:
    """Validate manifest-shaped package primary data for one measurement."""
    if digest_size not in {"optional", "required", "forbidden"}:
        raise ValueError("digest_size mode must be optional, required, or forbidden")

    validate_package_item_shape(primary, owner)
    for key, expected in EXPECTED_PRIMARY_DATA.items():
        if primary.get(key) != expected:
            raise ValueError(f"primary_data {key} must be {expected}")
    validate_package_primary_data_path(
        primary["package_path"],
        measurement_record_id=measurement_record_id,
        owner=f"{owner} package_path",
    )

    has_digest = "digest" in primary
    has_size = "size_bytes" in primary
    if has_digest != has_size:
        raise ValueError(f"{owner} digest and size_bytes must be declared together")
    if digest_size == "required" and not (has_digest and has_size):
        raise ValueError(f"{owner} requires digest and size_bytes")
    if digest_size == "forbidden" and (has_digest or has_size):
        raise ValueError(f"{owner} must not carry digest or size_bytes")
    if has_digest:
        validate_sha256_digest(primary["digest"], f"{owner} digest")
    if has_size:
        validate_positive_integer(primary["size_bytes"], f"{owner} size_bytes")


def validate_primary_bundle_item(
    item: dict[str, Any],
    *,
    measurement_record_id: str,
    primary: dict[str, Any],
    owner: str,
) -> None:
    """Validate the canonical default-bundle entry for primary data."""
    validate_package_item_shape(item, owner)
    expected = {
        **EXPECTED_PRIMARY_BUNDLE,
        "label": primary["label"],
    }
    for key, expected_value in expected.items():
        if item.get(key) != expected_value:
            raise ValueError(f"default bundle primary_data {key} must be {expected_value}")
    if item["item_id"] != f"{measurement_record_id}-primary":
        raise ValueError("primary bundle item_id must match selected measurement")
    if item["package_path"] != primary["package_path"]:
        raise ValueError("primary bundle item path must match primary data path")


def validate_handoff_preview_column(column: dict[str, Any], owner: str) -> None:
    validate_public_identifier(column["name"], f"{owner} name")
    validate_public_identifier(column["role"], f"{owner} role")
    validate_text(column["label"], f"{owner} label")
    validate_public_identifier(column["unit"], f"{owner} unit")


def validate_handoff_preview_ready_metadata(
    preview: dict[str, Any],
    *,
    primary_path: str,
    owner: str,
    shape_kind_owner: str | None = None,
    axis_owner: str | None = None,
) -> set[str]:
    """Validate shared preview-ready metadata and return declared column names."""
    if preview["metadata_authority"] != MANIFEST_AUTHORITY:
        raise ValueError(f"{owner} authority must stay manifest declared")
    if preview["status"] != "preview_ready":
        raise ValueError(f"{owner} requires preview_ready metadata")
    if preview["data_shape"] is None:
        raise ValueError(f"{owner} requires data_shape")
    if not isinstance(preview["data_shape"], dict):
        raise ValueError(f"{owner} data_shape must be an object")
    validate_public_identifier(
        preview["data_shape"]["kind"],
        shape_kind_owner or f"{owner} shape kind",
    )
    if not isinstance(preview["declared_columns"], list):
        raise ValueError(f"{owner} declared columns must be a list")
    for column in preview["declared_columns"]:
        if not isinstance(column, dict):
            raise ValueError(f"{owner} column must be an object")
        validate_handoff_preview_column(column, f"{owner} column")
    declared_names = [column["name"] for column in preview["declared_columns"]]
    if not declared_names or len(set(declared_names)) != len(declared_names):
        raise ValueError(f"{owner} declared columns must have unique names")
    declared_name_set = set(declared_names)
    axis_order = preview["data_shape"]["axis_order"]
    if not isinstance(axis_order, list):
        raise ValueError(f"{owner} axis order must be a list")
    for axis in axis_order:
        validate_public_identifier(axis, axis_owner or f"{owner} axis_order entry")
    if not axis_order or any(axis not in declared_name_set for axis in axis_order):
        raise ValueError(f"{owner} axis order must reference declared columns")
    if not isinstance(preview["plot_candidates"], list):
        raise ValueError(f"{owner} plot candidates must be a list")
    for candidate in preview["plot_candidates"]:
        if not isinstance(candidate, dict):
            raise ValueError(f"{owner} plot candidate must be an object")
        validate_public_identifier(candidate["x"], f"{owner} plot x")
        validate_public_identifier(candidate["y"], f"{owner} plot y")
        if candidate["source"] != primary_path:
            raise ValueError(f"{owner} plot candidate source must match primary data")
        if candidate["x"] not in declared_name_set or candidate["y"] not in declared_name_set:
            raise ValueError(f"{owner} plot candidate axes must reference declared columns")
    return declared_name_set


def validate_handoff_receiving_roots(
    *,
    package_dir: Path,
    storage_root: Path,
    artifact_output_dir: Path,
    artifact_output_filenames: tuple[str, ...] = (),
    allow_existing_artifact_targets: bool = False,
) -> None:
    """Validate receiving-workflow root separation before local writes."""

    if package_dir.is_symlink():
        raise ValueError("package root must not be a symlink")
    if storage_root.is_symlink():
        raise ValueError("storage root must not be a symlink")
    if artifact_output_dir.is_symlink():
        raise ValueError("artifact output must not be a symlink")
    if not package_dir.is_dir():
        raise ValueError("package root must be an existing directory")
    if not storage_root.is_dir():
        raise ValueError("storage root must be an existing directory")

    package_root = package_dir.resolve()
    storage_root = storage_root.resolve()
    artifact_root = artifact_output_dir.resolve(strict=False)
    if _path_same_or_under(storage_root, package_root) or _path_same_or_under(
        package_root,
        storage_root,
    ):
        raise ValueError("package root and storage root must be separate")
    if _path_same_or_under(artifact_root, package_root):
        raise ValueError("artifact output must be outside the package tree")
    if _path_same_or_under(artifact_root, storage_root):
        raise ValueError("artifact output must be outside the storage root")
    for filename in artifact_output_filenames:
        validate_public_identifier(filename, "artifact output filename")
        artifact_target = artifact_output_dir / filename
        if artifact_target.is_symlink():
            raise ValueError("artifact output target must not be a symlink")
        if os.path.lexists(artifact_target) and not allow_existing_artifact_targets:
            raise ValueError("artifact output target must not already exist")
        target_root = artifact_target.resolve(strict=False)
        if _path_same_or_under(target_root, package_root):
            raise ValueError("artifact output target must be outside the package tree")
        if _path_same_or_under(target_root, storage_root):
            raise ValueError("artifact output target must be outside the storage root")


def validate_handoff_reviewed_package_continuity(
    *,
    reviewed_package_id: str,
    reviewed_preview_classification: str,
    reviewed_integrity_classification: str,
    inspected_package: dict[str, Any],
    integrity_package: dict[str, Any],
    integrity_classification: str,
) -> None:
    """Validate reviewed package facts against composed receiving observations."""

    validate_public_identifier(reviewed_package_id, "reviewed_package_id")
    validate_public_identifier(
        reviewed_preview_classification,
        "reviewed_preview_classification",
    )
    validate_public_identifier(
        reviewed_integrity_classification,
        "reviewed_integrity_classification",
    )
    if reviewed_package_id != inspected_package["package_id"]:
        raise ValueError("reviewed package id must match inspected package")
    if reviewed_package_id != integrity_package["package_id"]:
        raise ValueError("reviewed package id must match integrity-observed package")
    if reviewed_preview_classification != inspected_package["preview_classification"]:
        raise ValueError("reviewed preview classification must match inspection")
    if reviewed_preview_classification != integrity_package["preview_classification"]:
        raise ValueError("reviewed preview classification must match integrity observation")
    if reviewed_integrity_classification != integrity_classification:
        raise ValueError("reviewed integrity classification must match observation")
