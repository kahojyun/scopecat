"""Append-only measurement storage writer implementation candidate.

This module performs a tightly bounded storage write for one new measurement
record. It writes only under a caller-provided storage root, from declared
chunk files under a caller-provided content root, after preflight digest and
size validation. It deliberately does not control hardware, infer schemas,
stream live events, import packages, export packages, or define GUI behavior.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from implementation_candidates.filesystem_mutation import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
    reject_existing_paths,
    write_new_files_transaction,
)

_EXPECTED_POLICY = {
    "write_authority": "approved_storage_write_request",
    "destination_authority": "caller_provided_storage_root_plus_declared_relative_paths",
    "append_behavior": "append_only_new_record",
    "overwrite_behavior": "no_overwrite",
    "checksum_algorithm": "sha256",
    "source_observation": "declared_chunk_files_only",
    "schema_inference": "not_performed",
    "hardware_control": "not_performed",
    "live_service": "not_defined",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRIMARY_DATA_FORMATS = {"csv_table"}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    raw_parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw_parts)
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _validate_positive_int(value: Any, owner: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{owner} must be an integer")
    if value <= 0:
        raise ValueError(f"{owner} must be positive")


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["storage_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected measurement storage writer policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"measurement storage writer policy {key} must be {expected}")


def _validate_preview_metadata(source: dict[str, Any]) -> None:
    preview = source["declared_preview_metadata"]
    primary_data_path = source["storage_request"]["primary_data_path"]
    if preview["metadata_authority"] != "writer_declared":
        raise ValueError("preview metadata authority must stay writer_declared")
    if preview["status"] != "preview_ready":
        raise ValueError("storage writer fixture currently requires preview_ready metadata")
    declared_columns = preview["declared_columns"]
    declared_names = {column["name"] for column in declared_columns}
    if len(declared_names) != len(declared_columns):
        raise ValueError("declared preview columns must have unique names")
    axis_order = preview["data_shape"]["axis_order"]
    if any(axis not in declared_names for axis in axis_order):
        raise ValueError("preview axis order must reference declared columns")
    for candidate in preview["plot_candidates"]:
        if candidate["source"] != primary_data_path:
            raise ValueError("plot candidate source must match stored primary data path")
        if candidate["x"] not in declared_names or candidate["y"] not in declared_names:
            raise ValueError("plot candidate axes must reference declared columns")


def _validate_storage_request(source: dict[str, Any]) -> None:
    request = source["storage_request"]
    if request["approval"]["approval_state"] != "approved":
        raise ValueError("measurement storage write request must be approved")
    destination = request["destination"]
    if destination["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("measurement storage destination path kind must stay relative")
    if destination["collision_policy"] != "no_overwrite":
        raise ValueError("measurement storage collision policy must refuse overwrites")
    if request["append_policy"] != "append_only_new_record":
        raise ValueError("measurement storage append policy must stay append_only_new_record")
    if request["primary_data_format"] not in _PRIMARY_DATA_FORMATS:
        raise ValueError("measurement storage primary data format is unsupported")

    for field in ("record_dir", "primary_data_path", "manifest_path"):
        _validate_relative_path(request[field], f"storage request {field}")
    record_dir = request["record_dir"]
    for field in ("primary_data_path", "manifest_path"):
        path = request[field]
        if not path.startswith(f"{record_dir}/"):
            raise ValueError(f"storage request {field} must stay under record_dir")
    if request["primary_data_path"] == request["manifest_path"]:
        raise ValueError("measurement storage primary data and manifest paths must differ")
    primary_parts = _relative_parts(request["primary_data_path"])
    manifest_parts = _relative_parts(request["manifest_path"])
    if primary_parts == manifest_parts:
        raise ValueError("measurement storage output paths must differ")
    if (
        primary_parts[: len(manifest_parts)] == manifest_parts
        or manifest_parts[: len(primary_parts)] == primary_parts
    ):
        raise ValueError("measurement storage output paths must not overlap")


def _validate_chunks(source: dict[str, Any]) -> None:
    chunks = source["append_chunks"]
    if not chunks:
        raise ValueError("measurement storage writer requires append chunks")
    _records_by_key(chunks, "chunk_id")
    sequences = [chunk["sequence"] for chunk in chunks]
    if sorted(sequences) != list(range(1, len(chunks) + 1)):
        raise ValueError("append chunk sequences must be contiguous from 1")
    event_ids = [chunk["event_id"] for chunk in chunks]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("append chunk event ids must be unique")

    previous_total = 0
    for chunk in sorted(chunks, key=lambda item: item["sequence"]):
        _validate_positive_int(chunk["sequence"], "append chunk sequence")
        _validate_relative_path(chunk["content_ref"], "append chunk content_ref")
        if not _SHA256_DIGEST.fullmatch(chunk["declared_digest"]):
            raise ValueError("append chunk digest must be a sha256-prefixed hex digest")
        _validate_positive_int(chunk["size_bytes"], "append chunk size_bytes")
        _validate_positive_int(chunk["rows_recorded"], "append chunk rows_recorded")
        _validate_positive_int(chunk["total_rows_recorded"], "append chunk total_rows_recorded")
        if chunk["total_rows_recorded"] != previous_total + chunk["rows_recorded"]:
            raise ValueError("append chunk total must equal previous total plus rows_recorded")
        previous_total = chunk["total_rows_recorded"]

    expected_points = source["measurement_record"]["expected_points"]
    _validate_positive_int(expected_points, "measurement record expected_points")
    if previous_total != expected_points:
        raise ValueError("append chunks must record the expected point count")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_storage_request(source)
    _validate_chunks(source)
    _validate_preview_metadata(source)


def _read_chunk_content(content_root: Path, chunk: dict[str, Any]) -> bytes:
    content_ref = chunk["content_ref"]
    ensure_no_symlink_parents(content_root, content_ref, "measurement storage writer content")
    content_path = path_under(content_root, content_ref)
    if content_path.is_symlink():
        raise ValueError("measurement storage writer content file is a symlink")
    if not content_path.is_file():
        raise ValueError("declared append chunk content file is unavailable")
    content = content_path.read_bytes()
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != chunk["declared_digest"]:
        raise ValueError("declared append chunk digest does not match fixture file")
    if len(content) != chunk["size_bytes"]:
        raise ValueError("declared append chunk size does not match fixture file")
    return content


def _preflight_chunks(
    source: dict[str, Any], content_root: Path
) -> list[tuple[dict[str, Any], bytes]]:
    return [
        (chunk, _read_chunk_content(content_root, chunk))
        for chunk in sorted(source["append_chunks"], key=lambda item: item["sequence"])
    ]


def _ensure_new_targets(source: dict[str, Any], storage_root: Path) -> None:
    request = source["storage_request"]
    reject_existing_paths(
        storage_root,
        [request["record_dir"], request["primary_data_path"], request["manifest_path"]],
        "measurement storage",
    )


def _primary_data_bytes(chunk_content: list[tuple[dict[str, Any], bytes]]) -> bytes:
    output = bytearray()
    for _chunk, content in chunk_content:
        output.extend(content)
    return bytes(output)


def _manifest_bytes(source: dict[str, Any], primary_digest: str, primary_size: int) -> bytes:
    request = source["storage_request"]
    chunks = sorted(source["append_chunks"], key=lambda item: item["sequence"])
    manifest = {
        "measurement_record_id": source["measurement_record"]["measurement_record_id"],
        "label": source["measurement_record"]["label"],
        "experiment_type": source["measurement_record"]["experiment_type"],
        "target": source["measurement_record"]["target"],
        "expected_points": source["measurement_record"]["expected_points"],
        "record_dir": request["record_dir"],
        "primary_data": {
            "path": request["primary_data_path"],
            "format": request["primary_data_format"],
            "digest": primary_digest,
            "size_bytes": primary_size,
            "rows_recorded": chunks[-1]["total_rows_recorded"],
        },
        "preview": copy.deepcopy(source["declared_preview_metadata"]),
        "append_chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "sequence": chunk["sequence"],
                "event_id": chunk["event_id"],
                "content_ref": chunk["content_ref"],
                "declared_digest": chunk["declared_digest"],
                "size_bytes": chunk["size_bytes"],
                "rows_recorded": chunk["rows_recorded"],
                "total_rows_recorded": chunk["total_rows_recorded"],
            }
            for chunk in chunks
        ],
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _preview_summary(source: dict[str, Any]) -> dict[str, Any]:
    preview = source["declared_preview_metadata"]
    return {
        "status": preview["status"],
        "metadata_authority": preview["metadata_authority"],
        "shape_kind": preview["data_shape"]["kind"],
        "axis_order": list(preview["data_shape"]["axis_order"]),
        "declared_roles": copy.deepcopy(preview["declared_columns"]),
        "plot_candidates": copy.deepcopy(preview["plot_candidates"]),
        "warnings": [],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "storage_write_performed",
            "severity": "review",
            "basis": "Approved fixture input wrote a new measurement record directory.",
            "does_not_claim": "final_storage_architecture",
        },
        {
            "code": "append_only_new_record",
            "severity": "review",
            "basis": "Existing record, primary-data, or manifest targets are refused.",
            "does_not_claim": "overwrite_merge_or_update",
        },
        {
            "code": "chunk_content_preflighted",
            "severity": "info",
            "basis": "Declared append chunk sha256 and size facts are checked before writing.",
            "does_not_claim": "semantic_schema_or_scientific_validation",
        },
        {
            "code": "schema_inference_not_performed",
            "severity": "review",
            "basis": "Preview metadata is caller-declared and source rows are not parsed for schema.",
            "does_not_claim": "automatic_schema_detection",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "The writer persists declared chunks without controlling instruments.",
            "does_not_claim": "instrument_command_or_safety_authority",
        },
    ]


def write_measurement_storage(
    source: dict[str, Any],
    *,
    content_root: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Write one new measurement record under a caller-provided storage root."""
    _validate_references(source)
    content_root_resolved = existing_directory_root(
        content_root, "measurement storage writer content"
    )
    storage_root_resolved = existing_directory_root(
        storage_root, "measurement storage writer storage"
    )
    chunk_content = _preflight_chunks(source, content_root_resolved)
    _ensure_new_targets(source, storage_root_resolved)

    primary_content = _primary_data_bytes(chunk_content)
    primary_digest = f"sha256:{hashlib.sha256(primary_content).hexdigest()}"
    primary_size = len(primary_content)
    manifest_content = _manifest_bytes(source, primary_digest, primary_size)
    manifest_digest = f"sha256:{hashlib.sha256(manifest_content).hexdigest()}"

    request = source["storage_request"]
    write_new_files_transaction(
        storage_root_resolved,
        [
            (request["primary_data_path"], primary_content),
            (request["manifest_path"], manifest_content),
        ],
        label="measurement storage",
    )

    return {
        "storage_policy": copy.deepcopy(source["storage_policy"]),
        "measurement_record": {
            "measurement_record_id": source["measurement_record"]["measurement_record_id"],
            "label": source["measurement_record"]["label"],
            "experiment_type": source["measurement_record"]["experiment_type"],
            "target": source["measurement_record"]["target"],
            "source_kind": source["measurement_record"]["source_kind"],
            "expected_points": source["measurement_record"]["expected_points"],
            "classification": "stored_ready_for_review",
        },
        "storage_request": {
            "request_id": request["request_id"],
            "approval_state": request["approval"]["approval_state"],
            "record_dir": request["record_dir"],
            "primary_data_path": request["primary_data_path"],
            "manifest_path": request["manifest_path"],
            "append_policy": request["append_policy"],
            "collision_policy": request["destination"]["collision_policy"],
        },
        "write_results": [
            {
                "path": request["primary_data_path"],
                "kind": "primary_data",
                "result": "written",
                "bytes_written": primary_size,
                "digest": primary_digest,
                "does_not_claim": "schema_or_scientific_validity",
            },
            {
                "path": request["manifest_path"],
                "kind": "record_manifest",
                "result": "written",
                "bytes_written": len(manifest_content),
                "digest": manifest_digest,
                "does_not_claim": "final_storage_schema",
            },
        ],
        "append_chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "sequence": chunk["sequence"],
                "event_id": chunk["event_id"],
                "content_ref": chunk["content_ref"],
                "rows_recorded": chunk["rows_recorded"],
                "total_rows_recorded": chunk["total_rows_recorded"],
                "declared_digest": chunk["declared_digest"],
                "size_bytes": chunk["size_bytes"],
            }
            for chunk, _content in chunk_content
        ],
        "preview": _preview_summary(source),
        "attention": _attention(),
    }
