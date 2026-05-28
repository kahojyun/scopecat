"""Read-only opener for directory-shaped handoff packages."""

from __future__ import annotations

import copy
import csv
import json
import os
import stat
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts as _relative_parts,
)
from implementation_candidates.contract_primitives import (
    validate_package_primary_data_path,
    validate_positive_integer,
    validate_public_identifier,
    validate_sha256_digest,
)
from implementation_candidates.handoff_package_contents_preview import (
    build_handoff_package_contents_preview_summary,
)

_MANIFEST_NAME = "package-manifest.json"
_OPEN_POLICY = {
    "open_authority": "caller_provided_package_directory",
    "manifest_name": _MANIFEST_NAME,
    "manifest_preview": "scopecat_export_manifest_contract_reused",
    "file_opening": "package_local_declared_primary_data",
    "primary_data_loading": "declared_csv_preview_rows",
    "archive_extraction": "not_performed",
    "checksum_validation": "not_performed",
    "package_integrity": "not_claimed",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "sdk_object_model": "not_defined",
}


def _existing_package_dir(package_dir: Path) -> Path:
    if package_dir.is_symlink():
        raise ValueError("handoff package opener package directory must not be a symlink")
    if not package_dir.is_dir():
        raise ValueError("handoff package opener requires an existing package directory")
    return package_dir.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path, "handoff package member path"))


def _ensure_no_symlink_parents(root: Path, relative_path: str, owner: str) -> None:
    current = root
    for part in _relative_parts(relative_path, owner)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{owner} parent must not be a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{owner} parent must be a directory")


def _read_regular_package_file(package_dir: Path, relative_path: str, owner: str) -> bytes:
    _ensure_no_symlink_parents(package_dir, relative_path, owner)
    target = _path_under(package_dir, relative_path)
    if target.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    try:
        with target.open("rb") as handle:
            file_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError(f"{owner} must be a regular file")
            return handle.read()
    except FileNotFoundError as exc:
        raise ValueError(f"{owner} is unavailable") from exc
    except OSError as exc:
        raise ValueError(f"{owner} is unavailable") from exc


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    content = _read_regular_package_file(
        package_dir,
        _MANIFEST_NAME,
        "handoff package manifest",
    )
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff package manifest must be valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("handoff package manifest must be a JSON object")
    return manifest


def _validate_manifest_identity(package_dir: Path, manifest: dict[str, Any]) -> None:
    package_id = manifest["package_identity"]["package_id"]
    validate_public_identifier(package_id, "handoff package package_id")
    if package_dir.name != package_id:
        raise ValueError("handoff package directory name must match package_id")


def _validate_primary_manifest_facts(record: dict[str, Any]) -> None:
    measurement_id = record["measurement_record_id"]
    validate_public_identifier(measurement_id, "measurement_record_id")
    primary = record["primary_data"]
    validate_package_primary_data_path(
        primary["package_path"],
        measurement_record_id=measurement_id,
        owner="handoff package primary_data package_path",
    )
    has_digest = "digest" in primary
    has_size = "size_bytes" in primary
    if has_digest != has_size:
        raise ValueError("handoff package primary_data digest and size_bytes must match")
    if has_digest:
        validate_sha256_digest(primary["digest"], "handoff package primary_data digest")
        validate_positive_integer(
            primary["size_bytes"],
            "handoff package primary_data size_bytes",
        )
    if primary["format"] != "csv_table":
        raise ValueError("handoff package opener currently supports csv_table primary data")


def _load_csv_rows(
    content: bytes,
    record: dict[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    preview = record["declared_preview_metadata"]
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("handoff package primary data must be utf-8 CSV") from exc

    reader = csv.DictReader(decoded.splitlines())
    if not reader.fieldnames:
        raise ValueError("handoff package primary data requires a CSV header")

    declared_names = [column["name"] for column in preview["declared_columns"]]
    fieldnames = list(reader.fieldnames)
    if any(name == "" for name in fieldnames):
        raise ValueError("handoff package primary data requires non-empty CSV headers")
    if len(set(fieldnames)) != len(fieldnames):
        raise ValueError("handoff package primary data requires unique CSV headers")
    missing = [name for name in declared_names if name not in fieldnames]
    if missing:
        raise ValueError("handoff package primary data is missing declared preview columns")
    rows = []
    for row in reader:
        if None in row:
            raise ValueError("handoff package primary data rows must match the CSV header")
        if any(row[name] is None for name in fieldnames):
            raise ValueError("handoff package primary data rows must match the CSV header")
        rows.append({name: row[name] for name in fieldnames})
    return fieldnames, rows


def _preview_rows(rows: list[dict[str, str]], declared_names: list[str]) -> list[dict[str, str]]:
    return [{name: row[name] for name in declared_names} for row in rows[:5]]


def _plot_series(
    rows: list[dict[str, str]],
    plot_candidates: list[dict[str, str]],
) -> list[dict[str, Any]]:
    series = []
    for candidate in plot_candidates:
        series.append(
            {
                "source": candidate["source"],
                "x": candidate["x"],
                "y": candidate["y"],
                "points": [
                    {
                        "x": row[candidate["x"]],
                        "y": row[candidate["y"]],
                    }
                    for row in rows
                ],
            }
        )
    return series


def _opened_measurement(package_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    _validate_primary_manifest_facts(record)
    preview = record["declared_preview_metadata"]
    if preview["status"] != "preview_ready":
        raise ValueError("handoff package opener requires preview_ready metadata")
    primary = record["primary_data"]
    content = _read_regular_package_file(
        package_dir,
        primary["package_path"],
        "handoff package primary data",
    )
    columns, rows = _load_csv_rows(content, record)
    declared_names = [column["name"] for column in preview["declared_columns"]]
    primary_data = {
        "package_path": primary["package_path"],
        "format": primary["format"],
        "open_state": "opened",
        "observed_size_bytes": len(content),
        "integrity_check": "not_performed",
    }
    if "digest" in primary and "size_bytes" in primary:
        primary_data["declared_digest"] = primary["digest"]
        primary_data["declared_size_bytes"] = primary["size_bytes"]
    return {
        "measurement_record_id": record["measurement_record_id"],
        "legacy_data_id": record["legacy_data_id"],
        "label": record["label"],
        "experiment_type": record["experiment_type"],
        "target": record["target"],
        "primary_data": primary_data,
        "declared_preview": {
            "status": preview["status"],
            "metadata_authority": preview["metadata_authority"],
            "data_shape": copy.deepcopy(preview["data_shape"]),
            "declared_columns": copy.deepcopy(preview["declared_columns"]),
            "plot_candidates": copy.deepcopy(preview["plot_candidates"]),
        },
        "primary_table": {
            "source": primary["package_path"],
            "columns": columns,
            "rows": copy.deepcopy(rows),
            "schema_inference": "not_performed",
        },
        "preview_data": {
            "source": primary["package_path"],
            "row_count": len(rows),
            "preview_rows": _preview_rows(rows, declared_names),
            "plot_series": _plot_series(rows, preview["plot_candidates"]),
            "schema_inference": "not_performed",
        },
        "classification": "opened_for_declared_preview",
    }


def _linked_context_summary(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "link_id": item["link_id"],
            "kind": item["kind"],
            "label": item["label"],
            "package_state": item["package_state"],
            "materialization": "reference_only",
            "linked_measurement_record_ids": list(item["linked_measurement_record_ids"]),
        }
        for item in manifest["linked_context"]
    ]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "package_opened_read_only",
            "severity": "info",
            "basis": (
                "Declared package manifest and package-local primary data were opened "
                "without storage mutation."
            ),
            "does_not_claim": "package_acceptance_or_import",
        },
        {
            "code": "package_integrity_not_claimed",
            "severity": "review",
            "basis": (
                "Declared digest and size facts remain manifest facts where present; "
                "this opener does not compare them."
            ),
            "does_not_claim": "package_integrity_verified",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview rows and plot series are derived only from manifest-declared columns.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "linked_context_reference_only",
            "severity": "review",
            "basis": "Linked context remains visible reference-only during read-only package use.",
            "does_not_claim": "recursive_relation_traversal_or_context_capture",
        },
    ]


def open_handoff_package(package_dir: Path) -> dict[str, Any]:
    """Open a directory-shaped handoff package for read-only declared preview use."""

    package_dir = _existing_package_dir(package_dir)
    manifest = _load_manifest(package_dir)
    preview_summary = build_handoff_package_contents_preview_summary(manifest)
    _validate_manifest_identity(package_dir, manifest)
    measurements = [
        _opened_measurement(package_dir, record) for record in manifest["selected_measurements"]
    ]
    return {
        "package_open_policy": copy.deepcopy(_OPEN_POLICY),
        "package": {
            "package_id": manifest["package_identity"]["package_id"],
            "display_name": manifest["package_identity"]["display_name"],
            "created_by": manifest["package_identity"]["created_by"],
            "source_export_summary_id": manifest["package_identity"]["source_export_summary_id"],
            "manifest_path": _MANIFEST_NAME,
            "classification": "opened_read_only_for_declared_preview",
            "preview_classification": preview_summary["package"]["classification"],
        },
        "manifest_preview_findings": copy.deepcopy(preview_summary["preview_findings"]),
        "selected_measurements": measurements,
        "linked_context": _linked_context_summary(manifest),
        "open_findings": [],
        "attention": _attention(),
    }
