"""Shared helpers for record-local read-model projection and refresh."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Protocol

from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import (
    path_under as _path_under_common,
)
from scopecat.measurement_records._storage import (
    sha256 as _sha256,
)
from scopecat.measurement_records._storage import (
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path_common,
)
from scopecat.measurement_records.creation import validate_text
from scopecat.measurement_records.finalization import FINALIZATION_RECEIPT_SCHEMA
from scopecat.measurement_records.read_view import MeasurementRecordReadRun

READ_MODEL_SCHEMA = "measurement_record_read_model_candidate_v0"
READ_MODEL_DOES_NOT_CLAIM = (
    "manifest_replacement",
    "canonical_storage_authority",
    "read_model_refresh",
    "stale_read_model_repair",
    "final_storage_schema",
    "conflict_resolution",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "export_schema",
    "gui_review_state",
)


class ReadModelRequest(Protocol):
    """Projection-shaped request fields needed to derive a read model."""

    request_id: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str

    @property
    def creation_manifest_path(self) -> str:
        """Path to the record creation manifest."""


def _validate_request_against_read_view(
    request: ReadModelRequest,
    read_view: MeasurementRecordReadRun,
) -> None:
    if read_view.storage_root != _existing_directory_root(
        Path(read_view.storage_root),
        "read model projection read view storage root",
    ):
        raise ValueError("read model projection read view storage root is invalid")
    if request.record_id != read_view.request.record_id:
        raise ValueError("read model projection record_id must match read view")
    if request.record_dir != read_view.request.record_dir:
        raise ValueError("read model projection record_dir must match read view")
    if request.creation_manifest_path != read_view.request.creation_manifest_path:
        raise ValueError("read model projection creation_manifest_path must match read view")
    if request.writer_receipt_path != read_view.request.writer_receipt_path:
        raise ValueError("read model projection writer_receipt_path must match read view")


def _validate_finalization_receipt(
    request: ReadModelRequest,
    read_view: MeasurementRecordReadRun,
    receipt: dict[str, Any],
) -> None:
    if receipt.get("schema") != FINALIZATION_RECEIPT_SCHEMA:
        raise ValueError("read model projection finalization receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("read model projection record_id must match finalization receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("read model projection record_dir must match finalization receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError(
            "read model projection creation_manifest_path must match finalization receipt"
        )
    if record.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError(
            "read model projection writer_receipt_path must match finalization receipt"
        )
    finalization = _require_dict(receipt, "finalization")
    final_state = finalization.get("final_state")
    if final_state not in {"complete", "failed"}:
        raise ValueError("read model projection finalization state is unsupported")
    evidence = _require_dict(finalization, "evidence")
    writer_ref = _writer_receipt_ref(read_view.writer_receipt)
    if evidence.get("read_view_classification") != read_view.classification:
        raise ValueError("read model projection read view classification must match finalization")
    if evidence.get("primary_data_path") != writer_ref["primary_data_path"]:
        raise ValueError("read model projection primary data path must match finalization")
    if evidence.get("primary_data_digest") != writer_ref["primary_data_digest"]:
        raise ValueError("read model projection primary data digest must match finalization")
    if evidence.get("rows_recorded") != writer_ref["rows_recorded"]:
        raise ValueError("read model projection rows recorded must match finalization")
    if evidence.get("table_row_count") != read_view.table["row_count"]:
        raise ValueError("read model projection table row count must match finalization")
    if final_state == "failed":
        validate_text(finalization.get("operator_reason"), "finalization operator_reason")


def _read_model(
    request: ReadModelRequest,
    read_view: MeasurementRecordReadRun,
    *,
    manifest_digest: str,
    writer_receipt_digest: str,
    finalization_receipt: dict[str, Any],
    finalization_receipt_digest: str,
) -> dict[str, Any]:
    manifest_ref = _manifest_ref(read_view.record_manifest)
    writer_ref = _writer_receipt_ref(read_view.writer_receipt)
    finalization = _require_dict(finalization_receipt, "finalization")
    final_state = finalization["final_state"]
    finalization_entry = {
        "final_state": final_state,
        "operator_reason": finalization.get("operator_reason"),
    }
    return {
        "schema": READ_MODEL_SCHEMA,
        "read_model_policy": {
            "authority": "derived_from_record_local_receipts",
            "canonical_storage_authority": "not_claimed",
            "manifest_replacement": "not_performed",
            "refresh": "not_performed",
        },
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "lifecycle_state": final_state,
            "creation_lifecycle_state": manifest_ref["lifecycle_state"],
        },
        "sources": {
            "creation_manifest": {
                "path": request.creation_manifest_path,
                "schema": manifest_ref["schema"],
                "digest": manifest_digest,
            },
            "writer_receipt": {
                "path": request.writer_receipt_path,
                "schema": writer_ref["schema"],
                "digest": writer_receipt_digest,
            },
            "finalization_receipt": {
                "path": request.finalization_receipt_path,
                "schema": finalization_receipt.get("schema"),
                "digest": finalization_receipt_digest,
            },
            "read_view": {
                "classification": read_view.classification,
            },
        },
        "primary_data": {
            "path": writer_ref["primary_data_path"],
            "format": read_view.table["format"],
            "digest": writer_ref["primary_data_digest"],
            "size_bytes": _require_dict(read_view.writer_receipt, "primary_data").get("size_bytes"),
            "declared_row_count": writer_ref["rows_recorded"],
            "observed_row_count": read_view.table["row_count"],
        },
        "table": {
            "classification": read_view.table["classification"],
            "columns": copy.deepcopy(read_view.table["columns"]),
            "preview": copy.deepcopy(read_view.table["preview"]),
        },
        "review": {
            "findings": [copy.deepcopy(finding) for finding in read_view.review_findings],
        },
        "finalization": finalization_entry,
        "projection": {
            "request_id": request.request_id,
            "read_model_path": request.read_model_path,
            "projection_kind": "derived_local_summary",
        },
        "does_not_claim": list(READ_MODEL_DOES_NOT_CLAIM),
    }


def _manifest_ref(manifest: dict[str, Any]) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    storage = _require_dict(manifest, "storage")
    return {
        "schema": manifest.get("schema"),
        "record_id": record.get("record_id"),
        "lifecycle_state": record.get("lifecycle_state"),
        "record_dir": storage.get("record_dir"),
        "manifest_path": storage.get("manifest_path"),
    }


def _writer_receipt_ref(receipt: dict[str, Any]) -> dict[str, Any]:
    record = _require_dict(receipt, "record")
    primary_data = _require_dict(receipt, "primary_data")
    writer_request = _require_dict(receipt, "writer_request")
    return {
        "schema": receipt.get("schema"),
        "record_id": record.get("record_id"),
        "writer_receipt_path": writer_request.get("writer_receipt_path"),
        "primary_data_path": primary_data.get("path"),
        "primary_data_digest": primary_data.get("digest"),
        "rows_recorded": primary_data.get("rows_recorded"),
    }


def _read_json_at(root: Path, relative_path: str, label: str) -> tuple[dict[str, Any], str]:
    _ensure_no_symlink_parents(root, relative_path, label)
    path = _path_under(root, relative_path)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is required") from exc
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be utf-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed, _sha256(content)


def _json_bytes(content: dict[str, Any]) -> bytes:
    return (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _finalization_ref(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    finalization = _require_dict(receipt, "finalization")
    record = _require_dict(receipt, "record")
    return {
        "schema": receipt.get("schema"),
        "record_id": record.get("record_id"),
        "record_dir": record.get("record_dir"),
        "final_state": finalization.get("final_state"),
    }


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "read model projection path")


def _validate_strict_child_path(value: str, parent: str, owner: str) -> None:
    _validate_strict_child_path_common(value, parent, owner)


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=False)


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item
