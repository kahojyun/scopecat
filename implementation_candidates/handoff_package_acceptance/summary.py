"""Approved receiving-side acceptance for directory-shaped handoff packages.

This candidate starts after read-only package inspection. It copies reviewed
package primary data into new local record directories and writes local record
manifests. The returned receipt is local review data, not a portable package
member.
"""

from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts,
    validate_public_identifier,
    validate_relative_path,
)
from implementation_candidates.filesystem_mutation import (
    ensure_no_symlink_parents,
    existing_directory_root,
    target_exists,
    write_new_files_transaction,
)
from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    MeasurementReadView,
    open_handoff_package_view,
)

_EXPECTED_SCHEMA = "scopecat.handoff_package_acceptance.v0"
_EXPECTED_POLICY = {
    "acceptance_authority": "approved_handoff_package_acceptance_request",
    "package_authority": "directory_shaped_handoff_package",
    "package_open": "read_only_declared_preview",
    "storage_mutation": "copy_package_primary_data_and_write_record_manifests",
    "copy_behavior": "copy_into_new_records",
    "linked_context_materialization": "reference_only",
    "overwrite_behavior": "no_overwrite",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "checksum_validation": "not_performed",
    "package_root_concurrency": "not_supported",
    "schema_inference": "not_performed",
    "dataframe_adapter": "not_defined",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    actual_keys = set(value)
    if actual_keys != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _path_same_or_under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _validate_separate_roots(package_root: Path, storage_root: Path) -> None:
    if _path_same_or_under(storage_root, package_root) or _path_same_or_under(
        package_root,
        storage_root,
    ):
        raise ValueError("package root and storage root must be separate")


def _read_package_file(package_root: Path, relative_path: str) -> bytes:
    validate_relative_path(relative_path, "package primary data")
    ensure_no_symlink_parents(package_root, relative_path, "package primary data")
    target = package_root.joinpath(*relative_path_parts(relative_path))
    if target.is_symlink():
        raise ValueError("package primary data must not be a symlink")
    try:
        file_stat = target.stat()
    except FileNotFoundError as exc:
        raise ValueError("package primary data is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("package primary data must be a regular file")
    return target.read_bytes()


def _load_package_manifest(package_root: Path) -> dict[str, Any]:
    manifest = json.loads((package_root / "package-manifest.json").read_text(encoding="utf-8"))
    return _require_mapping(manifest, "package manifest")


def _validate_policy(source: dict[str, Any]) -> None:
    _require_keys(
        source,
        {"acceptance_schema", "acceptance_policy", "acceptance_request"},
        "handoff package acceptance source",
    )
    if source.get("acceptance_schema") != _EXPECTED_SCHEMA:
        raise ValueError("acceptance_schema is unsupported")
    if source.get("acceptance_policy") != _EXPECTED_POLICY:
        raise ValueError("acceptance_policy is unsupported")


def _validate_review(request: dict[str, Any], read_view: HandoffPackageReadView) -> None:
    review = _require_mapping(request.get("review"), "acceptance review")
    _require_keys(
        review,
        {"approval_state", "reviewed_package_id", "reviewed_preview_classification"},
        "acceptance review",
    )
    if review.get("approval_state") != "approved":
        raise ValueError("handoff package acceptance requires approved review")
    if review.get("reviewed_package_id") != read_view.package_id:
        raise ValueError("reviewed package id must match opened package")
    if review.get("reviewed_preview_classification") != read_view.preview_classification:
        raise ValueError("reviewed preview classification must match opened package")


def _validate_destination(request: dict[str, Any]) -> None:
    destination = _require_mapping(request.get("destination"), "acceptance destination")
    _require_keys(
        destination,
        {"path_kind", "collision_policy"},
        "acceptance destination",
    )
    if destination.get("path_kind") != "relative_storage_path_under_caller_root":
        raise ValueError("acceptance destination path_kind is unsupported")
    if destination.get("collision_policy") != "no_overwrite":
        raise ValueError("acceptance destination collision_policy is unsupported")

    materialization = _require_mapping(request.get("materialization"), "acceptance materialization")
    _require_keys(
        materialization,
        {"selected_measurements", "linked_context", "source_package_identity"},
        "acceptance materialization",
    )
    if materialization.get("selected_measurements") != "copy_primary_data_into_storage":
        raise ValueError("selected measurement materialization is unsupported")
    if materialization.get("linked_context") != "reference_only":
        raise ValueError("linked context materialization is unsupported")
    if materialization.get("source_package_identity") != "preserve_package_reference":
        raise ValueError("source package identity materialization is unsupported")


def _validate_selected_measurements(
    request: dict[str, Any],
    read_view: HandoffPackageReadView,
) -> list[dict[str, str]]:
    selected = request.get("selected_measurements")
    if not isinstance(selected, list) or not selected:
        raise ValueError("selected_measurements must be a non-empty list")

    package_ids = set(read_view.measurement_ids)
    seen_ids: set[str] = set()
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(selected):
        entry = _require_mapping(item, f"selected_measurements[{index}]")
        _require_keys(
            entry,
            {"measurement_record_id", "record_dir", "primary_data_path", "manifest_path"},
            f"selected_measurements[{index}]",
        )
        measurement_id = validate_public_identifier(
            entry.get("measurement_record_id"),
            f"selected_measurements[{index}].measurement_record_id",
        )
        if measurement_id in seen_ids:
            raise ValueError("selected measurements must be unique")
        if measurement_id not in package_ids:
            raise ValueError("selected measurement must exist in opened package")

        record_dir = validate_relative_path(
            entry.get("record_dir"),
            f"selected_measurements[{index}].record_dir",
        )
        primary_data_path = validate_relative_path(
            entry.get("primary_data_path"),
            f"selected_measurements[{index}].primary_data_path",
        )
        manifest_path = validate_relative_path(
            entry.get("manifest_path"),
            f"selected_measurements[{index}].manifest_path",
        )

        expected_record_dir = f"records/{measurement_id}"
        expected_primary = f"{expected_record_dir}/primary.csv"
        expected_manifest = f"{expected_record_dir}/record-manifest.json"
        if record_dir != expected_record_dir:
            raise ValueError(f"record_dir must be {expected_record_dir}")
        if primary_data_path != expected_primary:
            raise ValueError(f"primary_data_path must be {expected_primary}")
        if manifest_path != expected_manifest:
            raise ValueError(f"manifest_path must be {expected_manifest}")

        seen_ids.add(measurement_id)
        normalized.append(
            {
                "measurement_record_id": measurement_id,
                "record_dir": record_dir,
                "primary_data_path": primary_data_path,
                "manifest_path": manifest_path,
            }
        )

    if seen_ids != package_ids:
        raise ValueError("handoff package acceptance must select every package measurement")
    return normalized


def _plot_series_manifest(measurement: MeasurementReadView) -> list[dict[str, Any]]:
    return [
        {
            "source": series.source,
            "x": series.x_name,
            "y": series.y_name,
            "point_count": len(series.points),
        }
        for series in measurement.plot_series()
    ]


def _record_manifest(
    *,
    request_id: str,
    read_view: HandoffPackageReadView,
    measurement: MeasurementReadView,
    destination: dict[str, str],
    primary_content: bytes,
    linked_context: list[dict[str, Any]],
) -> dict[str, Any]:
    digest = "sha256:" + hashlib.sha256(primary_content).hexdigest()
    primary_table = measurement.primary_table()
    preview_table = measurement.preview_table()
    return {
        "manifest_schema": "scopecat.accepted_handoff_measurement_record.v0",
        "measurement_record_id": measurement.measurement_record_id,
        "label": measurement.label,
        "experiment_type": measurement.experiment_type,
        "target": measurement.target,
        "source": {
            "kind": "handoff_package_acceptance",
            "acceptance_request_id": request_id,
            "package_id": read_view.package_id,
            "package_display_name": read_view.display_name,
            "package_primary_path": measurement.primary_package_path,
            "package_integrity_check": measurement.integrity_check,
        },
        "primary_data": {
            "path": destination["primary_data_path"],
            "format": "csv_table",
            "digest": digest,
            "size_bytes": len(primary_content),
            "package_checksum_validation": "not_performed",
        },
        "declared_preview": {
            "metadata_authority": "handoff_package_manifest",
            "declared_columns": list(measurement.declared_preview_columns),
            "primary_row_count": primary_table.row_count,
            "preview_row_count": preview_table.row_count,
            "plot_series": _plot_series_manifest(measurement),
        },
        "linked_context": linked_context,
        "acceptance": {
            "approval_state": "approved",
            "selected_measurement_materialization": "copy_primary_data_into_storage",
            "linked_context_materialization": "reference_only",
        },
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "handoff_package_accepted_into_local_storage",
            "severity": "info",
            "basis": "The package was reopened read-only after explicit approval and selected primary data was copied into new local record paths.",
            "does_not_claim": "stable_import_api_or_final_storage_schema",
        },
        {
            "code": "linked_context_preserved_reference_only",
            "severity": "review",
            "basis": "Linked context facts are copied into local manifests as references; payloads are not recursively imported.",
            "does_not_claim": "complete_context_materialization",
        },
        {
            "code": "package_integrity_not_verified",
            "severity": "review",
            "basis": "The acceptance copy records the observed copied bytes but does not validate package-declared checksum or signature facts.",
            "does_not_claim": "package_integrity_verified",
        },
    ]


def _linked_context_for_measurement(
    manifest: dict[str, Any],
    measurement_record_id: str,
) -> list[dict[str, Any]]:
    linked_context = []
    for item in manifest["linked_context"]:
        if measurement_record_id not in item["linked_measurement_record_ids"]:
            continue
        linked_context.append(
            {
                "link_id": item["link_id"],
                "kind": item["kind"],
                "label": item["label"],
                "relation": item["relation"],
                "authority": item["authority"],
                "linked_measurement_record_ids": list(item["linked_measurement_record_ids"]),
                "materialization": "reference_only",
                "payload_materialization": "not_performed",
                "source_package": {
                    "package_state": item["package_state"],
                    "include_status": item["include_status"],
                    "reason": item.get("reason"),
                },
            }
        )
    return linked_context


def accept_handoff_package(
    source: dict[str, Any],
    *,
    package_dir: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Accept a reviewed handoff package into new local storage records."""

    source = _require_mapping(source, "handoff package acceptance source")
    _validate_policy(source)

    package_root = existing_directory_root(package_dir, "package")
    storage_root = existing_directory_root(storage_root, "storage")
    _validate_separate_roots(package_root, storage_root)

    read_view = open_handoff_package_view(package_root)
    package_manifest = _load_package_manifest(package_root)
    request = _require_mapping(source.get("acceptance_request"), "acceptance_request")
    _require_keys(
        request,
        {"request_id", "review", "destination", "materialization", "selected_measurements"},
        "acceptance_request",
    )
    request_id = validate_public_identifier(
        request.get("request_id"), "acceptance_request.request_id"
    )
    _validate_review(request, read_view)
    _validate_destination(request)
    selected = _validate_selected_measurements(request, read_view)

    record_dirs = [destination["record_dir"] for destination in selected]
    all_targets: list[str] = []
    for destination in selected:
        all_targets.extend([destination["primary_data_path"], destination["manifest_path"]])
    if len(all_targets) != len(set(all_targets)):
        raise ValueError("storage targets must be unique")
    for record_dir in record_dirs:
        ensure_no_symlink_parents(storage_root, record_dir, "storage record directory")
        if target_exists(storage_root, record_dir):
            raise ValueError(f"storage record directory already exists: {record_dir}")
    for target in all_targets:
        ensure_no_symlink_parents(storage_root, target, "storage target")
        if target_exists(storage_root, target):
            raise ValueError(f"storage target already exists: {target}")

    pending_records: list[dict[str, Any]] = []
    for destination in selected:
        measurement = read_view.measurement(destination["measurement_record_id"])
        primary_content = _read_package_file(package_root, measurement.primary_package_path)
        manifest = _record_manifest(
            request_id=request_id,
            read_view=read_view,
            measurement=measurement,
            destination=destination,
            primary_content=primary_content,
            linked_context=_linked_context_for_measurement(
                package_manifest,
                measurement.measurement_record_id,
            ),
        )
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        pending_records.append(
            {
                "destination": destination,
                "measurement": measurement,
                "primary_content": primary_content,
                "manifest": manifest,
                "manifest_bytes": manifest_bytes,
            }
        )

    written_paths, _created_dirs = write_new_files_transaction(
        storage_root,
        [
            item
            for record in pending_records
            for item in (
                (record["destination"]["primary_data_path"], record["primary_content"]),
                (record["destination"]["manifest_path"], record["manifest_bytes"]),
            )
        ],
        label="storage target",
    )

    accepted_measurements = []
    for record in pending_records:
        destination = record["destination"]
        manifest = record["manifest"]
        accepted_measurements.append(
            {
                "measurement_record_id": destination["measurement_record_id"],
                "record_dir": destination["record_dir"],
                "primary_data_path": destination["primary_data_path"],
                "manifest_path": destination["manifest_path"],
                "source_package_path": manifest["source"]["package_primary_path"],
                "primary_data_copied": True,
                "manifest_written": True,
                "digest": manifest["primary_data"]["digest"],
                "size_bytes": manifest["primary_data"]["size_bytes"],
                "linked_context_count": len(manifest["linked_context"]),
            }
        )

    return {
        "artifact_posture": "local_write_receipt",
        "acceptance_policy": copy.deepcopy(_EXPECTED_POLICY),
        "package": {
            "package_id": read_view.package_id,
            "display_name": read_view.display_name,
            "package_directory_name": package_root.name,
            "preview_classification": read_view.preview_classification,
            "measurement_count": len(read_view.measurement_ids),
        },
        "acceptance_request": {
            "request_id": request_id,
            "approval_state": "approved",
            "selected_measurement_count": len(selected),
        },
        "storage_write": {
            "record_count": len(accepted_measurements),
            "written_paths": list(written_paths),
            "overwrite_behavior": "no_overwrite",
            "rollback_on_failure": "best_effort_for_written_files_and_created_dirs",
        },
        "accepted_measurements": accepted_measurements,
        "attention": _attention(),
    }
