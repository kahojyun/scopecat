"""Existing measurement record update implementation candidate.

This module validates one approved append update for an existing measurement
record. It writes only new append-segment and update-receipt files under the
declared existing record directory, guarded by a record-local lock guard. It
does not rewrite primary data, replace manifests, infer schemas, scan storage
roots, define a live service, or implement crash recovery.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts,
    validate_non_negative_integer,
    validate_positive_integer,
    validate_relative_path,
    validate_sha256_digest,
    validate_strict_child_path,
)
from implementation_candidates.filesystem_mutation import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
    reject_existing_paths,
    target_exists,
    write_new_file,
    write_new_files_transaction,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_existing_record_update_request",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "update_behavior": "append_new_segment_to_existing_record",
    "overwrite_behavior": "no_overwrite_new_update_files",
    "lock_behavior": "record_local_lock_guard",
    "checksum_algorithm": "sha256",
    "source_observation": "declared_update_chunk_file_only",
    "manifest_update": "append_receipt_only",
    "schema_inference": "not_performed",
    "crash_recovery": "not_defined",
    "hardware_control": "not_performed",
    "live_service": "not_defined",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_PRIMARY_DATA_FORMATS = {"csv_table"}


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = relative_path_parts(left, "existing record update output path")
    right_parts = relative_path_parts(right, "existing record update output path")
    return (
        left_parts == right_parts
        or left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
    )


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["update_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected existing record update policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"existing record update policy {key} must be {expected}")


def _validate_current_record(source: dict[str, Any]) -> None:
    current = source["current_record"]
    request = source["update_request"]
    if current["primary_data_format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("existing record update primary data format is unsupported")
    for field in ("record_dir", "manifest_path", "primary_data_path"):
        validate_relative_path(current[field], f"current record {field}")
    if current["record_dir"] != request["record_dir"]:
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


def _validate_update_request(source: dict[str, Any]) -> None:
    request = source["update_request"]
    if request["approval"]["approval_state"] != "approved":
        raise ValueError("existing record update request must be approved")
    if request["destination"]["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("existing record update destination path kind must stay relative")
    if request["destination"]["collision_policy"] != "no_overwrite_new_update_files":
        raise ValueError("existing record update collision policy must refuse overwrites")
    if request["append_policy"] != "existing_record_append":
        raise ValueError("existing record update append policy must stay existing_record_append")
    validate_relative_path(request["record_dir"], "update request record_dir")
    for field in ("append_segment_path", "update_receipt_path", "lock_path"):
        validate_relative_path(request[field], f"update request {field}")
        validate_strict_child_path(request[field], request["record_dir"], f"update request {field}")
    record_parts = relative_path_parts(request["record_dir"], "update request record_dir")
    lock_parts = relative_path_parts(request["lock_path"], "update request lock_path")
    if len(lock_parts) != len(record_parts) + 1 or lock_parts[: len(record_parts)] != record_parts:
        raise ValueError("update request lock_path must be directly under record_dir")
    paths = [
        request["append_segment_path"],
        request["update_receipt_path"],
        request["lock_path"],
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("existing record update output paths must differ")
    for index, path in enumerate(paths):
        for other in paths[index + 1 :]:
            if _paths_overlap(path, other):
                raise ValueError("existing record update output paths must not overlap")


def _validate_append_chunk(source: dict[str, Any]) -> None:
    chunk = source["append_chunk"]
    current = source["current_record"]
    validate_positive_integer(chunk["sequence"], "append chunk sequence")
    validate_relative_path(chunk["content_ref"], "append chunk content_ref")
    validate_sha256_digest(chunk["declared_digest"], "append chunk digest")
    validate_positive_integer(chunk["size_bytes"], "append chunk size_bytes")
    validate_positive_integer(chunk["rows_recorded"], "append chunk rows_recorded")
    validate_non_negative_integer(
        chunk["previous_total_rows_recorded"], "append chunk previous_total_rows_recorded"
    )
    validate_positive_integer(chunk["total_rows_recorded"], "append chunk total_rows_recorded")
    if chunk["previous_total_rows_recorded"] != current["expected_rows_recorded"]:
        raise ValueError("append chunk previous total must match current rows_recorded")
    if chunk["total_rows_recorded"] != (
        chunk["previous_total_rows_recorded"] + chunk["rows_recorded"]
    ):
        raise ValueError("append chunk total must equal previous total plus rows_recorded")
    expected_points = source["measurement_record"]["expected_points"]
    validate_positive_integer(expected_points, "measurement record expected_points")
    if chunk["total_rows_recorded"] > expected_points:
        raise ValueError("append chunk total must not exceed expected point count")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_update_request(source)
    _validate_current_record(source)
    _validate_append_chunk(source)


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_existing_file(storage_root: Path, relative_path: str, label: str) -> Path:
    ensure_no_symlink_parents(storage_root, relative_path, label)
    target = path_under(storage_root, relative_path)
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
    record_dir = path_under(storage_root, current["record_dir"])
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
    content_path = path_under(content_root, chunk["content_ref"])
    if content_path.is_symlink():
        raise ValueError("existing record update content file is a symlink")
    if not content_path.is_file():
        raise ValueError("declared append chunk content file is unavailable")
    content = content_path.read_bytes()
    digest = _sha256_bytes(content)
    if digest != chunk["declared_digest"]:
        raise ValueError("declared append chunk digest does not match fixture file")
    if len(content) != chunk["size_bytes"]:
        raise ValueError("declared append chunk size does not match fixture file")
    return content


def _receipt_bytes(source: dict[str, Any], segment_digest: str, segment_size: int) -> bytes:
    record = source["measurement_record"]
    request = source["update_request"]
    chunk = source["append_chunk"]
    receipt = {
        "measurement_record_id": record["measurement_record_id"],
        "update_id": request["update_id"],
        "request_id": request["request_id"],
        "append_segment": {
            "path": request["append_segment_path"],
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
        "manifest_update": "not_performed_append_receipt_only",
    }
    return json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _lock_content(request: dict[str, Any]) -> bytes:
    return f"{request['request_id']}\n{request['update_id']}\n".encode("utf-8")


def _acquire_lock(storage_root: Path, request: dict[str, Any]) -> bytes:
    lock_path = request["lock_path"]
    content = _lock_content(request)
    reject_existing_paths(storage_root, [lock_path], "existing record update lock")
    write_new_file(
        storage_root,
        lock_path,
        content,
        label="existing record update lock",
    )
    return content


def _release_owned_lock(storage_root: Path, lock_path: str, expected_content: bytes) -> None:
    try:
        lock = path_under(storage_root, lock_path)
        if lock.is_symlink() or not lock.is_file():
            return
        if lock.read_bytes() == expected_content:
            lock.unlink()
    except FileNotFoundError:
        pass


def _write_update_files(
    source: dict[str, Any],
    storage_root: Path,
    segment_content: bytes,
) -> tuple[list[str], list[dict[str, Any]]]:
    request = source["update_request"]
    segment_digest = _sha256_bytes(segment_content)
    segment_size = len(segment_content)
    receipt_content = _receipt_bytes(source, segment_digest, segment_size)
    receipt_digest = _sha256_bytes(receipt_content)

    written_paths, _created_dirs = write_new_files_transaction(
        storage_root,
        [
            (request["append_segment_path"], segment_content),
            (request["update_receipt_path"], receipt_content),
        ],
        label="existing record update",
    )
    return written_paths, [
        {
            "path": request["append_segment_path"],
            "kind": "append_segment",
            "result": "written",
            "bytes_written": segment_size,
            "digest": segment_digest,
            "does_not_claim": "merged_primary_data_or_schema_validity",
        },
        {
            "path": request["update_receipt_path"],
            "kind": "update_receipt",
            "result": "written",
            "bytes_written": len(receipt_content),
            "digest": receipt_digest,
            "does_not_claim": "manifest_replacement_or_crash_recovery",
        },
    ]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "existing_record_update_performed",
            "severity": "review",
            "basis": "Approved fixture input wrote new update files under an existing record.",
            "does_not_claim": "final_storage_update_model",
        },
        {
            "code": "record_lock_used",
            "severity": "review",
            "basis": "A direct record-local lock guard is used for this fixture mutation.",
            "does_not_claim": "distributed_locking_lock_identity_or_full_crash_recovery",
        },
        {
            "code": "current_record_preflighted",
            "severity": "info",
            "basis": "Existing manifest and primary-data digest and size facts are checked before writing.",
            "does_not_claim": "storage_root_scan_or_schema_inference",
        },
        {
            "code": "append_receipt_only",
            "severity": "review",
            "basis": "The candidate writes an append segment and receipt without replacing the manifest.",
            "does_not_claim": "compaction_or_read_model_update",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "The update persists declared data without controlling instruments.",
            "does_not_claim": "instrument_command_or_safety_authority",
        },
    ]


def append_existing_record_update(
    source: dict[str, Any],
    *,
    content_root: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Append one new update segment and receipt under an existing record."""
    _validate_references(source)
    content_root_resolved = existing_directory_root(content_root, "existing record update content")
    storage_root_resolved = existing_directory_root(storage_root, "existing record update storage")
    request = source["update_request"]
    _ensure_existing_record_dir(source, storage_root_resolved)
    lock_content = _acquire_lock(storage_root_resolved, request)
    try:
        current = _preflight_current_record(source, storage_root_resolved)
        segment_content = _read_append_chunk(source, content_root_resolved)

        if target_exists(storage_root_resolved, request["append_segment_path"]):
            raise ValueError("existing record update append segment already exists")
        if target_exists(storage_root_resolved, request["update_receipt_path"]):
            raise ValueError("existing record update receipt already exists")

        _written_paths, write_results = _write_update_files(
            source, storage_root_resolved, segment_content
        )
    finally:
        _release_owned_lock(storage_root_resolved, request["lock_path"], lock_content)

    record = source["measurement_record"]
    chunk = source["append_chunk"]
    return {
        "update_policy": copy.deepcopy(source["update_policy"]),
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
            "request_id": request["request_id"],
            "update_id": request["update_id"],
            "approval_state": request["approval"]["approval_state"],
            "record_dir": request["record_dir"],
            "append_segment_path": request["append_segment_path"],
            "update_receipt_path": request["update_receipt_path"],
            "append_policy": request["append_policy"],
            "collision_policy": request["destination"]["collision_policy"],
            "lock_path": request["lock_path"],
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
        "attention": _attention(),
    }
