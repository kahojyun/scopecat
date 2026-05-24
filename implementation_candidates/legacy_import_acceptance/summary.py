"""Bounded acceptance writer for adapter-authored legacy import manifests.

This module validates an already-reviewed normalized adapter manifest and
writes one new imported measurement record under a caller-provided storage
root. It copies only the declared primary-data file after digest and size
preflight. It does not parse legacy source formats, infer schemas, accept
export packages, import linked context payloads, update existing records, or
define a stable public API.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from implementation_candidates.adapter_authored_legacy_import import (
    build_adapter_authored_legacy_import_summary,
)

_ACCEPTANCE_SCHEMA = "scopecat.legacy_import_acceptance.v0"

_EXPECTED_POLICY = {
    "acceptance_authority": "approved_import_acceptance_request",
    "manifest_authority": "adapter_authored",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "source_observation": "declared_primary_data_file_only",
    "storage_mutation": "copy_primary_data_and_write_manifest",
    "copy_behavior": "copy_into_new_record",
    "reference_behavior": "external_source_identity_preserved",
    "linked_context_materialization": "reference_only",
    "overwrite_behavior": "no_overwrite",
    "checksum_algorithm": "sha256",
    "schema_inference": "not_performed",
    "package_acceptance": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


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


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _open_dir_fd(path: Path | str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW
    if dir_fd is None:
        return os.open(path, flags)
    return os.open(path, flags, dir_fd=dir_fd)


def _open_parent_dir_fd(root: Path, relative_path: str, *, create: bool) -> int:
    root_fd = _open_dir_fd(root)
    current_fd = root_fd
    for part in _relative_parts(relative_path)[:-1]:
        if create:
            try:
                os.mkdir(part, dir_fd=current_fd)
            except FileExistsError:
                pass
        try:
            next_fd = _open_dir_fd(part, dir_fd=current_fd)
        except Exception:
            if current_fd != root_fd:
                os.close(current_fd)
            os.close(root_fd)
            raise
        if current_fd != root_fd:
            os.close(current_fd)
        current_fd = next_fd
    if current_fd == root_fd:
        return root_fd
    os.close(root_fd)
    return current_fd


def _existing_root(root: Path, label: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"legacy import acceptance {label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"legacy import acceptance {label} root must be an existing directory")
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"legacy import acceptance {label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"legacy import acceptance {label} parent is not a directory")


def _target_exists(root: Path, relative_path: str) -> bool:
    target = _path_under(root, relative_path)
    return target.exists() or target.is_symlink()


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["acceptance_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy import acceptance policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy import acceptance policy {key} must be {expected}")


def _validate_destination_paths(request: dict[str, Any]) -> None:
    if request["destination"]["path_kind"] != "relative_storage_path_under_caller_root":
        raise ValueError("legacy import acceptance destination path kind must stay relative")
    if request["destination"]["collision_policy"] != "no_overwrite":
        raise ValueError("legacy import acceptance collision policy must refuse overwrites")

    for field in ("record_dir", "primary_data_path", "manifest_path"):
        _validate_relative_path(request[field], f"acceptance request {field}")

    record_dir = request["record_dir"]
    for field in ("primary_data_path", "manifest_path"):
        path = request[field]
        if not path.startswith(f"{record_dir}/"):
            raise ValueError(f"acceptance request {field} must stay under record_dir")
    if request["primary_data_path"] == request["manifest_path"]:
        raise ValueError("legacy import primary data and manifest paths must differ")
    primary_parts = _relative_parts(request["primary_data_path"])
    manifest_parts = _relative_parts(request["manifest_path"])
    if (
        primary_parts[: len(manifest_parts)] == manifest_parts
        or manifest_parts[: len(primary_parts)] == primary_parts
    ):
        raise ValueError("legacy import output paths must not overlap")


def _validate_materialization(request: dict[str, Any]) -> None:
    materialization = request["materialization"]
    expected = {
        "primary_data": "copy_into_storage",
        "linked_context": "reference_only",
        "source_identity": "preserve_external_reference",
    }
    if materialization != expected:
        raise ValueError("legacy import materialization plan must match expected shape")


def _validate_source_primary_data(
    request: dict[str, Any], adapter_manifest: dict[str, Any]
) -> None:
    source_primary_data = request["source_primary_data"]
    _validate_relative_path(source_primary_data["content_ref"], "source primary data")
    if source_primary_data["content_ref"] != adapter_manifest["primary_data"]["path"]:
        raise ValueError("source primary data content_ref must match adapter manifest primary path")
    if not _SHA256_DIGEST.fullmatch(source_primary_data["declared_digest"]):
        raise ValueError("source primary data digest must be a sha256-prefixed hex digest")
    if (
        not isinstance(source_primary_data["size_bytes"], int)
        or source_primary_data["size_bytes"] <= 0
    ):
        raise ValueError("source primary data size_bytes must be positive")


def _validate_acceptance_request(source: dict[str, Any], adapter_summary: dict[str, Any]) -> None:
    request = source["acceptance_request"]
    review = request["review"]
    if review["approval_state"] != "approved":
        raise ValueError("legacy import acceptance request must be approved")
    if review["reviewed_manifest_classification"] != adapter_summary["classification"]:
        raise ValueError("reviewed manifest classification must match adapter summary")
    if adapter_summary["classification"] != "adapter_manifest_ready_for_review":
        raise ValueError("legacy import acceptance requires a ready adapter manifest")

    _validate_destination_paths(request)
    _validate_materialization(request)
    _validate_source_primary_data(request, source["adapter_manifest"])


def _validate_references(source: dict[str, Any]) -> dict[str, Any]:
    if source["acceptance_schema"] != _ACCEPTANCE_SCHEMA:
        raise ValueError(f"acceptance_schema must be {_ACCEPTANCE_SCHEMA}")
    _validate_policy(source)
    adapter_summary = build_adapter_authored_legacy_import_summary(source["adapter_manifest"])
    _validate_acceptance_request(source, adapter_summary)
    return adapter_summary


def _read_source_primary_data(source: dict[str, Any], content_root: Path) -> bytes:
    source_primary_data = source["acceptance_request"]["source_primary_data"]
    content_ref = source_primary_data["content_ref"]
    _ensure_no_symlink_parents(content_root, content_ref, "content")
    parent_fd = _open_parent_dir_fd(content_root, content_ref, create=False)
    try:
        try:
            file_fd = os.open(
                _relative_parts(content_ref)[-1], os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd
            )
        except FileNotFoundError as exc:
            raise ValueError("declared legacy import source file is unavailable") from exc
        with os.fdopen(file_fd, "rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("declared legacy import source file is unavailable")
            if source_stat.st_size != source_primary_data["size_bytes"]:
                raise ValueError("declared source primary data size does not match fixture file")
            content = handle.read()
    finally:
        os.close(parent_fd)

    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != source_primary_data["declared_digest"]:
        raise ValueError("declared source primary data digest does not match fixture file")
    return content


def _ensure_new_targets(source: dict[str, Any], storage_root: Path) -> None:
    request = source["acceptance_request"]
    for field in ("record_dir", "primary_data_path", "manifest_path"):
        if _target_exists(storage_root, request[field]):
            raise ValueError("legacy import acceptance target already exists")
        _ensure_no_symlink_parents(storage_root, request[field], "target")


def _manifest_bytes(
    source: dict[str, Any],
    adapter_summary: dict[str, Any],
    primary_digest: str,
    primary_size: int,
) -> bytes:
    request = source["acceptance_request"]
    manifest = {
        "measurement_record_id": adapter_summary["measurement"]["measurement_record_id"],
        "label": adapter_summary["measurement"]["label"],
        "experiment_type": adapter_summary["measurement"]["experiment_type"],
        "source_kind": "adapter_authored_legacy_import",
        "adapter": adapter_summary["adapter"],
        "source_identity": adapter_summary["source_identity"],
        "primary_data": {
            "path": request["primary_data_path"],
            "format": adapter_summary["primary_data"]["format"],
            "digest": primary_digest,
            "size_bytes": primary_size,
            "source_content_ref": request["source_primary_data"]["content_ref"],
            "source_declared_digest": request["source_primary_data"]["declared_digest"],
        },
        "preview": adapter_summary["preview"],
        "linked_context": adapter_summary["linked_context"],
        "acceptance": {
            "request_id": request["request_id"],
            "approval_state": request["review"]["approval_state"],
            "materialization": copy.deepcopy(request["materialization"]),
        },
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _write_new_file(storage_root: Path, relative_path: str, content: bytes) -> None:
    _ensure_no_symlink_parents(storage_root, relative_path, "target")
    parent_fd = _open_parent_dir_fd(storage_root, relative_path, create=True)
    try:
        file_fd = os.open(
            _relative_parts(relative_path)[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
            0o666,
            dir_fd=parent_fd,
        )
        handle = os.fdopen(file_fd, "wb")
    finally:
        os.close(parent_fd)
    with handle:
        handle.write(content)


def _remove_empty_parents(storage_root: Path, relative_path: str) -> None:
    root = storage_root.resolve()
    current = _path_under(root, relative_path).parent
    while current != root:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _rollback_written_files(storage_root: Path, written_paths: list[str]) -> None:
    for relative_path in reversed(written_paths):
        target = _path_under(storage_root, relative_path)
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        _remove_empty_parents(storage_root, relative_path)


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "legacy_import_accepted",
            "severity": "review",
            "basis": "An approved acceptance request copied adapter-declared primary data into a new record directory.",
            "does_not_claim": "stable_import_api_or_gui",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "The embedded adapter manifest is validated, but Scopecat does not parse the legacy source format.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "source_file_preflighted",
            "severity": "info",
            "basis": "The declared source primary-data sha256 and size are checked before writing.",
            "does_not_claim": "schema_or_scientific_validity",
        },
        {
            "code": "linked_context_reference_only",
            "severity": "review",
            "basis": "Linked context references are preserved from the adapter manifest but their payloads are not imported.",
            "does_not_claim": "recursive_context_import",
        },
        {
            "code": "package_acceptance_not_performed",
            "severity": "review",
            "basis": "This accepts one adapter-authored legacy record, not a Scopecat export or handoff package.",
            "does_not_claim": "export_package_import",
        },
    ]


def accept_legacy_import(
    source: dict[str, Any],
    *,
    content_root: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Accept one reviewed adapter-authored legacy import into new storage."""
    adapter_summary = _validate_references(source)
    content_root_resolved = _existing_root(content_root, "content")
    storage_root_resolved = _existing_root(storage_root, "storage")
    primary_content = _read_source_primary_data(source, content_root_resolved)
    _ensure_new_targets(source, storage_root_resolved)

    primary_digest = f"sha256:{hashlib.sha256(primary_content).hexdigest()}"
    primary_size = len(primary_content)
    manifest_content = _manifest_bytes(source, adapter_summary, primary_digest, primary_size)
    manifest_digest = f"sha256:{hashlib.sha256(manifest_content).hexdigest()}"

    request = source["acceptance_request"]
    written_paths: list[str] = []
    try:
        _write_new_file(storage_root_resolved, request["primary_data_path"], primary_content)
        written_paths.append(request["primary_data_path"])
        _write_new_file(storage_root_resolved, request["manifest_path"], manifest_content)
        written_paths.append(request["manifest_path"])
    except Exception:
        _rollback_written_files(storage_root_resolved, written_paths)
        raise

    return {
        "acceptance_schema": source["acceptance_schema"],
        "acceptance_policy": copy.deepcopy(source["acceptance_policy"]),
        "adapter_manifest_classification": adapter_summary["classification"],
        "measurement_record": {
            "measurement_record_id": adapter_summary["measurement"]["measurement_record_id"],
            "label": adapter_summary["measurement"]["label"],
            "experiment_type": adapter_summary["measurement"]["experiment_type"],
            "source_kind": "adapter_authored_legacy_import",
            "classification": "imported_ready_for_review",
        },
        "adapter": adapter_summary["adapter"],
        "source_identity": adapter_summary["source_identity"],
        "acceptance_request": {
            "request_id": request["request_id"],
            "approval_state": request["review"]["approval_state"],
            "reviewed_manifest_classification": request["review"][
                "reviewed_manifest_classification"
            ],
            "record_dir": request["record_dir"],
            "primary_data_path": request["primary_data_path"],
            "manifest_path": request["manifest_path"],
            "collision_policy": request["destination"]["collision_policy"],
            "materialization": copy.deepcopy(request["materialization"]),
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
                "kind": "imported_record_manifest",
                "result": "written",
                "bytes_written": len(manifest_content),
                "digest": manifest_digest,
                "does_not_claim": "final_storage_schema_or_package_integrity",
            },
        ],
        "preview": adapter_summary["preview"],
        "linked_context": adapter_summary["linked_context"],
        "attention": _attention(),
    }
