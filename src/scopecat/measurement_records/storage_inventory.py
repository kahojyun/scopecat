"""Read-only inventory over Measurement Records storage."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import path_under as _path_under_common
from scopecat.measurement_records._storage import sha256 as _sha256
from scopecat.measurement_records.creation import (
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    validate_public_identifier,
    validate_relative_path,
)
from scopecat.measurement_records.legacy_run import (
    LEGACY_RUN_RECEIPT_NAME,
    LEGACY_RUN_RECEIPT_SCHEMA,
)
from scopecat.measurement_records.read_model_shared import (
    READ_MODEL_FILENAME,
    READ_MODEL_SCHEMA,
)


@dataclass(frozen=True)
class MeasurementRecordStorageInventoryRequest:
    """Request to list visible Measurement Records storage contents."""

    request_id: str
    records_dir: str = "records"
    include_read_models: bool = True
    include_legacy_receipts: bool = True

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "storage inventory request_id")
        validate_relative_path(self.records_dir, "storage inventory records_dir")
        if not isinstance(self.include_read_models, bool):
            raise ValueError("storage inventory include_read_models must be boolean")
        if not isinstance(self.include_legacy_receipts, bool):
            raise ValueError("storage inventory include_legacy_receipts must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "records_dir": self.records_dir,
            "include_read_models": self.include_read_models,
            "include_legacy_receipts": self.include_legacy_receipts,
        }


@dataclass(frozen=True)
class MeasurementRecordStorageInventoryRun:
    """Read-only storage inventory result."""

    request: MeasurementRecordStorageInventoryRequest
    storage_root: Path
    entries: tuple[dict[str, Any], ...] = ()
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "measurement_record_storage_inventory_review_needed"
        return "measurement_record_storage_inventory_ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_measurement_record_storage_inventory",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "entries": [copy.deepcopy(entry) for entry in self.entries],
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
            "next_action": _next_action(self.entries, self.review_findings),
        }


def list_measurement_record_storage_from_request(
    request: MeasurementRecordStorageInventoryRequest,
    *,
    storage_root: str | Path,
) -> MeasurementRecordStorageInventoryRun:
    """List Measurement Records storage contents from a typed request."""

    root = _existing_directory_root(Path(storage_root), "storage inventory storage root")
    records_path = _path_under(root, request.records_dir)
    _ensure_no_symlink_parents(root, request.records_dir, "storage inventory records dir")
    if records_path.is_symlink():
        raise ValueError("storage inventory records dir must not be a symlink")
    if not records_path.exists():
        return MeasurementRecordStorageInventoryRun(request=request, storage_root=root)
    if not records_path.is_dir():
        raise ValueError("storage inventory records dir must be a directory")

    entries: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    for record_path in sorted(records_path.iterdir(), key=lambda item: item.name):
        record_rel = _relative_to_root(root, record_path)
        if record_path.is_symlink():
            findings.append(
                _finding(
                    "record_dir_symlink_ignored",
                    record_rel,
                    "Record directory candidate is a symlink.",
                )
            )
            continue
        if not record_path.is_dir():
            findings.append(
                _finding(
                    "non_record_entry_ignored",
                    record_rel,
                    "Records directory contains a non-directory entry.",
                )
            )
            continue
        entry, entry_findings = _inventory_record_dir(root, record_rel, request)
        if entry is not None:
            entries.append(entry)
        findings.extend(entry_findings)

    return MeasurementRecordStorageInventoryRun(
        request=request,
        storage_root=root,
        entries=tuple(entries),
        review_findings=tuple(findings),
    )


def _inventory_record_dir(
    root: Path,
    record_dir: str,
    request: MeasurementRecordStorageInventoryRequest,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    manifest_path = f"{record_dir}/{RECORD_MANIFEST_NAME}"
    try:
        manifest, manifest_digest, manifest_size = _read_json_ref(root, manifest_path)
        _validate_manifest(manifest, record_dir, manifest_path)
    except ValueError as exc:
        return (
            None,
            [_finding("record_manifest_invalid", manifest_path, str(exc))],
        )

    record = manifest["record"]
    creation = manifest["creation"]
    primary_data = manifest["primary_data"]
    entry: dict[str, Any] = {
        "record_id": record["record_id"],
        "record_dir": record_dir,
        "manifest": {
            "path": manifest_path,
            "digest": manifest_digest,
            "size_bytes": manifest_size,
            "schema": manifest["schema"],
        },
        "lifecycle_state": record["lifecycle_state"],
        "creation_source_kind": creation["source_kind"],
        "label": record.get("label"),
        "experiment_type": record.get("experiment_type"),
        "primary_data": {
            "state": primary_data.get("state"),
            "reference_count": len(primary_data.get("references", [])),
        },
        "read_model": {"state": "not_checked"},
        "legacy_run": {"state": "not_checked"},
    }
    if request.include_read_models:
        read_model, read_model_findings = _read_model_summary(root, record_dir, entry)
        entry["read_model"] = read_model
        findings.extend(read_model_findings)
    if request.include_legacy_receipts:
        legacy_run, legacy_findings = _legacy_run_summary(root, record_dir, entry)
        entry["legacy_run"] = legacy_run
        findings.extend(legacy_findings)
    entry["next_action"] = _entry_next_action(entry, findings)
    return entry, findings


def _validate_manifest(manifest: dict[str, Any], record_dir: str, manifest_path: str) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("record manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    creation = _require_dict(manifest, "creation")
    storage = _require_dict(manifest, "storage")
    primary_data = _require_dict(manifest, "primary_data")
    validate_public_identifier(record.get("record_id"), "storage inventory record_id")
    if not isinstance(record.get("lifecycle_state"), str):
        raise ValueError("record manifest lifecycle_state is required")
    if not isinstance(creation.get("source_kind"), str):
        raise ValueError("record manifest creation source_kind is required")
    if storage.get("record_dir") != record_dir:
        raise ValueError("record manifest record_dir conflicts with scanned path")
    if storage.get("manifest_path") != manifest_path:
        raise ValueError("record manifest path conflicts with scanned path")
    if not isinstance(primary_data.get("references", []), list):
        raise ValueError("record manifest primary data references must be a list")


def _read_model_summary(
    root: Path,
    record_dir: str,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    read_model_path = f"{record_dir}/{READ_MODEL_FILENAME}"
    target = _path_under(root, read_model_path)
    if target.is_symlink():
        return (
            {"state": "invalid", "path": read_model_path},
            [
                _finding(
                    "read_model_symlink_ignored",
                    read_model_path,
                    "Projected read model is a symlink.",
                )
            ],
        )
    if not target.exists():
        return {"state": "missing", "path": read_model_path}, []
    try:
        model, digest, size = _read_json_ref(root, read_model_path)
        if model.get("schema") != READ_MODEL_SCHEMA:
            raise ValueError("read model schema is unsupported")
        record = _require_dict(model, "record")
        if record.get("record_id") != entry["record_id"]:
            raise ValueError("read model record_id conflicts with manifest")
        if record.get("record_dir") != record_dir:
            raise ValueError("read model record_dir conflicts with scanned path")
    except ValueError as exc:
        return (
            {"state": "invalid", "path": read_model_path},
            [_finding("read_model_invalid", read_model_path, str(exc))],
        )
    return (
        {
            "state": "present",
            "path": read_model_path,
            "digest": digest,
            "size_bytes": size,
            "lifecycle_state": record.get("lifecycle_state"),
        },
        [],
    )


def _legacy_run_summary(
    root: Path,
    record_dir: str,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    receipt_path = f"{record_dir}/{LEGACY_RUN_RECEIPT_NAME}"
    target = _path_under(root, receipt_path)
    if target.is_symlink():
        return (
            {"state": "invalid", "path": receipt_path},
            [
                _finding(
                    "legacy_receipt_symlink_ignored",
                    receipt_path,
                    "Legacy run receipt is a symlink.",
                )
            ],
        )
    if not target.exists():
        if entry["creation_source_kind"] == "legacy_system":
            return (
                {"state": "missing", "path": receipt_path},
                [
                    _finding(
                        "legacy_receipt_missing",
                        receipt_path,
                        "Legacy-system record has no record-local legacy receipt.",
                    )
                ],
            )
        return {"state": "not_present", "path": receipt_path}, []
    try:
        receipt, digest, size = _read_json_ref(root, receipt_path)
        if receipt.get("schema") != LEGACY_RUN_RECEIPT_SCHEMA:
            raise ValueError("legacy run receipt schema is unsupported")
        record = _require_dict(receipt, "record")
        if record.get("record_id") != entry["record_id"]:
            raise ValueError("legacy run receipt record_id conflicts with manifest")
        if record.get("record_dir") != record_dir:
            raise ValueError("legacy run receipt record_dir conflicts with scanned path")
        legacy_run = _require_dict(receipt, "legacy_run")
        locators = receipt.get("declared_locators", [])
        if not isinstance(locators, list):
            raise ValueError("legacy run receipt locators must be a list")
    except ValueError as exc:
        return (
            {"state": "invalid", "path": receipt_path},
            [_finding("legacy_receipt_invalid", receipt_path, str(exc))],
        )
    return (
        {
            "state": "present",
            "path": receipt_path,
            "digest": digest,
            "size_bytes": size,
            "legacy_system_id": legacy_run.get("legacy_system_id"),
            "legacy_run_id": legacy_run.get("legacy_run_id"),
            "locator_count": len(locators),
            "context_reference_count": len(receipt.get("context_references", [])),
        },
        [],
    )


def _read_json_ref(root: Path, relative_path: str) -> tuple[dict[str, Any], str, int]:
    target = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "storage inventory source")
    if target.is_symlink():
        raise ValueError("storage inventory source must not be a symlink")
    if not target.is_file():
        raise ValueError("storage inventory source must be a file")
    content = target.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"storage inventory JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("storage inventory JSON must be an object")
    return payload, _sha256(content), len(content)


def _entry_next_action(entry: dict[str, Any], findings: list[dict[str, str]]) -> str:
    record_dir = entry["record_dir"]
    if any(finding["path"].startswith(f"{record_dir}/") for finding in findings):
        return "review_record_inventory_findings"
    if entry["legacy_run"]["state"] == "present" and entry["primary_data"]["state"] != "recorded":
        return "review_legacy_run_or_import_primary_data"
    if entry["read_model"]["state"] == "missing":
        return "project_or_refresh_record_read_model_when_ready"
    return "select_record_for_review"


def _next_action(
    entries: tuple[dict[str, Any], ...],
    findings: tuple[dict[str, str], ...],
) -> str:
    if findings:
        return "review_storage_inventory_findings"
    if not entries:
        return "record_or_import_measurement_runs"
    if any(entry["legacy_run"]["state"] == "present" for entry in entries):
        return "review_legacy_runs_or_import_primary_data"
    return "select_record_for_review"


def _finding(code: str, path: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "path": path,
        "message": message,
    }


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "storage inventory path")


def _relative_to_root(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"storage inventory {key} must be an object")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"storage inventory {key} must be text")
    return value


def _optional_text(source: dict[str, Any], key: str, *, default: str) -> str:
    value = source.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"storage inventory {key} must be text")
    return value


def _optional_bool(source: dict[str, Any], key: str, *, default: bool) -> bool:
    value = source.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"storage inventory {key} must be boolean")
    return value
