"""Existing measurement-record append update engineering prototype.

This module validates one approved append update for an existing measurement
record. It writes only new append-segment and update-receipt files under the
declared existing record directory, guarded by a record-local lock file.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
    sha256,
    validate_non_overlapping_paths,
    validate_strict_child_path,
)
from scopecat.measurement_records.creation import (
    validate_public_identifier,
    validate_relative_path,
)
from scopecat.measurement_records.writer_integration import validate_sha256_digest

_PRIMARY_DATA_FORMATS = {"csv_table"}


@dataclass(frozen=True)
class MeasurementRecordExistingAppendChunk:
    """Declared append chunk for one existing-record update."""

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
        validate_sha256_digest(self.declared_digest, "append chunk digest")
        validate_positive_integer(self.size_bytes, "append chunk size_bytes")
        validate_positive_integer(self.rows_recorded, "append chunk rows_recorded")
        validate_non_negative_integer(
            self.previous_total_rows_recorded,
            "append chunk previous_total_rows_recorded",
        )
        validate_positive_integer(self.total_rows_recorded, "append chunk total_rows_recorded")

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

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> MeasurementRecordExistingAppendChunk:
        return cls(
            chunk_id=source["chunk_id"],
            sequence=source["sequence"],
            event_id=source["event_id"],
            content_ref=source["content_ref"],
            declared_digest=source["declared_digest"],
            size_bytes=source["size_bytes"],
            rows_recorded=source["rows_recorded"],
            previous_total_rows_recorded=source["previous_total_rows_recorded"],
            total_rows_recorded=source["total_rows_recorded"],
        )


@dataclass(frozen=True)
class MeasurementRecordExistingUpdateRequest:
    """Approved request to append new evidence under an existing record."""

    request_id: str
    update_id: str
    record_dir: str
    append_segment_path: str
    update_receipt_path: str
    lock_path: str
    append_policy: str
    collision_policy: str
    approval_state: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "existing update request_id")
        validate_public_identifier(self.update_id, "existing update update_id")
        if self.approval_state != "approved":
            raise ValueError("existing record update request must be approved")
        if self.collision_policy != "no_overwrite_new_update_files":
            raise ValueError("existing record update collision policy must refuse overwrites")
        if self.append_policy != "existing_record_append":
            raise ValueError(
                "existing record update append policy must stay existing_record_append"
            )
        validate_relative_path(self.record_dir, "update request record_dir")
        for field_name in ("append_segment_path", "update_receipt_path", "lock_path"):
            value = getattr(self, field_name)
            validate_relative_path(value, f"update request {field_name}")
            validate_strict_child_path(value, self.record_dir, f"update request {field_name}")
        record_parts = Path(
            validate_relative_path(self.record_dir, "update request record_dir")
        ).parts
        lock_parts = Path(validate_relative_path(self.lock_path, "update request lock_path")).parts
        if (
            len(lock_parts) != len(record_parts) + 1
            or lock_parts[: len(record_parts)] != record_parts
        ):
            raise ValueError("update request lock_path must be directly under record_dir")
        validate_non_overlapping_paths(
            (self.append_segment_path, self.update_receipt_path, self.lock_path),
            "existing record update output paths",
            reject_parent_child=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "update_id": self.update_id,
            "record_dir": self.record_dir,
            "append_segment_path": self.append_segment_path,
            "update_receipt_path": self.update_receipt_path,
            "lock_path": self.lock_path,
            "append_policy": self.append_policy,
            "destination": {
                "path_kind": "relative_storage_path_under_caller_root",
                "collision_policy": self.collision_policy,
            },
            "approval": {"approval_state": self.approval_state},
        }

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> MeasurementRecordExistingUpdateRequest:
        if source["destination"]["path_kind"] != "relative_storage_path_under_caller_root":
            raise ValueError("existing record update destination path kind must stay relative")
        return cls(
            request_id=source["request_id"],
            update_id=source["update_id"],
            record_dir=source["record_dir"],
            append_segment_path=source["append_segment_path"],
            update_receipt_path=source["update_receipt_path"],
            lock_path=source["lock_path"],
            append_policy=source["append_policy"],
            collision_policy=source["destination"]["collision_policy"],
            approval_state=source["approval"]["approval_state"],
        )


@dataclass(frozen=True, init=False)
class MeasurementRecordExistingUpdateRun:
    """Result for one existing-record append update run."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def classification(self) -> str:
        return self._summary["measurement_record"]["classification"]

    @property
    def write_results(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["write_results"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def append_existing_measurement_record_from_request(
    source: dict[str, Any],
    *,
    content_root: Path,
    storage_root: Path,
) -> MeasurementRecordExistingUpdateRun:
    """Append one new update segment and receipt under an existing record."""
    _validate_source(source)
    content_root_resolved = existing_directory_root(content_root, "existing record update content")
    storage_root_resolved = existing_directory_root(storage_root, "existing record update storage")
    request = MeasurementRecordExistingUpdateRequest.from_dict(source["update_request"])
    _ensure_existing_record_dir(source, storage_root_resolved)
    lock_content = _acquire_lock(storage_root_resolved, request)
    try:
        current = _preflight_current_record(source, storage_root_resolved)
        segment_content = _read_append_chunk(source, content_root_resolved)

        if _target_exists(storage_root_resolved, request.append_segment_path):
            raise ValueError("existing record update append segment already exists")
        if _target_exists(storage_root_resolved, request.update_receipt_path):
            raise ValueError("existing record update receipt already exists")

        write_results = _write_update_files(source, request, storage_root_resolved, segment_content)
    finally:
        _release_owned_lock(storage_root_resolved, request.lock_path, lock_content)

    return MeasurementRecordExistingUpdateRun(
        summary=_build_summary(source, request, current, write_results)
    )


def append_existing_measurement_record(
    source: dict[str, Any],
    *,
    content_root: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Raw-dictionary adapter for existing measurement-record append updates."""
    return append_existing_measurement_record_from_request(
        source,
        content_root=content_root,
        storage_root=storage_root,
    ).to_dict()


def _validate_source(source: dict[str, Any]) -> None:
    request = MeasurementRecordExistingUpdateRequest.from_dict(source["update_request"])
    chunk = MeasurementRecordExistingAppendChunk.from_dict(source["append_chunk"])
    current = source["current_record"]
    record = source["measurement_record"]

    validate_public_identifier(record["measurement_record_id"], "measurement record id")
    validate_public_identifier(record["experiment_type"], "measurement experiment_type")
    validate_public_identifier(record["target"], "measurement target")
    validate_positive_integer(record["expected_points"], "measurement record expected_points")

    if current["primary_data_format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("existing record update primary data format is unsupported")
    for field_name in ("record_dir", "manifest_path", "primary_data_path"):
        validate_relative_path(current[field_name], f"current record {field_name}")
    if current["record_dir"] != request.record_dir:
        raise ValueError("current record_dir must match update request record_dir")
    validate_strict_child_path(
        current["manifest_path"], current["record_dir"], "current record manifest_path"
    )
    validate_strict_child_path(
        current["primary_data_path"], current["record_dir"], "current record primary_data_path"
    )
    validate_sha256_digest(current["expected_primary_digest"], "current primary digest")
    validate_positive_integer(current["expected_primary_size_bytes"], "current primary size_bytes")
    validate_non_negative_integer(current["expected_rows_recorded"], "current rows_recorded")

    if chunk.previous_total_rows_recorded != current["expected_rows_recorded"]:
        raise ValueError("append chunk previous total must match current rows_recorded")
    if chunk.total_rows_recorded != chunk.previous_total_rows_recorded + chunk.rows_recorded:
        raise ValueError("append chunk total must equal previous total plus rows_recorded")
    if chunk.total_rows_recorded > record["expected_points"]:
        raise ValueError("append chunk total must not exceed expected point count")


def _sha256_file(path: Path) -> str:
    digest = sha256(path.read_bytes())
    return digest


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_existing_file(storage_root: Path, relative_path: str, label: str) -> Path:
    ensure_no_symlink_parents(storage_root, relative_path, label)
    target = path_under(storage_root, relative_path, label)
    if target.is_symlink():
        raise ValueError(f"{label} target is a symlink")
    if not target.is_file():
        raise ValueError(f"{label} file is unavailable")
    return target


def _ensure_existing_record_dir(source: dict[str, Any], storage_root: Path) -> None:
    current = source["current_record"]
    ensure_no_symlink_parents(
        storage_root, current["record_dir"], "existing record update record_dir"
    )
    record_dir = path_under(
        storage_root, current["record_dir"], "existing record update record_dir"
    )
    if record_dir.is_symlink():
        raise ValueError("existing record directory is a symlink")
    if not record_dir.is_dir():
        raise ValueError("existing record directory is unavailable")


def _preflight_current_record(source: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    current = source["current_record"]
    record = source["measurement_record"]
    _ensure_existing_record_dir(source, storage_root)

    manifest_path = _ensure_existing_file(
        storage_root, current["manifest_path"], "existing record manifest"
    )
    primary_path = _ensure_existing_file(
        storage_root, current["primary_data_path"], "existing record primary data"
    )
    manifest = _read_json(manifest_path)

    record_id = record["measurement_record_id"]
    if manifest["measurement_record_id"] != record_id:
        raise ValueError("existing record manifest id must match update request")
    if manifest["label"] != record["label"]:
        raise ValueError("existing record manifest label must match update request")
    if manifest["experiment_type"] != record["experiment_type"]:
        raise ValueError("existing record manifest experiment_type must match update request")
    if manifest["target"] != record["target"]:
        raise ValueError("existing record manifest target must match update request")
    if manifest["expected_points"] != record["expected_points"]:
        raise ValueError("existing record manifest expected_points must match update request")
    if manifest["record_dir"] != current["record_dir"]:
        raise ValueError("existing record manifest record_dir must match current record")
    if manifest["primary_data"]["path"] != current["primary_data_path"]:
        raise ValueError("existing record manifest primary path must match current record")
    if manifest["primary_data"]["format"] != current["primary_data_format"]:
        raise ValueError("existing record manifest primary format must match current record")
    if manifest["primary_data"]["digest"] != current["expected_primary_digest"]:
        raise ValueError("existing record manifest digest must match current record")
    if manifest["primary_data"]["size_bytes"] != current["expected_primary_size_bytes"]:
        raise ValueError("existing record manifest size must match current record")
    if manifest["primary_data"]["rows_recorded"] != current["expected_rows_recorded"]:
        raise ValueError("existing record manifest rows must match current record")

    observed_digest = _sha256_file(primary_path)
    observed_size = primary_path.stat().st_size
    if observed_digest != current["expected_primary_digest"]:
        raise ValueError("existing primary digest does not match current record")
    if observed_size != current["expected_primary_size_bytes"]:
        raise ValueError("existing primary size does not match current record")
    if source["append_chunk"]["total_rows_recorded"] > manifest["expected_points"]:
        raise ValueError("append chunk total must not exceed manifest expected point count")

    return {
        "manifest_path": current["manifest_path"],
        "primary_data_path": current["primary_data_path"],
        "manifest_expected_points": manifest["expected_points"],
        "observed_primary_digest": observed_digest,
        "observed_primary_size_bytes": observed_size,
        "observed_rows_recorded": current["expected_rows_recorded"],
    }


def _read_append_chunk(source: dict[str, Any], content_root: Path) -> bytes:
    chunk = source["append_chunk"]
    ensure_no_symlink_parents(content_root, chunk["content_ref"], "existing record update content")
    content_path = path_under(content_root, chunk["content_ref"], "append chunk content_ref")
    if content_path.is_symlink():
        raise ValueError("existing record update content file is a symlink")
    if not content_path.is_file():
        raise ValueError("declared append chunk content file is unavailable")
    content = content_path.read_bytes()
    digest = sha256(content)
    if digest != chunk["declared_digest"]:
        raise ValueError("declared append chunk digest does not match fixture file")
    if len(content) != chunk["size_bytes"]:
        raise ValueError("declared append chunk size does not match fixture file")
    return content


def _receipt_bytes(
    source: dict[str, Any],
    request: MeasurementRecordExistingUpdateRequest,
    segment_digest: str,
    segment_size: int,
) -> bytes:
    record = source["measurement_record"]
    chunk = source["append_chunk"]
    receipt = {
        "measurement_record_id": record["measurement_record_id"],
        "update_id": request.update_id,
        "request_id": request.request_id,
        "append_segment": {
            "path": request.append_segment_path,
            "digest": segment_digest,
            "size_bytes": segment_size,
            "format": source["current_record"]["primary_data_format"],
        },
        "append_chunk": {
            "chunk_id": chunk["chunk_id"],
            "sequence": chunk["sequence"],
            "event_id": chunk["event_id"],
            "rows_recorded": chunk["rows_recorded"],
            "previous_total_rows_recorded": chunk["previous_total_rows_recorded"],
            "total_rows_recorded": chunk["total_rows_recorded"],
        },
    }
    return json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _lock_content(request: MeasurementRecordExistingUpdateRequest) -> bytes:
    return f"{request.request_id}\n{request.update_id}\n".encode()


def _target_exists(root: Path, relative_path: str) -> bool:
    return os.path.lexists(path_under(root, relative_path, "existing record update target"))


def _write_new_file(root: Path, relative_path: str, content: bytes, *, label: str) -> None:
    ensure_no_symlink_parents(root, relative_path, label)
    target = path_under(root, relative_path, label)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
    except Exception:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if fd != -1:
            os.close(fd)


def _acquire_lock(storage_root: Path, request: MeasurementRecordExistingUpdateRequest) -> bytes:
    content = _lock_content(request)
    if _target_exists(storage_root, request.lock_path):
        raise ValueError("existing record update lock target already exists")
    _write_new_file(
        storage_root,
        request.lock_path,
        content,
        label="existing record update lock",
    )
    return content


def _release_owned_lock(storage_root: Path, lock_path: str, expected_content: bytes) -> None:
    try:
        lock = path_under(storage_root, lock_path, "existing record update lock")
        if lock.is_symlink() or not lock.is_file():
            return
        if lock.read_bytes() == expected_content:
            lock.unlink()
    except FileNotFoundError:
        pass


def _write_update_files(
    source: dict[str, Any],
    request: MeasurementRecordExistingUpdateRequest,
    storage_root: Path,
    segment_content: bytes,
) -> list[dict[str, Any]]:
    segment_digest = sha256(segment_content)
    segment_size = len(segment_content)
    receipt_content = _receipt_bytes(source, request, segment_digest, segment_size)
    receipt_digest = sha256(receipt_content)
    written_paths: list[str] = []
    try:
        _write_new_file(
            storage_root,
            request.append_segment_path,
            segment_content,
            label="existing record update append segment",
        )
        written_paths.append(request.append_segment_path)
        _write_new_file(
            storage_root,
            request.update_receipt_path,
            receipt_content,
            label="existing record update receipt",
        )
        written_paths.append(request.update_receipt_path)
    except Exception:
        for relative_path in reversed(written_paths):
            try:
                path_under(storage_root, relative_path, "existing record update rollback").unlink()
            except FileNotFoundError:
                pass
        raise

    return [
        {
            "path": request.append_segment_path,
            "kind": "append_segment",
            "result": "written",
            "bytes_written": segment_size,
            "digest": segment_digest,
        },
        {
            "path": request.update_receipt_path,
            "kind": "update_receipt",
            "result": "written",
            "bytes_written": len(receipt_content),
            "digest": receipt_digest,
        },
    ]


def _build_summary(
    source: dict[str, Any],
    request: MeasurementRecordExistingUpdateRequest,
    current: dict[str, Any],
    write_results: list[dict[str, Any]],
) -> dict[str, Any]:
    record = source["measurement_record"]
    chunk = source["append_chunk"]
    return {
        "measurement_record": {
            "measurement_record_id": record["measurement_record_id"],
            "label": record["label"],
            "experiment_type": record["experiment_type"],
            "target": record["target"],
            "source_kind": record["source_kind"],
            "expected_points": record["expected_points"],
            "classification": "existing_record_append_recorded",
        },
        "current_record": current,
        "update_request": {
            "request_id": request.request_id,
            "update_id": request.update_id,
            "approval_state": request.approval_state,
            "record_dir": request.record_dir,
            "append_segment_path": request.append_segment_path,
            "update_receipt_path": request.update_receipt_path,
            "append_policy": request.append_policy,
            "collision_policy": request.collision_policy,
            "lock_path": request.lock_path,
            "lock_result": "acquired_and_released",
        },
        "append_chunk": {
            "chunk_id": chunk["chunk_id"],
            "sequence": chunk["sequence"],
            "event_id": chunk["event_id"],
            "content_ref": chunk["content_ref"],
            "rows_recorded": chunk["rows_recorded"],
            "previous_total_rows_recorded": chunk["previous_total_rows_recorded"],
            "total_rows_recorded": chunk["total_rows_recorded"],
            "declared_digest": chunk["declared_digest"],
            "size_bytes": chunk["size_bytes"],
        },
        "write_results": write_results,
    }


def validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def validate_positive_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{owner} must be positive")
    return value
