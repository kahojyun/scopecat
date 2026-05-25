"""Minimal handoff package writer implementation candidate.

This module writes a directory-shaped handoff package under a caller-provided
package root. It copies only explicitly declared primary data from a
caller-provided storage root, writes a deterministic package manifest, and
keeps linked context reference-only. It deliberately does not create archives,
accept packages, infer schemas, traverse relations, mutate measurement storage,
or define GUI behavior.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts as _relative_parts,
)
from implementation_candidates.contract_primitives import (
    validate_non_negative_integer as _validate_non_negative_integer,
)
from implementation_candidates.contract_primitives import (
    validate_package_primary_data_path,
    validate_positive_integer,
    validate_sha256_digest,
    validate_unique_reference_targets,
)
from implementation_candidates.contract_primitives import (
    validate_package_root_outside_storage as _validate_package_root_outside_storage,
)
from implementation_candidates.contract_primitives import (
    validate_public_identifier as _validate_public_identifier,
)
from implementation_candidates.contract_primitives import (
    validate_redacted_display_ref as _validate_redacted_display_ref,
)
from implementation_candidates.contract_primitives import (
    validate_relative_path as _validate_relative_path,
)
from implementation_candidates.contract_primitives import (
    validate_strict_child_path as _validate_strict_child_path,
)
from implementation_candidates.contract_primitives import (
    validate_text as _validate_text,
)
from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_handoff_package_write_request",
    "source_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "destination_authority": "caller_provided_package_root_plus_declared_package_paths",
    "package_format": "directory_manifest",
    "overwrite_behavior": "no_overwrite",
    "checksum_algorithm": "sha256",
    "primary_data_materialization": "copy_declared_primary_data",
    "linked_context_materialization": "reference_only",
    "archive_creation": "not_performed",
    "package_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_EXPECTED_PREVIEW_POLICY = {
    "preview_authority": "scopecat_export_manifest_only",
    "archive_extraction": "not_performed",
    "file_observation": "not_performed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "package_integrity": "not_claimed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_MANIFEST_AUTHORITY = "scopecat_export_manifest"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _open_dir_fd(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def _remove_created_dirs(root: Path, created_dirs: list[str]) -> None:
    for relative_path in reversed(created_dirs):
        try:
            _path_under(root, relative_path).rmdir()
        except OSError:
            pass


def _open_parent_dir_fd(root: Path, relative_path: str, *, create: bool) -> tuple[int, list[str]]:
    root_fd = _open_dir_fd(root)
    current_fd = root_fd
    current_parts: list[str] = []
    created_dirs: list[str] = []
    try:
        for part in _relative_parts(relative_path)[:-1]:
            current_parts.append(part)
            if create:
                try:
                    os.mkdir(part, dir_fd=current_fd)
                    created_dirs.append("/".join(current_parts))
                except FileExistsError:
                    pass
            next_fd = _open_dir_fd(part, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        if current_fd == root_fd:
            return root_fd, created_dirs
        os.close(root_fd)
        return current_fd, created_dirs
    except Exception:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        if create:
            _remove_created_dirs(root, created_dirs)
        raise


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = _relative_parts(left)
    right_parts = _relative_parts(right)
    return (
        left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
    )


def _existing_root(root: Path, label: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"handoff package writer {label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"handoff package writer {label} root must be an existing directory")
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"handoff package writer {label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"handoff package writer {label} parent is not a directory")


def _target_exists(root: Path, relative_path: str) -> bool:
    target = _path_under(root, relative_path)
    return target.exists() or target.is_symlink()


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["package_write_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("handoff package writer policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"handoff package writer policy {key} must be {expected}")


def _validate_write_request(source: dict[str, Any]) -> None:
    request = source["package_write_request"]
    if request["approval_state"] != "approved":
        raise ValueError("handoff package write request must be approved")
    if request["collision_policy"] != "no_overwrite":
        raise ValueError("handoff package writer collision_policy must be no_overwrite")
    expected_package_dir = source["package_identity"]["package_id"]
    expected_manifest_path = f"{expected_package_dir}/package-manifest.json"
    for field in ("package_dir", "manifest_path"):
        _validate_relative_path(request[field], f"handoff package {field}")
    if request["package_dir"] != expected_package_dir:
        raise ValueError("handoff package package_dir must match package_id")
    if request["manifest_path"] != expected_manifest_path:
        raise ValueError("handoff package manifest_path must be package_id/package-manifest.json")
    _validate_strict_child_path(
        request["manifest_path"],
        request["package_dir"],
        "handoff package manifest_path",
    )
    _validate_public_identifier(request["request_id"], "handoff package request_id")


def _validate_package_identity(source: dict[str, Any]) -> None:
    identity = source["package_identity"]
    _validate_public_identifier(identity["package_id"], "handoff package package_id")
    _validate_text(identity["display_name"], "handoff package display_name")
    if identity["created_by"] != "scopecat_selected_measurement_export":
        raise ValueError("handoff package created_by must be scopecat_selected_measurement_export")
    _validate_public_identifier(
        identity["source_export_summary_id"],
        "handoff package source_export_summary_id",
    )
    _validate_redacted_display_ref(
        identity["display_path"],
        "handoff package display_path",
        prefix="HANDOFF_PACKAGE:",
    )
    if identity["local_path_redacted"] is not True:
        raise ValueError("handoff package local path must stay redacted")


def _validate_preview_metadata(record: dict[str, Any]) -> None:
    preview = record["declared_preview_metadata"]
    primary_path = record["primary_data"]["package_path"]
    if preview["metadata_authority"] != _MANIFEST_AUTHORITY:
        raise ValueError("handoff package preview authority must stay manifest declared")
    if preview["status"] != "preview_ready":
        raise ValueError("handoff package writer currently requires preview_ready metadata")
    _validate_public_identifier(preview["data_shape"]["kind"], "handoff package data_shape kind")
    declared_names = [column["name"] for column in preview["declared_columns"]]
    if not declared_names or len(set(declared_names)) != len(declared_names):
        raise ValueError("handoff package preview declared columns must be present and unique")
    for column in preview["declared_columns"]:
        _validate_public_identifier(column["name"], "handoff package column name")
        _validate_public_identifier(column["role"], "handoff package column role")
        _validate_text(column["label"], "handoff package column label")
        _validate_public_identifier(column["unit"], "handoff package column unit")
    declared_name_set = set(declared_names)
    axis_order = preview["data_shape"]["axis_order"]
    for axis in axis_order:
        _validate_public_identifier(axis, "handoff package axis_order entry")
    if not axis_order or any(axis not in declared_name_set for axis in axis_order):
        raise ValueError("handoff package preview axis order must reference declared columns")
    for candidate in preview["plot_candidates"]:
        _validate_public_identifier(candidate["x"], "handoff package plot x")
        _validate_public_identifier(candidate["y"], "handoff package plot y")
        if candidate["source"] != primary_path:
            raise ValueError("handoff package plot candidate source must match primary data")
        if candidate["x"] not in declared_name_set or candidate["y"] not in declared_name_set:
            raise ValueError("handoff package plot candidate axes must reference declared columns")


def _validate_primary_data(record: dict[str, Any]) -> None:
    measurement_id = record["measurement_record_id"]
    _validate_public_identifier(measurement_id, "measurement_record_id")
    _validate_non_negative_integer(record["legacy_data_id"], "measurement legacy_data_id")
    _validate_text(record["label"], "measurement label")
    _validate_public_identifier(record["experiment_type"], "measurement experiment_type")
    _validate_public_identifier(record["target"], "measurement target")

    primary = record["primary_data"]
    expected = {
        "kind": "primary_data",
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": _MANIFEST_AUTHORITY,
        "format": "csv_table",
        "package_state": "packaged",
        "reason": None,
    }
    for key, value in expected.items():
        if primary[key] != value:
            raise ValueError(f"handoff package primary_data {key} must be {value}")
    _validate_text(primary["label"], "handoff package primary_data label")
    _validate_relative_path(primary["source_path"], "handoff package primary_data source_path")
    validate_package_primary_data_path(
        primary["package_path"],
        measurement_record_id=measurement_id,
        owner="handoff package primary_data package_path",
    )
    validate_sha256_digest(
        primary["expected_digest"],
        "handoff package primary_data expected_digest",
    )
    validate_positive_integer(
        primary["expected_size_bytes"],
        "handoff package primary_data expected_size_bytes",
    )


def _validate_default_bundle(record: dict[str, Any]) -> None:
    bundle = record["default_bundle"]
    if len(bundle) != 1:
        raise ValueError("handoff package writer currently writes one primary bundle item")
    item = bundle[0]
    primary = record["primary_data"]
    expected = {
        "item_id": f"{record['measurement_record_id']}-primary",
        "kind": "primary_data",
        "label": primary["label"],
        "package_path": primary["package_path"],
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": _MANIFEST_AUTHORITY,
        "package_state": "packaged",
        "reason": None,
    }
    for key, value in expected.items():
        if item[key] != value:
            raise ValueError("handoff package default bundle must match primary data")


def _validate_selected_measurements(source: dict[str, Any]) -> None:
    if not source["selected_measurements"]:
        raise ValueError("handoff package writer requires selected_measurements")
    seen_ids = set()
    seen_paths = set()
    for record in source["selected_measurements"]:
        _validate_primary_data(record)
        measurement_id = record["measurement_record_id"]
        if measurement_id in seen_ids:
            raise ValueError(f"duplicate measurement_record_id: {measurement_id}")
        seen_ids.add(measurement_id)
        _validate_preview_metadata(record)
        _validate_default_bundle(record)
        package_path = record["primary_data"]["package_path"]
        if package_path in seen_paths:
            raise ValueError(f"duplicate package_path: {package_path}")
        seen_paths.add(package_path)


def _validate_linked_context(source: dict[str, Any]) -> None:
    selected_ids = {record["measurement_record_id"] for record in source["selected_measurements"]}
    seen_ids = set()
    for item in source["linked_context"]:
        link_id = item["link_id"]
        _validate_public_identifier(link_id, "linked context link_id")
        if link_id in seen_ids:
            raise ValueError(f"duplicate linked context id: {link_id}")
        seen_ids.add(link_id)
        _validate_public_identifier(item["kind"], f"linked context {link_id} kind")
        _validate_text(item["label"], f"linked context {link_id} label")
        _validate_public_identifier(item["relation"], f"linked context {link_id} relation")
        if item["package_path"] is not None:
            raise ValueError("handoff package writer keeps linked context reference-only")
        if item["include_status"] != "visible_excluded":
            raise ValueError(
                "handoff package linked context include_status must stay visible_excluded"
            )
        if item["authority"] != _MANIFEST_AUTHORITY:
            raise ValueError("handoff package linked context authority must stay manifest declared")
        if item["package_state"] != "not_packaged_visible_reference":
            raise ValueError("handoff package writer keeps linked context reference-only")
        _validate_text(item["reason"], "handoff package linked context reason")
        validate_unique_reference_targets(
            item["linked_measurement_record_ids"],
            selected_ids=selected_ids,
            owner="handoff package linked context",
        )


def _actual_package_path(source: dict[str, Any], package_path: str) -> str:
    return f"{source['package_write_request']['package_dir']}/{package_path}"


def _validate_destination_topology(source: dict[str, Any]) -> None:
    output_paths = [source["package_write_request"]["manifest_path"]]
    output_paths.extend(
        _actual_package_path(source, record["primary_data"]["package_path"])
        for record in source["selected_measurements"]
    )
    for index, path in enumerate(output_paths):
        for other in output_paths[index + 1 :]:
            if path == other:
                raise ValueError(f"duplicate package output path: {path}")
            if _paths_overlap(path, other):
                raise ValueError(f"overlapping package output path: {path}")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_package_identity(source)
    _validate_write_request(source)
    _validate_selected_measurements(source)
    _validate_linked_context(source)
    _validate_destination_topology(source)


def _read_source_file(storage_root: Path, record: dict[str, Any]) -> bytes:
    primary = record["primary_data"]
    source_path = primary["source_path"]
    _ensure_no_symlink_parents(storage_root, source_path, "source")
    try:
        parent_fd, _created_dirs = _open_parent_dir_fd(storage_root, source_path, create=False)
    except OSError as exc:
        raise ValueError("handoff package source file is unavailable") from exc
    try:
        try:
            file_fd = os.open(
                _relative_parts(source_path)[-1], os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd
            )
        except FileNotFoundError as exc:
            raise ValueError("handoff package source file is unavailable") from exc
        except OSError as exc:
            raise ValueError("handoff package source file is unavailable") from exc
        with os.fdopen(file_fd, "rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("handoff package source file is unavailable")
            if source_stat.st_size != primary["expected_size_bytes"]:
                raise ValueError("handoff package source size does not match")
            content = handle.read()
    finally:
        os.close(parent_fd)
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != primary["expected_digest"]:
        raise ValueError("handoff package source digest does not match")
    if len(content) != primary["expected_size_bytes"]:
        raise ValueError("handoff package source size does not match")
    return content


def _preflight_sources(
    source: dict[str, Any],
    storage_root: Path,
) -> list[tuple[dict[str, Any], bytes]]:
    return [
        (record, _read_source_file(storage_root, record))
        for record in source["selected_measurements"]
    ]


def _ensure_new_targets(source: dict[str, Any], package_root: Path) -> None:
    request = source["package_write_request"]
    if _target_exists(package_root, request["package_dir"]):
        raise ValueError("handoff package target already exists")
    for path in [request["manifest_path"]] + [
        _actual_package_path(source, record["primary_data"]["package_path"])
        for record in source["selected_measurements"]
    ]:
        if _target_exists(package_root, path):
            raise ValueError("handoff package target already exists")
        _ensure_no_symlink_parents(package_root, path, "target")


def _write_new_file(package_root: Path, relative_path: str, content: bytes) -> list[str]:
    _ensure_no_symlink_parents(package_root, relative_path, "target")
    parent_fd: int | None = None
    created_dirs: list[str] = []
    created_file = False
    try:
        parent_fd, created_dirs = _open_parent_dir_fd(package_root, relative_path, create=True)
        file_fd = os.open(
            _relative_parts(relative_path)[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o666,
            dir_fd=parent_fd,
        )
        created_file = True
        with os.fdopen(file_fd, "wb") as handle:
            handle.write(content)
    except Exception:
        if created_file:
            try:
                _path_under(package_root, relative_path).unlink()
            except FileNotFoundError:
                pass
        _remove_created_dirs(package_root, created_dirs)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    return created_dirs


def _rollback_written_files(
    package_root: Path, written_paths: list[str], created_dirs: list[str]
) -> None:
    for relative_path in reversed(written_paths):
        try:
            _path_under(package_root, relative_path).unlink()
        except FileNotFoundError:
            pass
    _remove_created_dirs(package_root, created_dirs)


def _manifest_measurement(record: dict[str, Any], digest: str, size: int) -> dict[str, Any]:
    primary = record["primary_data"]
    return {
        "measurement_record_id": record["measurement_record_id"],
        "legacy_data_id": record["legacy_data_id"],
        "label": record["label"],
        "experiment_type": record["experiment_type"],
        "target": record["target"],
        "primary_data": {
            "kind": primary["kind"],
            "label": primary["label"],
            "package_path": primary["package_path"],
            "include_status": primary["include_status"],
            "relation": primary["relation"],
            "authority": primary["authority"],
            "format": primary["format"],
            "package_state": primary["package_state"],
            "reason": primary["reason"],
            "digest": digest,
            "size_bytes": size,
        },
        "declared_preview_metadata": _manifest_preview_metadata(
            record["declared_preview_metadata"]
        ),
        "default_bundle": [_manifest_default_bundle_item(record["default_bundle"][0])],
    }


def _manifest_preview_metadata(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": preview["status"],
        "metadata_authority": preview["metadata_authority"],
        "data_shape": {
            "kind": preview["data_shape"]["kind"],
            "axis_order": list(preview["data_shape"]["axis_order"]),
        },
        "declared_columns": [
            {
                "name": column["name"],
                "role": column["role"],
                "label": column["label"],
                "unit": column["unit"],
            }
            for column in preview["declared_columns"]
        ],
        "plot_candidates": [
            {
                "x": candidate["x"],
                "y": candidate["y"],
                "source": candidate["source"],
            }
            for candidate in preview["plot_candidates"]
        ],
    }


def _manifest_default_bundle_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "kind": item["kind"],
        "label": item["label"],
        "package_path": item["package_path"],
        "include_status": item["include_status"],
        "relation": item["relation"],
        "authority": item["authority"],
        "package_state": item["package_state"],
        "reason": item["reason"],
    }


def _manifest_linked_context(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "link_id": item["link_id"],
        "kind": item["kind"],
        "label": item["label"],
        "package_path": item["package_path"],
        "include_status": item["include_status"],
        "relation": item["relation"],
        "authority": item["authority"],
        "package_state": item["package_state"],
        "reason": item["reason"],
        "linked_measurement_record_ids": list(item["linked_measurement_record_ids"]),
    }


def _manifest_bytes(
    source: dict[str, Any],
    copied_sources: list[tuple[dict[str, Any], bytes]],
) -> bytes:
    digest_by_id = {
        record["measurement_record_id"]: f"sha256:{hashlib.sha256(content).hexdigest()}"
        for record, content in copied_sources
    }
    size_by_id = {
        record["measurement_record_id"]: len(content) for record, content in copied_sources
    }
    manifest = {
        "package_preview_policy": copy.deepcopy(_EXPECTED_PREVIEW_POLICY),
        "package_identity": {
            "package_id": source["package_identity"]["package_id"],
            "display_name": source["package_identity"]["display_name"],
            "created_by": source["package_identity"]["created_by"],
            "source_export_summary_id": source["package_identity"]["source_export_summary_id"],
            "local_path_redacted": source["package_identity"]["local_path_redacted"],
        },
        "selected_measurements": [
            _manifest_measurement(
                record,
                digest_by_id[record["measurement_record_id"]],
                size_by_id[record["measurement_record_id"]],
            )
            for record in source["selected_measurements"]
        ],
        "linked_context": [_manifest_linked_context(item) for item in source["linked_context"]],
    }
    build_handoff_package_contents_preview_summary(manifest)
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _package_contents(source: dict[str, Any]) -> list[dict[str, Any]]:
    contents = []
    for record in source["selected_measurements"]:
        item = record["default_bundle"][0]
        contents.append(
            {
                "owner_type": "selected_measurement",
                "owner_id": record["measurement_record_id"],
                "item_id": item["item_id"],
                "kind": item["kind"],
                "label": item["label"],
                "package_path": item["package_path"],
                "include_status": item["include_status"],
                "relation": item["relation"],
                "authority": item["authority"],
                "package_state": item["package_state"],
                "reason": item["reason"],
            }
        )
    for item in source["linked_context"]:
        contents.append(
            {
                "owner_type": "linked_context",
                "owner_id": item["link_id"],
                "item_id": item["link_id"],
                "kind": item["kind"],
                "label": item["label"],
                "package_path": item["package_path"],
                "include_status": item["include_status"],
                "relation": item["relation"],
                "authority": item["authority"],
                "package_state": item["package_state"],
                "reason": item["reason"],
            }
        )
    return contents


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "handoff_package_written",
            "severity": "review",
            "basis": "Approved fixture input wrote a directory-shaped handoff package.",
            "does_not_claim": "package_acceptance_or_import_readiness",
        },
        {
            "code": "primary_data_copied",
            "severity": "info",
            "basis": "Declared primary data sha256 and size facts are checked before copying.",
            "does_not_claim": "schema_or_scientific_validity",
        },
        {
            "code": "linked_context_reference_only",
            "severity": "review",
            "basis": "Linked context remains visible reference-only; payloads are not packaged.",
            "does_not_claim": "recursive_relation_traversal_or_context_capture",
        },
        {
            "code": "archive_creation_not_performed",
            "severity": "review",
            "basis": "The writer creates a package directory and manifest but no archive.",
            "does_not_claim": "zip_or_archive_package_format",
        },
    ]


def write_handoff_package(
    source: dict[str, Any],
    *,
    storage_root: Path,
    package_root: Path,
) -> dict[str, Any]:
    """Write a minimal handoff package under a caller-provided package root."""
    _validate_references(source)
    storage_root_resolved = _existing_root(storage_root, "storage")
    package_root_resolved = _existing_root(package_root, "package")
    _validate_package_root_outside_storage(
        storage_root_resolved,
        package_root_resolved,
        owner="handoff package writer",
    )
    copied_sources = _preflight_sources(source, storage_root_resolved)
    _ensure_new_targets(source, package_root_resolved)

    request = source["package_write_request"]
    manifest_content = _manifest_bytes(source, copied_sources)
    manifest_digest = f"sha256:{hashlib.sha256(manifest_content).hexdigest()}"

    written_paths: list[str] = []
    created_dirs: list[str] = []
    try:
        for record, content in copied_sources:
            package_path = _actual_package_path(source, record["primary_data"]["package_path"])
            created_dirs.extend(_write_new_file(package_root_resolved, package_path, content))
            written_paths.append(package_path)
        created_dirs.extend(
            _write_new_file(package_root_resolved, request["manifest_path"], manifest_content)
        )
        written_paths.append(request["manifest_path"])
    except Exception:
        _rollback_written_files(package_root_resolved, written_paths, created_dirs)
        raise

    copied_by_id = {record["measurement_record_id"]: content for record, content in copied_sources}
    return {
        "artifact_posture": "local_write_receipt",
        "package_write_policy": copy.deepcopy(source["package_write_policy"]),
        "package": {
            "package_id": source["package_identity"]["package_id"],
            "display_name": source["package_identity"]["display_name"],
            "created_by": source["package_identity"]["created_by"],
            "source_export_summary_id": source["package_identity"]["source_export_summary_id"],
            "display_path": source["package_identity"]["display_path"],
            "classification": "package_written_ready_for_transfer_review",
        },
        "write_request": {
            "request_id": request["request_id"],
            "approval_state": request["approval_state"],
            "package_dir": request["package_dir"],
            "manifest_path": request["manifest_path"],
            "collision_policy": request["collision_policy"],
        },
        "selected_measurements": [
            {
                "measurement_record_id": record["measurement_record_id"],
                "legacy_data_id": record["legacy_data_id"],
                "label": record["label"],
                "experiment_type": record["experiment_type"],
                "target": record["target"],
                "source_path": record["primary_data"]["source_path"],
                "primary_data": {
                    "package_path": record["primary_data"]["package_path"],
                    "digest": f"sha256:{hashlib.sha256(copied_by_id[record['measurement_record_id']]).hexdigest()}",
                    "size_bytes": len(copied_by_id[record["measurement_record_id"]]),
                    "format": record["primary_data"]["format"],
                },
                "classification": "primary_data_packaged",
            }
            for record in source["selected_measurements"]
        ],
        "package_contents": _package_contents(source),
        "write_results": [
            {
                "path": _actual_package_path(source, record["primary_data"]["package_path"]),
                "kind": "primary_data",
                "result": "written",
                "bytes_written": len(copied_by_id[record["measurement_record_id"]]),
                "digest": f"sha256:{hashlib.sha256(copied_by_id[record['measurement_record_id']]).hexdigest()}",
                "does_not_claim": "schema_or_scientific_validity",
            }
            for record in source["selected_measurements"]
        ]
        + [
            {
                "path": request["manifest_path"],
                "kind": "package_manifest",
                "result": "written",
                "bytes_written": len(manifest_content),
                "digest": manifest_digest,
                "does_not_claim": "package_acceptance_or_archive_integrity",
            }
        ],
        "attention": _attention(),
    }
