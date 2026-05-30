"""Append one reviewed segment to an in-progress measurement record."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
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
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.creation import (
    CANDIDATE_MANIFEST_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.writer_integration import (
    WRITER_RECEIPT_SCHEMA,
    validate_positive_integer,
    validate_sha256_digest,
)

IN_PROGRESS_UPDATE_SCHEMA = "scopecat.measurement_record_in_progress_update.v0"
UPDATE_RECEIPT_SCHEMA = "measurement_record_update_receipt_candidate_v0"
IN_PROGRESS_UPDATE_POLICY = {
    "workflow_authority": "approved_in_progress_update_request",
    "record_authority": "existing_in_progress_creation_manifest",
    "writer_receipt_authority": "record_local_writer_receipt",
    "storage_authority": "caller_provided_storage_root",
    "update_behavior": "append_segment_and_receipt_only",
    "primary_data_materialization": "not_merged",
    "record_manifest": "read_only_creation_manifest_continuity_check",
    "read_model_refresh": "not_performed",
    "collision_policy": "no_overwrite",
    "rollback": "best_effort_synchronous_cleanup",
    "storage_root_concurrency": "not_supported",
}
DOES_NOT_CLAIM = [
    "final_storage_schema",
    "manifest_replacement",
    "primary_data_merge_or_compaction",
    "read_model_refresh",
    "lifecycle_finalization",
    "conflict_resolution",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "schema_inference",
    "scientific_validity",
]


@dataclass(frozen=True)
class MeasurementRecordAppendChunk:
    """Declared append chunk for an in-progress record update."""

    chunk_id: str
    sequence: int
    event_id: str
    content_ref: str
    declared_digest: str
    size_bytes: int
    rows_recorded: int
    previous_total_rows_recorded: int
    total_rows_recorded: int

    def __post_init__(self) -> None:
        validate_public_identifier(self.chunk_id, "append chunk chunk_id")
        validate_positive_integer(self.sequence, "append chunk sequence")
        validate_public_identifier(self.event_id, "append chunk event_id")
        validate_relative_path(self.content_ref, "append chunk content_ref")
        validate_sha256_digest(self.declared_digest, "append chunk declared_digest")
        validate_positive_integer(self.size_bytes, "append chunk size_bytes")
        validate_positive_integer(self.rows_recorded, "append chunk rows_recorded")
        _validate_non_negative_integer(
            self.previous_total_rows_recorded,
            "append chunk previous_total_rows_recorded",
        )
        validate_positive_integer(self.total_rows_recorded, "append chunk total_rows_recorded")
        if self.total_rows_recorded != self.previous_total_rows_recorded + self.rows_recorded:
            raise ValueError("append chunk total must equal previous total plus rows_recorded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "content_ref": self.content_ref,
            "declared_digest": self.declared_digest,
            "size_bytes": self.size_bytes,
            "rows_recorded": self.rows_recorded,
            "previous_total_rows_recorded": self.previous_total_rows_recorded,
            "total_rows_recorded": self.total_rows_recorded,
        }


@dataclass(frozen=True)
class MeasurementRecordInProgressUpdateRequest:
    """Approved request to append one segment to an in-progress record."""

    request_id: str
    approval_state: str
    update_id: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    append_segment_path: str
    update_receipt_path: str
    primary_data_format: str
    expected_total_rows: int
    append_chunk: MeasurementRecordAppendChunk

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "in-progress update request_id")
        if self.approval_state not in {"approved", "rejected", "needs_review"}:
            raise ValueError("in-progress update approval_state is unsupported")
        validate_public_identifier(self.update_id, "in-progress update update_id")
        validate_public_identifier(self.record_id, "in-progress update record_id")
        validate_relative_path(self.record_dir, "in-progress update record_dir")
        validate_relative_path(
            self.writer_receipt_path,
            "in-progress update writer_receipt_path",
        )
        validate_relative_path(
            self.append_segment_path,
            "in-progress update append_segment_path",
        )
        validate_relative_path(
            self.update_receipt_path,
            "in-progress update update_receipt_path",
        )
        validate_public_identifier(
            self.primary_data_format,
            "in-progress update primary_data_format",
        )
        if self.primary_data_format != "csv_table":
            raise ValueError("in-progress update primary_data_format is unsupported")
        validate_positive_integer(
            self.expected_total_rows, "in-progress update expected_total_rows"
        )
        if self.append_chunk.total_rows_recorded > self.expected_total_rows:
            raise ValueError("append chunk total must not exceed expected_total_rows")
        for path, owner in (
            (self.writer_receipt_path, "in-progress update writer_receipt_path"),
            (self.append_segment_path, "in-progress update append_segment_path"),
            (self.update_receipt_path, "in-progress update update_receipt_path"),
        ):
            _validate_strict_child_path(path, self.record_dir, owner)
        _validate_non_overlapping_paths(
            (
                self.append_segment_path,
                self.update_receipt_path,
            ),
            "in-progress update output paths",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "update_id": self.update_id,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.manifest_path,
            "writer_receipt_path": self.writer_receipt_path,
            "append_segment_path": self.append_segment_path,
            "update_receipt_path": self.update_receipt_path,
            "primary_data_format": self.primary_data_format,
            "expected_total_rows": self.expected_total_rows,
            "append_chunk": self.append_chunk.to_dict(),
        }


@dataclass(frozen=True)
class MeasurementRecordInProgressUpdateRun:
    """Local receipt for one in-progress append update."""

    request: MeasurementRecordInProgressUpdateRequest
    storage_root: Path
    content_root: Path
    record_manifest: dict[str, Any] | None = None
    writer_receipt: dict[str, Any] | None = None
    write_results: tuple[dict[str, Any], ...] = ()
    rollback_performed: bool = False
    update_error: str | None = None

    @property
    def updated(self) -> bool:
        return self.classification == "appended_to_in_progress_record"

    @property
    def classification(self) -> str:
        if self.update_error is not None:
            if self.rollback_performed:
                return "rolled_back_after_in_progress_update_failure"
            return "blocked_before_in_progress_update"
        if not self.request.approved:
            return "blocked_before_in_progress_update"
        return "appended_to_in_progress_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_in_progress_update_receipt",
            "in_progress_update_policy": copy.deepcopy(IN_PROGRESS_UPDATE_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_in_progress_update_request",
                    "read_creation_manifest",
                    "read_writer_receipt",
                    *([] if not self.updated else ["write_append_segment", "write_update_receipt"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "record_manifest": _manifest_ref(self.record_manifest),
            "writer_receipt": _writer_receipt_ref(self.writer_receipt),
            "in_progress_update": {
                "performed": self.updated,
                "rollback_performed": self.rollback_performed,
                "update_error": self.update_error,
                "storage_root": str(self.storage_root),
                "content_root": str(self.content_root),
                "write_results": [copy.deepcopy(item) for item in self.write_results],
            },
        }


def append_in_progress_measurement_record(
    source: dict[str, Any],
    *,
    content_root: str | Path,
    storage_root: str | Path,
) -> MeasurementRecordInProgressUpdateRun:
    """Append one segment to an in-progress record from a raw source."""

    request = _parse_source(source)
    return append_in_progress_measurement_record_from_request(
        request,
        content_root=content_root,
        storage_root=storage_root,
    )


def append_in_progress_measurement_record_from_request(
    request: MeasurementRecordInProgressUpdateRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    file_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordInProgressUpdateRun:
    """Append one segment to an in-progress record from a typed request."""

    content = _existing_directory_root(Path(content_root), "in-progress update content root")
    storage = _existing_directory_root(Path(storage_root), "in-progress update storage root")
    manifest = _read_creation_manifest(storage, request)
    writer_receipt = _read_writer_receipt(storage, request)
    _preflight_current_primary(storage, request, writer_receipt)
    if not request.approved:
        return MeasurementRecordInProgressUpdateRun(
            request=request,
            storage_root=storage,
            content_root=content,
            record_manifest=manifest,
            writer_receipt=writer_receipt,
        )

    try:
        segment_content = _read_append_chunk(content, request)
        segment_digest = _sha256(segment_content)
        receipt_content = _update_receipt_bytes(
            request=request,
            writer_receipt=writer_receipt,
            segment_digest=segment_digest,
            segment_size=len(segment_content),
        )
        receipt_digest = _sha256(receipt_content)
        writer = file_writer or _write_new_file
        _write_new_files_transaction(
            storage,
            [
                (request.append_segment_path, segment_content),
                (request.update_receipt_path, receipt_content),
            ],
            file_writer=writer,
        )
    except _InProgressUpdateFailure as exc:
        return MeasurementRecordInProgressUpdateRun(
            request=request,
            storage_root=storage,
            content_root=content,
            record_manifest=manifest,
            writer_receipt=writer_receipt,
            rollback_performed=exc.rollback_performed,
            update_error=str(exc),
        )

    return MeasurementRecordInProgressUpdateRun(
        request=request,
        storage_root=storage,
        content_root=content,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        write_results=(
            {
                "path": request.append_segment_path,
                "kind": "append_segment",
                "result": "written",
                "bytes_written": len(segment_content),
                "digest": segment_digest,
                "does_not_claim": "merged_primary_data_or_schema_validity",
            },
            {
                "path": request.update_receipt_path,
                "kind": "update_receipt",
                "result": "written",
                "bytes_written": len(receipt_content),
                "digest": receipt_digest,
                "does_not_claim": "manifest_replacement_or_read_model_refresh",
            },
        ),
    )


def _parse_source(source: dict[str, Any]) -> MeasurementRecordInProgressUpdateRequest:
    if source.get("in_progress_update_schema") != IN_PROGRESS_UPDATE_SCHEMA:
        raise ValueError(f"in-progress update source schema must be {IN_PROGRESS_UPDATE_SCHEMA}")
    if source.get("in_progress_update_policy") != IN_PROGRESS_UPDATE_POLICY:
        raise ValueError("in-progress update source policy is unsupported")
    request = _require_dict(source, "in_progress_update_request")
    return MeasurementRecordInProgressUpdateRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        update_id=_require_text(request, "update_id"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        writer_receipt_path=_require_text(request, "writer_receipt_path"),
        append_segment_path=_require_text(request, "append_segment_path"),
        update_receipt_path=_require_text(request, "update_receipt_path"),
        primary_data_format=_require_text(request, "primary_data_format"),
        expected_total_rows=_require_int(request, "expected_total_rows"),
        append_chunk=_parse_append_chunk(_require_dict(request, "append_chunk")),
    )


def _parse_append_chunk(value: dict[str, Any]) -> MeasurementRecordAppendChunk:
    return MeasurementRecordAppendChunk(
        chunk_id=_require_text(value, "chunk_id"),
        sequence=_require_int(value, "sequence"),
        event_id=_require_text(value, "event_id"),
        content_ref=_require_text(value, "content_ref"),
        declared_digest=_require_text(value, "declared_digest"),
        size_bytes=_require_int(value, "size_bytes"),
        rows_recorded=_require_int(value, "rows_recorded"),
        previous_total_rows_recorded=_require_int(value, "previous_total_rows_recorded"),
        total_rows_recorded=_require_int(value, "total_rows_recorded"),
    )


def _read_creation_manifest(
    root: Path,
    request: MeasurementRecordInProgressUpdateRequest,
) -> dict[str, Any]:
    manifest_path = _path_under(root, request.manifest_path)
    _ensure_no_symlink_parents(root, request.manifest_path, "in-progress update manifest")
    if manifest_path.is_symlink():
        raise ValueError("in-progress update manifest must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("in-progress update requires an existing creation manifest") from exc
    if manifest.get("schema") != CANDIDATE_MANIFEST_SCHEMA:
        raise ValueError("in-progress update manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("in-progress update record_id must match creation manifest")
    if record.get("lifecycle_state") != "in_progress":
        raise ValueError("in-progress update requires an in_progress creation manifest")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("in-progress update record_dir must match creation manifest")
    if storage.get("manifest_path") != request.manifest_path:
        raise ValueError("in-progress update manifest_path must match creation manifest")
    return manifest


def _read_writer_receipt(
    root: Path,
    request: MeasurementRecordInProgressUpdateRequest,
) -> dict[str, Any]:
    receipt_path = _path_under(root, request.writer_receipt_path)
    _ensure_no_symlink_parents(root, request.writer_receipt_path, "in-progress update receipt")
    if receipt_path.is_symlink():
        raise ValueError("in-progress update writer receipt must not be a symlink")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("in-progress update requires an existing writer receipt") from exc
    if receipt.get("schema") != WRITER_RECEIPT_SCHEMA:
        raise ValueError("in-progress update writer receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("in-progress update record_id must match writer receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("in-progress update record_dir must match writer receipt")
    if record.get("creation_manifest_path") != request.manifest_path:
        raise ValueError("in-progress update creation manifest path must match writer receipt")
    writer_request = _require_dict(receipt, "writer_request")
    if writer_request.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError("in-progress update writer_receipt_path must match writer receipt")
    primary_data = _require_dict(receipt, "primary_data")
    primary_path = validate_text(primary_data.get("path"), "writer receipt primary_data path")
    validate_relative_path(primary_path, "writer receipt primary_data path")
    _validate_strict_child_path(
        primary_path,
        request.record_dir,
        "writer receipt primary_data path",
    )
    if primary_data.get("format") != request.primary_data_format:
        raise ValueError("in-progress update primary_data_format must match writer receipt")
    validate_sha256_digest(primary_data.get("digest"), "writer receipt primary_data digest")
    _validate_non_negative_integer(
        primary_data.get("size_bytes"),
        "writer receipt primary_data size_bytes",
    )
    _validate_non_negative_integer(
        primary_data.get("rows_recorded"),
        "writer receipt primary_data rows_recorded",
    )
    if primary_data["rows_recorded"] != request.append_chunk.previous_total_rows_recorded:
        raise ValueError("append chunk previous total must match writer receipt rows_recorded")
    return receipt


def _preflight_current_primary(
    root: Path,
    request: MeasurementRecordInProgressUpdateRequest,
    writer_receipt: dict[str, Any],
) -> None:
    primary_data = writer_receipt["primary_data"]
    primary_path = primary_data["path"]
    _ensure_no_symlink_parents(root, primary_path, "in-progress update primary data")
    target = _path_under(root, primary_path)
    if target.is_symlink():
        raise ValueError("in-progress update primary data must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("in-progress update primary data is unavailable") from exc
    if _sha256(content) != primary_data["digest"]:
        raise ValueError("in-progress update primary data digest does not match writer receipt")
    if len(content) != primary_data["size_bytes"]:
        raise ValueError("in-progress update primary data size does not match writer receipt")
    _validate_strict_child_path(primary_path, request.record_dir, "in-progress update primary data")


def _read_append_chunk(
    content_root: Path,
    request: MeasurementRecordInProgressUpdateRequest,
) -> bytes:
    chunk = request.append_chunk
    _ensure_no_symlink_parents(content_root, chunk.content_ref, "in-progress update append chunk")
    target = _path_under(content_root, chunk.content_ref)
    if target.is_symlink():
        raise ValueError("in-progress update append chunk must not be a symlink")
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("in-progress update append chunk is unavailable") from exc
    if _sha256(content) != chunk.declared_digest:
        raise ValueError("in-progress update append chunk digest does not match")
    if len(content) != chunk.size_bytes:
        raise ValueError("in-progress update append chunk size does not match")
    return content


def _update_receipt_bytes(
    *,
    request: MeasurementRecordInProgressUpdateRequest,
    writer_receipt: dict[str, Any],
    segment_digest: str,
    segment_size: int,
) -> bytes:
    receipt = {
        "schema": UPDATE_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.manifest_path,
            "writer_receipt_path": request.writer_receipt_path,
        },
        "update_request": {
            "request_id": request.request_id,
            "update_id": request.update_id,
            "append_segment_path": request.append_segment_path,
            "update_receipt_path": request.update_receipt_path,
            "primary_data_format": request.primary_data_format,
            "expected_total_rows": request.expected_total_rows,
        },
        "current_primary_data": {
            "path": writer_receipt["primary_data"]["path"],
            "digest": writer_receipt["primary_data"]["digest"],
            "size_bytes": writer_receipt["primary_data"]["size_bytes"],
            "rows_recorded": writer_receipt["primary_data"]["rows_recorded"],
        },
        "append_segment": {
            "path": request.append_segment_path,
            "format": request.primary_data_format,
            "digest": segment_digest,
            "size_bytes": segment_size,
        },
        "append_chunk": request.append_chunk.to_dict(),
        "does_not_claim": list(DOES_NOT_CLAIM),
    }
    return json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _write_new_files_transaction(
    root: Path,
    files: list[tuple[str, bytes]],
    *,
    file_writer: Callable[[Path, bytes], None],
) -> None:
    try:
        for relative_path, _content in files:
            if _target_exists(root, relative_path):
                raise _InProgressUpdateFailure(
                    "in-progress update target already exists",
                    rollback_performed=False,
                )
            _ensure_no_symlink_parents(root, relative_path, "in-progress update target")
    except _InProgressUpdateFailure:
        raise
    except Exception as exc:
        raise _InProgressUpdateFailure(str(exc), rollback_performed=False) from exc

    written_paths: list[str] = []
    try:
        for relative_path, content in files:
            file_writer(_path_under(root, relative_path), content)
            written_paths.append(relative_path)
    except Exception as exc:
        _rollback_written_files(root, written_paths)
        raise _InProgressUpdateFailure(
            f"in-progress update write failed: {exc}",
            rollback_performed=bool(written_paths),
        ) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)


def _rollback_written_files(root: Path, written_paths: list[str]) -> None:
    for relative_path in reversed(written_paths):
        try:
            _path_under(root, relative_path).unlink()
        except FileNotFoundError:
            pass


class _InProgressUpdateFailure(RuntimeError):
    def __init__(self, message: str, *, rollback_performed: bool) -> None:
        super().__init__(message)
        self.rollback_performed = rollback_performed


def _manifest_ref(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    record = _require_dict(manifest, "record")
    storage = _require_dict(manifest, "storage")
    return {
        "schema": manifest.get("schema"),
        "record_id": record.get("record_id"),
        "lifecycle_state": record.get("lifecycle_state"),
        "record_dir": storage.get("record_dir"),
        "manifest_path": storage.get("manifest_path"),
    }


def _writer_receipt_ref(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
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
    return _path_under_common(root, relative_path, "in-progress update path")


def _target_exists(root: Path, relative_path: str) -> bool:
    return (
        _path_under(root, relative_path).exists() or _path_under(root, relative_path).is_symlink()
    )


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _require_int(value: dict[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item
