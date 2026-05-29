"""Attach writer-produced primary data to a created measurement record."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records.creation import (
    CANDIDATE_MANIFEST_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)

WRITER_INTEGRATION_SCHEMA = "scopecat.measurement_record_writer_integration.v0"
WRITER_RECEIPT_SCHEMA = "measurement_record_writer_receipt_candidate_v0"
WRITER_INTEGRATION_POLICY = {
    "workflow_authority": "approved_measurement_record_writer_request",
    "record_authority": "existing_measurement_record_creation_manifest",
    "storage_authority": "caller_provided_storage_root",
    "primary_data_materialization": "write_declared_chunks_to_created_record",
    "record_manifest": "read_only_creation_manifest_continuity_check",
    "writer_receipt": "write_record_local_writer_receipt",
    "collision_policy": "no_overwrite",
    "rollback": "best_effort_synchronous_cleanup",
    "storage_root_concurrency": "not_supported",
    "final_lifecycle_state": "not_defined",
    "read_model_refresh": "not_performed",
    "existing_record_update": "not_performed",
}
DOES_NOT_CLAIM = [
    "final_storage_schema",
    "manifest_replacement",
    "read_model_refresh",
    "lifecycle_finalization",
    "existing_record_update_or_merge",
    "conflict_resolution",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "schema_inference",
    "scientific_validity",
]

_SHA256_PREFIX = "sha256:"
_SUPPORTED_PRIMARY_DATA_FORMATS = {"csv_table"}
_WRITABLE_LIFECYCLE_STATES = {"created", "in_progress"}


@dataclass(frozen=True)
class MeasurementRecordWriterChunk:
    """Declared writer chunk to materialize as primary data."""

    chunk_id: str
    sequence: int
    event_id: str
    content_ref: str
    declared_digest: str
    size_bytes: int
    rows_recorded: int
    total_rows_recorded: int

    def __post_init__(self) -> None:
        validate_public_identifier(self.chunk_id, "writer chunk chunk_id")
        validate_positive_integer(self.sequence, "writer chunk sequence")
        validate_public_identifier(self.event_id, "writer chunk event_id")
        validate_relative_path(self.content_ref, "writer chunk content_ref")
        validate_sha256_digest(self.declared_digest, "writer chunk declared_digest")
        validate_positive_integer(self.size_bytes, "writer chunk size_bytes")
        validate_positive_integer(self.rows_recorded, "writer chunk rows_recorded")
        validate_positive_integer(self.total_rows_recorded, "writer chunk total_rows_recorded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "content_ref": self.content_ref,
            "declared_digest": self.declared_digest,
            "size_bytes": self.size_bytes,
            "rows_recorded": self.rows_recorded,
            "total_rows_recorded": self.total_rows_recorded,
        }


@dataclass(frozen=True)
class MeasurementRecordWriterRequest:
    """Approved request to write primary data into a created record."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    primary_data_path: str
    writer_receipt_path: str
    primary_data_format: str
    expected_rows: int
    chunks: tuple[MeasurementRecordWriterChunk, ...]

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "writer request request_id")
        if self.approval_state not in {"approved", "rejected", "needs_review"}:
            raise ValueError("writer request approval_state is unsupported")
        validate_public_identifier(self.record_id, "writer request record_id")
        validate_relative_path(self.record_dir, "writer request record_dir")
        validate_relative_path(self.primary_data_path, "writer request primary_data_path")
        validate_relative_path(self.writer_receipt_path, "writer request writer_receipt_path")
        validate_public_identifier(self.primary_data_format, "writer request primary_data_format")
        if self.primary_data_format not in _SUPPORTED_PRIMARY_DATA_FORMATS:
            raise ValueError("writer request primary_data_format is unsupported")
        validate_positive_integer(self.expected_rows, "writer request expected_rows")
        if not self.chunks:
            raise ValueError("writer request chunks are required")
        _validate_chunk_sequence(self.chunks, self.expected_rows)
        _validate_strict_child_path(
            self.primary_data_path,
            self.record_dir,
            "writer request primary_data_path",
        )
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "writer request writer_receipt_path",
        )
        _validate_non_overlapping_paths(
            (self.primary_data_path, self.writer_receipt_path),
            "writer request output paths",
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
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.manifest_path,
            "primary_data_path": self.primary_data_path,
            "writer_receipt_path": self.writer_receipt_path,
            "primary_data_format": self.primary_data_format,
            "expected_rows": self.expected_rows,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


@dataclass(frozen=True)
class MeasurementRecordWriterRun:
    """Local receipt for writer integration with a created record."""

    request: MeasurementRecordWriterRequest
    storage_root: Path
    content_root: Path
    record_manifest: dict[str, Any] | None = None
    write_results: tuple[dict[str, Any], ...] = ()
    rollback_performed: bool = False
    write_error: str | None = None

    @property
    def written(self) -> bool:
        return self.classification == "written_to_created_record"

    @property
    def classification(self) -> str:
        if self.write_error is not None:
            if self.rollback_performed:
                return "rolled_back_after_writer_failure"
            return "blocked_before_writer_integration"
        if not self.request.approved:
            return "blocked_before_writer_integration"
        return "written_to_created_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_writer_integration_receipt",
            "writer_integration_policy": copy.deepcopy(WRITER_INTEGRATION_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_writer_request",
                    "read_creation_manifest",
                    *([] if not self.written else ["write_primary_data", "write_writer_receipt"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "record_manifest": _manifest_ref(self.record_manifest),
            "writer_integration": {
                "performed": self.written,
                "rollback_performed": self.rollback_performed,
                "write_error": self.write_error,
                "storage_root": str(self.storage_root),
                "content_root": str(self.content_root),
                "write_results": [copy.deepcopy(item) for item in self.write_results],
            },
        }


def write_created_record_primary_data(
    source: dict[str, Any],
    *,
    content_root: str | Path,
    storage_root: str | Path,
) -> MeasurementRecordWriterRun:
    """Write primary data into an existing created record from a raw source."""

    request = _parse_source(source)
    return write_created_record_primary_data_from_request(
        request,
        content_root=content_root,
        storage_root=storage_root,
    )


def write_created_record_primary_data_from_request(
    request: MeasurementRecordWriterRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    file_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordWriterRun:
    """Write primary data into an existing created record from a typed request."""

    content = _existing_directory_root(Path(content_root), "writer integration content root")
    storage = _existing_directory_root(Path(storage_root), "writer integration storage root")
    manifest = _read_creation_manifest(storage, request)
    if not request.approved:
        return MeasurementRecordWriterRun(
            request=request,
            storage_root=storage,
            content_root=content,
            record_manifest=manifest,
        )

    try:
        chunk_content = _preflight_chunks(request, content)
        primary_content = b"".join(content for _chunk, content in chunk_content)
        primary_digest = _sha256(primary_content)
        writer_receipt_content = _writer_receipt_bytes(
            request=request,
            manifest=manifest,
            chunk_content=chunk_content,
            primary_digest=primary_digest,
            primary_size=len(primary_content),
        )
        writer_receipt_digest = _sha256(writer_receipt_content)
        writer = file_writer or _write_new_file
        _write_new_files_transaction(
            storage,
            [
                (request.primary_data_path, primary_content),
                (request.writer_receipt_path, writer_receipt_content),
            ],
            file_writer=writer,
        )
    except _WriterIntegrationFailure as exc:
        return MeasurementRecordWriterRun(
            request=request,
            storage_root=storage,
            content_root=content,
            record_manifest=manifest,
            rollback_performed=exc.rollback_performed,
            write_error=str(exc),
        )

    return MeasurementRecordWriterRun(
        request=request,
        storage_root=storage,
        content_root=content,
        record_manifest=manifest,
        write_results=(
            {
                "path": request.primary_data_path,
                "kind": "primary_data",
                "result": "written",
                "bytes_written": len(primary_content),
                "digest": primary_digest,
                "does_not_claim": "schema_or_scientific_validity",
            },
            {
                "path": request.writer_receipt_path,
                "kind": "writer_receipt",
                "result": "written",
                "bytes_written": len(writer_receipt_content),
                "digest": writer_receipt_digest,
                "does_not_claim": "manifest_replacement_or_read_model_refresh",
            },
        ),
    )


def _parse_source(source: dict[str, Any]) -> MeasurementRecordWriterRequest:
    if source.get("writer_integration_schema") != WRITER_INTEGRATION_SCHEMA:
        raise ValueError(f"writer integration source schema must be {WRITER_INTEGRATION_SCHEMA}")
    if source.get("writer_integration_policy") != WRITER_INTEGRATION_POLICY:
        raise ValueError("writer integration source policy is unsupported")
    request = _require_dict(source, "writer_request")
    chunks = _require_list(request, "chunks")
    return MeasurementRecordWriterRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        primary_data_path=_require_text(request, "primary_data_path"),
        writer_receipt_path=_require_text(request, "writer_receipt_path"),
        primary_data_format=_require_text(request, "primary_data_format"),
        expected_rows=_require_int(request, "expected_rows"),
        chunks=tuple(_parse_chunk(chunk) for chunk in chunks),
    )


def _parse_chunk(value: Any) -> MeasurementRecordWriterChunk:
    if not isinstance(value, dict):
        raise ValueError("writer chunk must be an object")
    return MeasurementRecordWriterChunk(
        chunk_id=_require_text(value, "chunk_id"),
        sequence=_require_int(value, "sequence"),
        event_id=_require_text(value, "event_id"),
        content_ref=_require_text(value, "content_ref"),
        declared_digest=_require_text(value, "declared_digest"),
        size_bytes=_require_int(value, "size_bytes"),
        rows_recorded=_require_int(value, "rows_recorded"),
        total_rows_recorded=_require_int(value, "total_rows_recorded"),
    )


def _read_creation_manifest(root: Path, request: MeasurementRecordWriterRequest) -> dict[str, Any]:
    manifest_path = _path_under(root, request.manifest_path)
    _ensure_no_symlink_parents(root, request.manifest_path, "writer integration manifest")
    if manifest_path.is_symlink():
        raise ValueError("writer integration manifest must not be a symlink")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("writer integration requires an existing creation manifest") from exc
    if manifest.get("schema") != CANDIDATE_MANIFEST_SCHEMA:
        raise ValueError("writer integration manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("writer integration record_id must match creation manifest")
    lifecycle_state = record.get("lifecycle_state")
    if lifecycle_state not in _WRITABLE_LIFECYCLE_STATES:
        raise ValueError("writer integration lifecycle_state is not writable")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("writer integration record_dir must match creation manifest")
    if storage.get("manifest_path") != request.manifest_path:
        raise ValueError("writer integration manifest_path must match creation manifest")
    primary_data = _require_dict(manifest, "primary_data")
    if primary_data.get("state") != "not_recorded":
        raise ValueError("writer integration creation manifest primary_data must be not_recorded")
    return manifest


def _preflight_chunks(
    request: MeasurementRecordWriterRequest,
    content_root: Path,
) -> list[tuple[MeasurementRecordWriterChunk, bytes]]:
    chunk_content = []
    for chunk in sorted(request.chunks, key=lambda item: item.sequence):
        content_path = _path_under(content_root, chunk.content_ref)
        _ensure_no_symlink_parents(content_root, chunk.content_ref, "writer integration chunk")
        if content_path.is_symlink():
            raise ValueError("writer integration chunk must not be a symlink")
        try:
            content = content_path.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError("writer integration chunk is unavailable") from exc
        if _sha256(content) != chunk.declared_digest:
            raise ValueError("writer integration chunk digest does not match")
        if len(content) != chunk.size_bytes:
            raise ValueError("writer integration chunk size does not match")
        chunk_content.append((chunk, content))
    return chunk_content


def _writer_receipt_bytes(
    *,
    request: MeasurementRecordWriterRequest,
    manifest: dict[str, Any],
    chunk_content: list[tuple[MeasurementRecordWriterChunk, bytes]],
    primary_digest: str,
    primary_size: int,
) -> bytes:
    chunks = [chunk for chunk, _content in chunk_content]
    receipt = {
        "schema": WRITER_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.manifest_path,
            "creation_lifecycle_state": manifest["record"]["lifecycle_state"],
        },
        "writer_request": {
            "request_id": request.request_id,
            "primary_data_path": request.primary_data_path,
            "writer_receipt_path": request.writer_receipt_path,
            "primary_data_format": request.primary_data_format,
            "expected_rows": request.expected_rows,
        },
        "primary_data": {
            "path": request.primary_data_path,
            "format": request.primary_data_format,
            "digest": primary_digest,
            "size_bytes": primary_size,
            "rows_recorded": chunks[-1].total_rows_recorded,
        },
        "chunks": [chunk.to_dict() for chunk in chunks],
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
                raise _WriterIntegrationFailure(
                    "writer integration target already exists",
                    rollback_performed=False,
                )
            _ensure_no_symlink_parents(root, relative_path, "writer integration target")
    except _WriterIntegrationFailure:
        raise
    except Exception as exc:
        raise _WriterIntegrationFailure(str(exc), rollback_performed=False) from exc

    written_paths: list[str] = []
    try:
        for relative_path, content in files:
            file_writer(_path_under(root, relative_path), content)
            written_paths.append(relative_path)
    except Exception as exc:
        _rollback_written_files(root, written_paths)
        raise _WriterIntegrationFailure(
            f"writer integration write failed: {exc}",
            rollback_performed=bool(written_paths),
        ) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _rollback_written_files(root: Path, written_paths: list[str]) -> None:
    for relative_path in reversed(written_paths):
        try:
            _path_under(root, relative_path).unlink()
        except FileNotFoundError:
            pass


class _WriterIntegrationFailure(RuntimeError):
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


def _existing_directory_root(root: Path, owner: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    return root.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(
        *Path(validate_relative_path(relative_path, "writer integration path")).parts
    )


def _target_exists(root: Path, relative_path: str) -> bool:
    return (
        _path_under(root, relative_path).exists() or _path_under(root, relative_path).is_symlink()
    )


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    parts = Path(validate_relative_path(relative_path, label)).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def _validate_chunk_sequence(
    chunks: tuple[MeasurementRecordWriterChunk, ...],
    expected_rows: int,
) -> None:
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("writer request chunk_id values must be unique")
    event_ids = [chunk.event_id for chunk in chunks]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("writer request event_id values must be unique")
    sequences = [chunk.sequence for chunk in chunks]
    if sorted(sequences) != list(range(1, len(chunks) + 1)):
        raise ValueError("writer request chunk sequences must be contiguous")
    previous_total = 0
    for chunk in sorted(chunks, key=lambda item: item.sequence):
        if chunk.total_rows_recorded != previous_total + chunk.rows_recorded:
            raise ValueError("writer request chunk totals must match append progress")
        previous_total = chunk.total_rows_recorded
    if previous_total != expected_rows:
        raise ValueError("writer request chunks must record expected_rows")


def _validate_strict_child_path(value: str, parent: str, owner: str) -> None:
    value_parts = Path(validate_relative_path(value, owner)).parts
    parent_parts = Path(validate_relative_path(parent, f"{owner} parent")).parts
    if len(value_parts) <= len(parent_parts) or value_parts[: len(parent_parts)] != parent_parts:
        raise ValueError(f"{owner} must stay under record_dir")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    path_parts = [(path, Path(validate_relative_path(path, owner)).parts) for path in paths]
    for left_index, (left_path, left_parts) in enumerate(path_parts):
        for right_path, right_parts in path_parts[left_index + 1 :]:
            shared_length = min(len(left_parts), len(right_parts))
            if left_parts[:shared_length] == right_parts[:shared_length]:
                raise ValueError(f"{owner} must not overlap: {left_path}, {right_path}")


def validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value


def validate_sha256_digest(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_SHA256_PREFIX)
        or len(value) != len(_SHA256_PREFIX) + 64
        or any(
            character not in "0123456789abcdef" for character in value.removeprefix(_SHA256_PREFIX)
        )
    ):
        raise ValueError(f"{owner} must be a sha256-prefixed hex digest")
    return value


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_list(value: dict[str, Any], field: str) -> list[Any]:
    item = value.get(field)
    if not isinstance(item, list):
        raise ValueError(f"{field} must be a list")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _require_int(value: dict[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item
