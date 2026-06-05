"""Read primary table data from a created record with a writer receipt."""

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
from scopecat.measurement_records._storage import (
    path_under as _path_under_common,
)
from scopecat.measurement_records._storage import (
    sha256 as _sha256,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.creation import (
    MANIFEST_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.normalized_primary_table import (
    summarize_observed_primary_table_for_read_view,
)
from scopecat.measurement_records.writer_integration import WRITER_RECEIPT_SCHEMA


@dataclass(frozen=True)
class MeasurementRecordReadRequest:
    """Request to read primary table facts from a created record."""

    request_id: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    preview_row_limit: int = 5

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "read request request_id")
        validate_public_identifier(self.record_id, "read request record_id")
        validate_relative_path(self.record_dir, "read request record_dir")
        validate_relative_path(self.writer_receipt_path, "read request writer_receipt_path")
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "read request writer_receipt_path",
        )
        _validate_positive_integer(self.preview_row_limit, "read request preview_row_limit")

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "writer_receipt_path": self.writer_receipt_path,
            "preview_row_limit": self.preview_row_limit,
        }


@dataclass(frozen=True)
class MeasurementRecordReadRun:
    """Local read summary for a created record with writer data."""

    request: MeasurementRecordReadRequest
    storage_root: Path
    record_manifest: dict[str, Any]
    writer_receipt: dict[str, Any]
    table: dict[str, Any]
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "primary_table_review_needed"
        return "primary_table_ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_read_view",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "record_manifest": _manifest_ref(self.record_manifest),
            "writer_receipt": _writer_receipt_ref(self.writer_receipt),
            "table": copy.deepcopy(self.table),
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
        }


def read_created_record_primary_table_from_request(
    request: MeasurementRecordReadRequest,
    *,
    storage_root: str | Path,
) -> MeasurementRecordReadRun:
    """Read primary table facts from a typed read-view request."""

    root = _existing_directory_root(Path(storage_root), "read view storage root")
    manifest = _read_creation_manifest(root, request)
    writer_receipt = _read_writer_receipt(root, request)
    primary_content = _read_primary_data(root, request, writer_receipt)
    table, findings = _read_table(
        primary_content,
        source=writer_receipt["primary_data"]["path"],
        declared_row_count=writer_receipt["primary_data"]["rows_recorded"],
        preview_row_limit=request.preview_row_limit,
    )
    return MeasurementRecordReadRun(
        request=request,
        storage_root=root,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        table=table,
        review_findings=tuple(findings),
    )


def _read_creation_manifest(root: Path, request: MeasurementRecordReadRequest) -> dict[str, Any]:
    manifest_path = _path_under(root, request.creation_manifest_path)
    _ensure_no_symlink_parents(root, request.creation_manifest_path, "read view creation manifest")
    if manifest_path.is_symlink():
        raise ValueError("read view creation manifest must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("read view requires an existing creation manifest") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("read view creation manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("read view record_id must match creation manifest")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("read view record_dir must match creation manifest")
    if storage.get("manifest_path") != request.creation_manifest_path:
        raise ValueError("read view manifest_path must match creation manifest")
    return manifest


def _read_writer_receipt(root: Path, request: MeasurementRecordReadRequest) -> dict[str, Any]:
    receipt_path = _path_under(root, request.writer_receipt_path)
    _ensure_no_symlink_parents(root, request.writer_receipt_path, "read view writer receipt")
    if receipt_path.is_symlink():
        raise ValueError("read view writer receipt must not be a symlink")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("read view requires an existing writer receipt") from exc
    if receipt.get("schema") != WRITER_RECEIPT_SCHEMA:
        raise ValueError("read view writer receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("read view record_id must match writer receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("read view record_dir must match writer receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError("read view creation manifest path must match writer receipt")
    writer_request = _require_dict(receipt, "writer_request")
    if writer_request.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError("read view writer_receipt_path must match writer receipt")
    primary_data = _require_dict(receipt, "primary_data")
    primary_path = validate_text(primary_data.get("path"), "writer receipt primary_data path")
    validate_relative_path(primary_path, "writer receipt primary_data path")
    _validate_strict_child_path(
        primary_path, request.record_dir, "writer receipt primary_data path"
    )
    if primary_data.get("format") != "csv_table":
        raise ValueError("read view primary_data format is unsupported")
    _validate_sha256_digest(primary_data.get("digest"), "writer receipt primary_data digest")
    _validate_non_negative_integer(
        primary_data.get("size_bytes"),
        "writer receipt primary_data size_bytes",
    )
    _validate_non_negative_integer(
        primary_data.get("rows_recorded"),
        "writer receipt primary_data rows_recorded",
    )
    return receipt


def _read_primary_data(
    root: Path,
    request: MeasurementRecordReadRequest,
    writer_receipt: dict[str, Any],
) -> bytes:
    primary = writer_receipt["primary_data"]
    primary_path = primary["path"]
    _ensure_no_symlink_parents(root, primary_path, "read view primary data")
    target = _path_under(root, primary_path)
    if target.is_symlink():
        raise ValueError("read view primary data must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("read view primary data is unavailable") from exc
    if _sha256(content) != primary["digest"]:
        raise ValueError("read view primary data digest does not match writer receipt")
    if len(content) != primary["size_bytes"]:
        raise ValueError("read view primary data size does not match writer receipt")
    _validate_strict_child_path(primary_path, request.record_dir, "read view primary data")
    return content


def _read_table(
    content: bytes,
    *,
    source: str,
    declared_row_count: int,
    preview_row_limit: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return summarize_observed_primary_table_for_read_view(
        content,
        source=source,
        declared_row_count=declared_row_count,
        preview_row_limit=preview_row_limit,
    )


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


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "read view path")


def _validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _validate_sha256_digest(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value.removeprefix("sha256:"))
    ):
        raise ValueError(f"{owner} must be a sha256-prefixed hex digest")
    return value


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_positive_int(value: dict[str, Any], field: str, *, default: int) -> int:
    if field not in value:
        return default
    return _validate_positive_integer(value[field], field)
