"""Internal stored-primary-table read helpers."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    MANIFEST_SCHEMA,
    WRITER_RECEIPT_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
    validate_text,
)
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
from scopecat.measurement_records.normalized_primary_table import (
    summarize_observed_primary_table,
)


@dataclass(frozen=True)
class PrimaryTableReadRequest:
    """Internal request to read primary table facts from a stored record."""

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


@dataclass(frozen=True)
class PrimaryTableReadResult:
    """Internal read result for stored primary table data."""

    request: PrimaryTableReadRequest
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


def read_record_primary_table(
    request: PrimaryTableReadRequest,
    *,
    storage_root: str | Path,
) -> PrimaryTableReadResult:
    """Read stored primary table facts through the record writer receipt."""

    root = _existing_directory_root(Path(storage_root), "primary table read storage root")
    manifest = _read_creation_manifest(root, request)
    writer_receipt = _read_writer_receipt(root, request)
    primary_content = _read_primary_data(root, request, writer_receipt)
    table, findings = _read_table(
        primary_content,
        source=writer_receipt["primary_data"]["path"],
        declared_row_count=writer_receipt["primary_data"]["rows_recorded"],
        preview_row_limit=request.preview_row_limit,
    )
    return PrimaryTableReadResult(
        request=request,
        storage_root=root,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        table=table,
        review_findings=tuple(findings),
    )


def _read_creation_manifest(root: Path, request: PrimaryTableReadRequest) -> dict[str, Any]:
    manifest_path = _path_under(root, request.creation_manifest_path)
    _ensure_no_symlink_parents(
        root,
        request.creation_manifest_path,
        "primary table read creation manifest",
    )
    if manifest_path.is_symlink():
        raise ValueError("primary table read creation manifest must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("primary table read requires an existing creation manifest") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("primary table read creation manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("primary table read record_id must match creation manifest")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("primary table read record_dir must match creation manifest")
    if storage.get("manifest_path") != request.creation_manifest_path:
        raise ValueError("primary table read manifest_path must match creation manifest")
    return manifest


def _read_writer_receipt(root: Path, request: PrimaryTableReadRequest) -> dict[str, Any]:
    receipt_path = _path_under(root, request.writer_receipt_path)
    _ensure_no_symlink_parents(
        root,
        request.writer_receipt_path,
        "primary table read writer receipt",
    )
    if receipt_path.is_symlink():
        raise ValueError("primary table read writer receipt must not be a symlink")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("primary table read requires an existing writer receipt") from exc
    if receipt.get("schema") != WRITER_RECEIPT_SCHEMA:
        raise ValueError("primary table read writer receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("primary table read record_id must match writer receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("primary table read record_dir must match writer receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError("primary table read creation manifest path must match writer receipt")
    writer_request = _require_dict(receipt, "writer_request")
    if writer_request.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError("primary table read writer_receipt_path must match writer receipt")
    primary_data = _require_dict(receipt, "primary_data")
    primary_path = validate_text(primary_data.get("path"), "writer receipt primary_data path")
    validate_relative_path(primary_path, "writer receipt primary_data path")
    _validate_strict_child_path(
        primary_path, request.record_dir, "writer receipt primary_data path"
    )
    if primary_data.get("format") != "csv_table":
        raise ValueError("primary table read primary_data format is unsupported")
    validate_sha256_digest(primary_data.get("digest"), "writer receipt primary_data digest")
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
    request: PrimaryTableReadRequest,
    writer_receipt: dict[str, Any],
) -> bytes:
    primary = writer_receipt["primary_data"]
    primary_path = primary["path"]
    _ensure_no_symlink_parents(root, primary_path, "primary table read primary data")
    target = _path_under(root, primary_path)
    if target.is_symlink():
        raise ValueError("primary table read primary data must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("primary table read primary data is unavailable") from exc
    if _sha256(content) != primary["digest"]:
        raise ValueError("primary table read primary data digest does not match writer receipt")
    if len(content) != primary["size_bytes"]:
        raise ValueError("primary table read primary data size does not match writer receipt")
    _validate_strict_child_path(primary_path, request.record_dir, "primary table read primary data")
    return content


def _read_table(
    content: bytes,
    *,
    source: str,
    declared_row_count: int,
    preview_row_limit: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    return summarize_observed_primary_table(
        content,
        source=source,
        declared_row_count=declared_row_count,
        preview_row_limit=preview_row_limit,
    )


def read_result_summary(result: PrimaryTableReadResult) -> dict[str, Any]:
    return {
        "classification": result.classification,
        "table": copy.deepcopy(result.table),
        "review_findings": [copy.deepcopy(finding) for finding in result.review_findings],
    }


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "primary table read path")


def _validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item
