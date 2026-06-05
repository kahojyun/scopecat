"""Inspect visible rows from an in-progress measurement record."""

from __future__ import annotations

import copy
import csv
import io
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
from scopecat.measurement_records.in_progress_update import UPDATE_RECEIPT_SCHEMA
from scopecat.measurement_records.writer_integration import (
    WRITER_RECEIPT_SCHEMA,
    validate_sha256_digest,
)

RUNNING_INSPECTION_SCHEMA = "scopecat.measurement_record_running_inspection.v0"
RUNNING_INSPECTION_SUMMARY_SCHEMA = "scopecat.measurement_record_running_inspection_summary.v0"


@dataclass(frozen=True)
class MeasurementRecordRunningInspectionRequest:
    """Read-only request to inspect an in-progress record."""

    request_id: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    update_receipt_paths: tuple[str, ...] = ()
    expected_total_rows: int | None = None
    preview_row_limit: int = 5

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "running inspection request_id")
        validate_public_identifier(self.record_id, "running inspection record_id")
        validate_relative_path(self.record_dir, "running inspection record_dir")
        validate_relative_path(
            self.writer_receipt_path,
            "running inspection writer_receipt_path",
        )
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "running inspection writer_receipt_path",
        )
        for path in self.update_receipt_paths:
            validate_relative_path(path, "running inspection update_receipt_path")
            _validate_strict_child_path(
                path,
                self.record_dir,
                "running inspection update_receipt_path",
            )
        if len(set(self.update_receipt_paths)) != len(self.update_receipt_paths):
            raise ValueError("running inspection update_receipt_paths must be unique")
        if self.expected_total_rows is not None:
            _validate_positive_integer(
                self.expected_total_rows,
                "running inspection expected_total_rows",
            )
        _validate_positive_integer(self.preview_row_limit, "running inspection preview_row_limit")

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        request = {
            "request_id": self.request_id,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "writer_receipt_path": self.writer_receipt_path,
            "update_receipt_paths": list(self.update_receipt_paths),
            "preview_row_limit": self.preview_row_limit,
        }
        if self.expected_total_rows is not None:
            request["expected_total_rows"] = self.expected_total_rows
        return request


@dataclass(frozen=True)
class MeasurementRecordRunningInspectionRun:
    """Local read-only inspection summary for an in-progress record."""

    request: MeasurementRecordRunningInspectionRequest
    storage_root: Path
    record_manifest: dict[str, Any]
    writer_receipt: dict[str, Any]
    update_receipts: tuple[dict[str, Any], ...]
    table: dict[str, Any]
    progress: dict[str, Any]
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "in_progress_table_review_needed"
        return "in_progress_table_ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_running_inspection_view",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "record_manifest": _manifest_ref(self.record_manifest),
            "writer_receipt": _writer_receipt_ref(self.writer_receipt),
            "update_receipts": [_update_receipt_ref(receipt) for receipt in self.update_receipts],
            "progress": copy.deepcopy(self.progress),
            "table": copy.deepcopy(self.table),
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
        }


def inspect_running_measurement_record(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordRunningInspectionRun:
    """Inspect visible rows from a raw running-inspection source."""

    request = _parse_source(source)
    return inspect_running_measurement_record_from_request(request, storage_root=storage_root)


def inspect_running_measurement_record_from_request(
    request: MeasurementRecordRunningInspectionRequest,
    *,
    storage_root: str | Path,
) -> MeasurementRecordRunningInspectionRun:
    """Inspect visible rows from a typed running-inspection request."""

    root = _existing_directory_root(Path(storage_root), "running inspection storage root")
    manifest = _read_creation_manifest(root, request)
    writer_receipt = _read_writer_receipt(root, request)
    primary_content = _read_primary_data(root, request, writer_receipt)
    update_receipts, append_segments = _read_update_receipts_and_segments(
        root, request, writer_receipt
    )
    _validate_append_segment_tables(primary_content, append_segments)
    visible_content = _combine_visible_content(primary_content, append_segments)
    declared_rows = (
        update_receipts[-1]["append_chunk"]["total_rows_recorded"]
        if update_receipts
        else writer_receipt["primary_data"]["rows_recorded"]
    )
    table, findings = _read_table(
        visible_content,
        source=writer_receipt["primary_data"]["path"],
        declared_row_count=declared_rows,
        preview_row_limit=request.preview_row_limit,
    )
    if request.expected_total_rows is not None and table["row_count"] > request.expected_total_rows:
        findings.append(
            {
                "code": "visible_rows_exceed_expected_total",
                "severity": "review",
                "target": request.record_id,
                "message": "Visible row count exceeds the requested expected total.",
            }
        )
    progress = {
        "state": "in_progress",
        "base_rows_recorded": writer_receipt["primary_data"]["rows_recorded"],
        "append_receipts_observed": len(update_receipts),
        "visible_rows_recorded": table["row_count"],
        "declared_visible_rows": declared_rows,
        "expected_total_rows": request.expected_total_rows,
        "remaining_rows": (
            None
            if request.expected_total_rows is None
            else max(request.expected_total_rows - table["row_count"], 0)
        ),
    }
    return MeasurementRecordRunningInspectionRun(
        request=request,
        storage_root=root,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        update_receipts=tuple(update_receipts),
        table=table,
        progress=progress,
        review_findings=tuple(findings),
    )


def summarize_running_measurement_inspection(
    run: MeasurementRecordRunningInspectionRun,
    *,
    latest_row_limit: int = 3,
) -> dict[str, Any]:
    """Project a compact local summary from a running-inspection run."""

    _validate_positive_integer(latest_row_limit, "running inspection latest_row_limit")
    rows = run.table["rows"]
    latest_rows = rows[-latest_row_limit:]
    finding_codes = [finding["code"] for finding in run.review_findings]
    return {
        "summary_schema": RUNNING_INSPECTION_SUMMARY_SCHEMA,
        "artifact_posture": "local_record_running_inspection_summary",
        "record": {
            "record_id": run.request.record_id,
            "record_dir": run.request.record_dir,
            "lifecycle_state": run.record_manifest["record"]["lifecycle_state"],
        },
        "inspection": {
            "classification": run.classification,
            "visible_rows_recorded": run.progress["visible_rows_recorded"],
            "expected_total_rows": run.progress["expected_total_rows"],
            "remaining_rows": run.progress["remaining_rows"],
            "append_receipts_observed": run.progress["append_receipts_observed"],
            "latest_row_limit": latest_row_limit,
            "latest_visible_rows": copy.deepcopy(latest_rows),
            "review_finding_codes": finding_codes,
            "next_action": _summary_next_action(run),
        },
    }


def _parse_source(source: dict[str, Any]) -> MeasurementRecordRunningInspectionRequest:
    if source.get("running_inspection_schema") != RUNNING_INSPECTION_SCHEMA:
        raise ValueError(f"running inspection source schema must be {RUNNING_INSPECTION_SCHEMA}")
    request = _require_dict(source, "running_inspection_request")
    paths = request.get("update_receipt_paths", [])
    if not isinstance(paths, list):
        raise ValueError("running inspection update_receipt_paths must be a list")
    return MeasurementRecordRunningInspectionRequest(
        request_id=_require_text(request, "request_id"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        writer_receipt_path=_require_text(request, "writer_receipt_path"),
        update_receipt_paths=tuple(validate_text(path, "update_receipt_path") for path in paths),
        expected_total_rows=_optional_positive_int(request, "expected_total_rows"),
        preview_row_limit=_optional_positive_int(request, "preview_row_limit") or 5,
    )


def _read_creation_manifest(
    root: Path,
    request: MeasurementRecordRunningInspectionRequest,
) -> dict[str, Any]:
    manifest_path = _path_under(root, request.creation_manifest_path)
    _ensure_no_symlink_parents(root, request.creation_manifest_path, "running inspection manifest")
    if manifest_path.is_symlink():
        raise ValueError("running inspection manifest must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("running inspection requires an existing creation manifest") from exc
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("running inspection manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("running inspection record_id must match creation manifest")
    if record.get("lifecycle_state") != "in_progress":
        raise ValueError("running inspection requires an in_progress creation manifest")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("running inspection record_dir must match creation manifest")
    if storage.get("manifest_path") != request.creation_manifest_path:
        raise ValueError("running inspection manifest_path must match creation manifest")
    return manifest


def _read_writer_receipt(
    root: Path,
    request: MeasurementRecordRunningInspectionRequest,
) -> dict[str, Any]:
    receipt_path = _path_under(root, request.writer_receipt_path)
    _ensure_no_symlink_parents(root, request.writer_receipt_path, "running inspection receipt")
    if receipt_path.is_symlink():
        raise ValueError("running inspection writer receipt must not be a symlink")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("running inspection requires an existing writer receipt") from exc
    if receipt.get("schema") != WRITER_RECEIPT_SCHEMA:
        raise ValueError("running inspection writer receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("running inspection record_id must match writer receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("running inspection record_dir must match writer receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError("running inspection creation manifest path must match writer receipt")
    writer_request = _require_dict(receipt, "writer_request")
    if writer_request.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError("running inspection writer_receipt_path must match writer receipt")
    primary_data = _require_dict(receipt, "primary_data")
    primary_path = validate_text(primary_data.get("path"), "writer receipt primary_data path")
    validate_relative_path(primary_path, "writer receipt primary_data path")
    _validate_strict_child_path(
        primary_path,
        request.record_dir,
        "writer receipt primary_data path",
    )
    if primary_data.get("format") != "csv_table":
        raise ValueError("running inspection primary data format is unsupported")
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
    request: MeasurementRecordRunningInspectionRequest,
    writer_receipt: dict[str, Any],
) -> bytes:
    primary = writer_receipt["primary_data"]
    primary_path = primary["path"]
    _ensure_no_symlink_parents(root, primary_path, "running inspection primary data")
    target = _path_under(root, primary_path)
    if target.is_symlink():
        raise ValueError("running inspection primary data must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("running inspection primary data is unavailable") from exc
    if _sha256(content) != primary["digest"]:
        raise ValueError("running inspection primary data digest does not match writer receipt")
    if len(content) != primary["size_bytes"]:
        raise ValueError("running inspection primary data size does not match writer receipt")
    _validate_strict_child_path(primary_path, request.record_dir, "running inspection primary data")
    return content


def _read_update_receipts_and_segments(
    root: Path,
    request: MeasurementRecordRunningInspectionRequest,
    writer_receipt: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[bytes]]:
    receipts: list[dict[str, Any]] = []
    segments: list[bytes] = []
    previous_total = writer_receipt["primary_data"]["rows_recorded"]
    previous_receipt_path: str | None = None
    previous_receipt: dict[str, Any] | None = None
    seen_update_ids: set[str] = set()
    for path in request.update_receipt_paths:
        receipt = _read_update_receipt(root, request, path, writer_receipt)
        update_request = _require_dict(receipt, "update_request")
        update_id = validate_text(update_request.get("update_id"), "update receipt update_id")
        validate_public_identifier(update_id, "update receipt update_id")
        if update_id in seen_update_ids:
            raise ValueError("running inspection update_id values must be unique")
        _validate_previous_receipt_link(
            receipt,
            expected_previous_path=previous_receipt_path,
            expected_previous_receipt=previous_receipt,
        )
        seen_update_ids.add(update_id)
        append_chunk = _require_dict(receipt, "append_chunk")
        if append_chunk.get("previous_total_rows_recorded") != previous_total:
            raise ValueError("running inspection append totals must be contiguous")
        previous_total = _validate_positive_integer(
            append_chunk.get("total_rows_recorded"),
            "update receipt append total_rows_recorded",
        )
        segment = _read_append_segment(root, request, receipt)
        receipts.append(receipt)
        segments.append(segment)
        previous_receipt_path = path
        previous_receipt = receipt
    return receipts, segments


def _read_update_receipt(
    root: Path,
    request: MeasurementRecordRunningInspectionRequest,
    receipt_path: str,
    writer_receipt: dict[str, Any],
) -> dict[str, Any]:
    path = _path_under(root, receipt_path)
    _ensure_no_symlink_parents(root, receipt_path, "running inspection update receipt")
    if path.is_symlink():
        raise ValueError("running inspection update receipt must not be a symlink")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("running inspection update receipt is unavailable") from exc
    if receipt.get("schema") != UPDATE_RECEIPT_SCHEMA:
        raise ValueError("running inspection update receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("running inspection record_id must match update receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("running inspection record_dir must match update receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError("running inspection manifest path must match update receipt")
    if record.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError("running inspection writer receipt path must match update receipt")
    update_request = _require_dict(receipt, "update_request")
    if update_request.get("update_receipt_path") != receipt_path:
        raise ValueError("running inspection update receipt path must match receipt")
    current = _require_dict(receipt, "current_primary_data")
    for field in ("path", "digest", "size_bytes", "rows_recorded"):
        if current.get(field) != writer_receipt["primary_data"].get(field):
            raise ValueError("running inspection current primary data must match writer receipt")
    return receipt


def _validate_previous_receipt_link(
    receipt: dict[str, Any],
    *,
    expected_previous_path: str | None,
    expected_previous_receipt: dict[str, Any] | None,
) -> None:
    update_request = _require_dict(receipt, "update_request")
    if update_request.get("previous_update_receipt_path") != expected_previous_path:
        raise ValueError("running inspection previous update receipt path must match chain")
    previous_ref = receipt.get("previous_update_receipt")
    if expected_previous_receipt is None:
        if previous_ref is not None:
            raise ValueError("running inspection first update receipt must not declare previous")
        return
    if not isinstance(previous_ref, dict):
        raise ValueError("running inspection previous update receipt ref is required")
    expected_ref = _update_receipt_ref(expected_previous_receipt)
    for field in (
        "record_id",
        "update_id",
        "update_receipt_path",
        "append_segment_path",
        "total_rows_recorded",
    ):
        if previous_ref.get(field) != expected_ref.get(field):
            raise ValueError("running inspection previous update receipt ref must match chain")


def _read_append_segment(
    root: Path,
    request: MeasurementRecordRunningInspectionRequest,
    receipt: dict[str, Any],
) -> bytes:
    append_segment = _require_dict(receipt, "append_segment")
    segment_path = validate_text(append_segment.get("path"), "append segment path")
    validate_relative_path(segment_path, "append segment path")
    _validate_strict_child_path(segment_path, request.record_dir, "append segment path")
    if append_segment.get("format") != "csv_table":
        raise ValueError("running inspection append segment format is unsupported")
    validate_sha256_digest(append_segment.get("digest"), "append segment digest")
    _validate_non_negative_integer(append_segment.get("size_bytes"), "append segment size_bytes")
    _ensure_no_symlink_parents(root, segment_path, "running inspection append segment")
    target = _path_under(root, segment_path)
    if target.is_symlink():
        raise ValueError("running inspection append segment must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("running inspection append segment is unavailable") from exc
    if _sha256(content) != append_segment["digest"]:
        raise ValueError("running inspection append segment digest does not match receipt")
    if len(content) != append_segment["size_bytes"]:
        raise ValueError("running inspection append segment size does not match receipt")
    return content


def _combine_visible_content(primary_content: bytes, append_segments: list[bytes]) -> bytes:
    content = primary_content
    for segment in append_segments:
        if content and not content.endswith(b"\n"):
            content += b"\n"
        content += segment
    return content


def _validate_append_segment_tables(primary_content: bytes, append_segments: list[bytes]) -> None:
    if not append_segments:
        return
    header = _read_csv_header(primary_content, owner="running inspection primary table")
    for segment in append_segments:
        decoded = _decode_csv(segment)
        reader = csv.reader(io.StringIO(decoded, newline=""))
        row_seen = False
        for row in reader:
            row_seen = True
            if row == header:
                raise ValueError("running inspection append segment must not repeat CSV header")
            if len(row) != len(header):
                raise ValueError(
                    "running inspection append segment rows must match the primary CSV header"
                )
        if not row_seen:
            raise ValueError("running inspection append segment must contain rows")


def _read_csv_header(content: bytes, *, owner: str) -> list[str]:
    decoded = _decode_csv(content)
    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError(f"{owner} requires a CSV header") from exc
    if not header:
        raise ValueError(f"{owner} requires a CSV header")
    for index, name in enumerate(header):
        if not isinstance(name, str) or name.strip() == "":
            raise ValueError(f"{owner} column {index} name must be non-blank")
    if len(set(header)) != len(header):
        raise ValueError(f"{owner} requires unique CSV headers")
    return header


def _read_table(
    content: bytes,
    *,
    source: str,
    declared_row_count: int,
    preview_row_limit: int,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    decoded = _decode_csv(content)
    reader = csv.reader(io.StringIO(decoded, newline=""))
    header = _read_csv_header(content, owner="running inspection primary table")
    next(reader, None)

    rows = []
    for row in reader:
        if len(row) != len(header):
            raise ValueError("running inspection table rows must match the CSV header")
        rows.append(dict(zip(header, row, strict=True)))

    findings: list[dict[str, str]] = []
    if declared_row_count != len(rows):
        findings.append(
            {
                "code": "visible_row_count_mismatch",
                "severity": "review",
                "target": source,
                "message": "Visible row count differs from declared append receipt progress.",
            }
        )

    return (
        {
            "table_schema": "measurement_record_running_primary_table_read_v0",
            "source": source,
            "format": "csv_table",
            "classification": (
                "in_progress_table_review_needed" if findings else "in_progress_table_ready"
            ),
            "columns": [
                {
                    "name": name,
                    "position": position,
                    "declared": False,
                    "role": "undeclared",
                    "unit": None,
                }
                for position, name in enumerate(header)
            ],
            "row_count": len(rows),
            "declared_row_count": declared_row_count,
            "rows": copy.deepcopy(rows),
            "preview": {
                "row_limit": preview_row_limit,
                "columns": list(header),
                "rows": copy.deepcopy(rows[:preview_row_limit]),
            },
        },
        findings,
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


def _update_receipt_ref(receipt: dict[str, Any]) -> dict[str, Any]:
    record = _require_dict(receipt, "record")
    update_request = _require_dict(receipt, "update_request")
    append_chunk = _require_dict(receipt, "append_chunk")
    append_segment = _require_dict(receipt, "append_segment")
    return {
        "schema": receipt.get("schema"),
        "record_id": record.get("record_id"),
        "update_id": update_request.get("update_id"),
        "update_receipt_path": update_request.get("update_receipt_path"),
        "append_segment_path": append_segment.get("path"),
        "total_rows_recorded": append_chunk.get("total_rows_recorded"),
    }


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "running inspection path")


def _decode_csv(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("running inspection primary table must be utf-8 CSV") from exc


def _validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _optional_positive_int(value: dict[str, Any], field: str) -> int | None:
    if field not in value:
        return None
    return _validate_positive_integer(value[field], field)


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _summary_next_action(run: MeasurementRecordRunningInspectionRun) -> str:
    if run.review_findings:
        return "review_running_inspection_findings"
    if run.progress["remaining_rows"] == 0:
        return "ready_for_later_finalization_decision"
    return "continue_monitoring_in_progress_record"
