"""Workspace materialization implementation candidate.

This module performs a tightly bounded write: it copies declared managed
content into a caller-provided workspace root for an approved materialization
request. It deliberately does not restore environments, import code, execute
code, inspect Git state, overwrite targets, merge workspaces, delete files, or
define final managed-workspace storage.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "fact_source": "declared_fixture_managed_content",
    "selected_source": "approved_workspace_materialization_intent",
    "destination_authority": "caller_provided_workspace_root_plus_declared_relative_path",
    "filesystem_inspection": "target_paths_only",
    "workspace_creation": "approved_write_to_target_workspace",
    "overwrite_behavior": "no_overwrite",
    "environment_restoration": "not_performed",
    "code_import": "not_performed",
    "code_execution": "not_performed",
    "git_behavior": "not_performed",
}
_MATERIALIZATION_SOURCE_STATES = {
    "content_available",
    "redacted",
    "unavailable",
}
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _version_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["managed_code_versions"], "version_id")


def _request_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["materialization_requests"], "request_id")


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


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["materialization_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected workspace materialization policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"workspace materialization policy {key} must be {expected}")


def _validate_content_state(file_record: dict[str, Any]) -> None:
    source_state = file_record["materialization_source_state"]
    content_state = file_record.get("content_state")
    content_ref = file_record.get("content_ref")

    if source_state == "content_available":
        if content_state is None:
            raise ValueError("content-available materialization entries require content_state")
        if content_ref is None:
            raise ValueError("content-available materialization entries require content_ref")
        if not _path_is_relative(content_ref):
            raise ValueError("workspace materialization content refs must be relative")
        if content_state["digest_algorithm"] != "sha256":
            raise ValueError("workspace materialization integrity hint must use sha256")
        if not _SHA256_DIGEST.fullmatch(content_state["digest"]):
            raise ValueError(
                "workspace materialization digest must be a sha256-prefixed hex digest"
            )
    else:
        if content_state is not None or content_ref is not None:
            raise ValueError("non-content-available materialization entries must not carry content")


def _validate_file_record(version_id: str, file_record: dict[str, Any]) -> None:
    if not _path_is_relative(file_record["path"]):
        raise ValueError(f"managed code version {version_id} contains non-relative file path")
    if not _path_is_relative(file_record["materialization_path"]):
        raise ValueError(
            f"managed code version {version_id} contains non-relative materialization path"
        )

    source_state = file_record["materialization_source_state"]
    if source_state not in _MATERIALIZATION_SOURCE_STATES:
        raise ValueError("managed code version has unsupported materialization source state")
    _validate_content_state(file_record)


def _validate_destination(request: dict[str, Any]) -> None:
    destination = request["destination"]
    if destination["path_kind"] != "relative_workspace_path_under_caller_root":
        raise ValueError("workspace materialization destination path kind must stay relative")
    if destination["collision_policy"] != "no_overwrite":
        raise ValueError("workspace materialization collision policy must refuse overwrites")
    if not _path_is_relative(destination["root_path"]):
        raise ValueError("workspace materialization destination root path must be relative")

    approval = request["approval"]
    if approval["approval_state"] != "approved":
        raise ValueError("workspace materialization request must be approved")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    versions = _version_by_id(source)
    _request_by_id(source)

    for version in source["managed_code_versions"]:
        version_id = version["version_id"]
        file_paths = [file_record["path"] for file_record in version["file_inventory"]]
        if len(set(file_paths)) != len(file_paths):
            raise ValueError(f"managed code version {version_id} contains duplicate file paths")

        materialization_paths = [
            file_record["materialization_path"] for file_record in version["file_inventory"]
        ]
        if len(set(materialization_paths)) != len(materialization_paths):
            raise ValueError(
                f"managed code version {version_id} contains duplicate materialization paths"
            )

        for file_record in version["file_inventory"]:
            _validate_file_record(version_id, file_record)

    for request in source["materialization_requests"]:
        selected_version_id = request["selected_version_id"]
        if selected_version_id not in versions:
            raise ValueError(
                f"materialization request references missing managed version: {selected_version_id}"
            )
        _validate_destination(request)


def _selected_version_summary(version: dict[str, Any]) -> dict[str, Any]:
    materializable_count = sum(
        1
        for file_record in version["file_inventory"]
        if file_record["materialization_source_state"] == "content_available"
    )
    return {
        "version_id": version["version_id"],
        "stable_identity": copy.deepcopy(version["stable_identity"]),
        "storage_authority": version["storage_authority"],
        "version_status": version["version_status"],
        "file_count": len(version["file_inventory"]),
        "materializable_file_count": materializable_count,
        "non_materializable_file_count": len(version["file_inventory"]) - materializable_count,
    }


def _resolve_under(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    resolved = (root_resolved / relative_path).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("workspace materialization path escaped allowed root") from exc
    return resolved


def _read_declared_content(content_root: Path, file_record: dict[str, Any]) -> bytes:
    content_path = _resolve_under(content_root, file_record["content_ref"])
    if not content_path.is_file():
        raise ValueError("declared managed content file is unavailable")

    content = content_path.read_bytes()
    content_state = file_record["content_state"]
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != content_state["digest"]:
        raise ValueError("declared managed content digest does not match fixture file")
    if len(content) != content_state["size_bytes"]:
        raise ValueError("declared managed content size does not match fixture file")
    return content


def _target_path(
    workspace_root: Path, request: dict[str, Any], file_record: dict[str, Any]
) -> Path:
    relative_path = str(
        PurePosixPath(request["destination"]["root_path"]) / file_record["materialization_path"]
    )
    return _resolve_under(workspace_root, relative_path)


def _relative_destination_path(request: dict[str, Any], file_record: dict[str, Any]) -> str:
    return str(
        PurePosixPath(request["destination"]["root_path"]) / file_record["materialization_path"]
    )


def _write_content(target_path: Path, workspace_root: Path, content: bytes) -> None:
    workspace_root_resolved = workspace_root.resolve()
    current = target_path.parent
    parents_to_check = []
    while current != workspace_root_resolved and current != current.parent:
        parents_to_check.append(current)
        current = current.parent
    for parent in reversed(parents_to_check):
        if parent.exists() and parent.is_symlink():
            raise ValueError("workspace materialization target parent is a symlink")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)


def _file_result_for_record(
    request: dict[str, Any],
    version: dict[str, Any],
    file_record: dict[str, Any],
    content_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    destination_path = _relative_destination_path(request, file_record)
    target_path = _target_path(workspace_root, request, file_record)
    source_state = file_record["materialization_source_state"]
    bytes_written = 0

    if source_state == "redacted":
        result = "skipped_redacted"
        basis = "The selected managed version declares this file redacted."
        does_not_claim = "file_content_available_for_materialization"
    elif source_state == "unavailable":
        result = "unavailable"
        basis = "The selected managed version declares this file unavailable."
        does_not_claim = "file_can_be_restored"
    elif target_path.exists():
        result = "skipped_existing_target"
        basis = "The target path already exists; no overwrite was performed."
        does_not_claim = "overwrite_or_merge_performed"
    else:
        content = _read_declared_content(content_root, file_record)
        _write_content(target_path, workspace_root, content)
        bytes_written = len(content)
        result = "written"
        basis = "Declared managed content was written to a new target path."
        does_not_claim = "runnable_environment_or_execution"

    return {
        "request_id": request["request_id"],
        "version_id": version["version_id"],
        "source_path": file_record["path"],
        "destination_path": destination_path,
        "role": file_record["role"],
        "recorded_form": file_record["recorded_form"],
        "materialization_source_state": source_state,
        "result": result,
        "bytes_written": bytes_written,
        "provenance_label": f"{version['stable_identity']['stable_id']}:{file_record['path']}",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _file_results_for_request(
    request: dict[str, Any],
    version: dict[str, Any],
    content_root: Path,
    workspace_root: Path,
) -> list[dict[str, Any]]:
    return [
        _file_result_for_record(request, version, file_record, content_root, workspace_root)
        for file_record in version["file_inventory"]
    ]


def _result_counts(file_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for file_result in file_results:
        result = file_result["result"]
        counts[result] = counts.get(result, 0) + 1
    return dict(sorted(counts.items()))


def _request_summary(request: dict[str, Any], file_results: list[dict[str, Any]]) -> dict[str, Any]:
    destination = request["destination"]
    return {
        "request_id": request["request_id"],
        "selected_version_id": request["selected_version_id"],
        "request_purpose": request["request_purpose"],
        "approval_state": request["approval"]["approval_state"],
        "destination_id": destination["destination_id"],
        "root_label": destination["root_label"],
        "root_path": destination["root_path"],
        "collision_policy": destination["collision_policy"],
        "target_path_count": len(file_results),
        "written_file_count": sum(1 for item in file_results if item["result"] == "written"),
        "bytes_written": sum(item["bytes_written"] for item in file_results),
        "result_counts": _result_counts(file_results),
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["materialization_policy"]
    attention = []

    if policy["filesystem_inspection"] == "target_paths_only":
        attention.append(
            {
                "code": "target_paths_inspected",
                "severity": "info",
                "basis": "Only declared target paths were checked for existing entries.",
                "does_not_claim": "full_filesystem_scan_or_staleness_check",
            }
        )

    if policy["workspace_creation"] == "approved_write_to_target_workspace":
        attention.append(
            {
                "code": "workspace_created_with_available_files",
                "severity": "review",
                "basis": "Available managed content can be written to the target workspace.",
                "does_not_claim": "runnable_or_complete_lab_workspace",
            }
        )

    if policy["overwrite_behavior"] == "no_overwrite":
        attention.append(
            {
                "code": "overwrite_not_performed",
                "severity": "review",
                "basis": "Existing target paths are reported and left unchanged.",
                "does_not_claim": "overwrite_or_merge_performed",
            }
        )

    if policy["environment_restoration"] == "not_performed":
        attention.append(
            {
                "code": "environment_not_restored",
                "severity": "review",
                "basis": "Environment files or lockfiles are not synced or checked by this slice.",
                "does_not_claim": "runnable_environment",
            }
        )

    if policy["code_import"] == "not_performed" and policy["code_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_not_imported_or_executed",
                "severity": "review",
                "basis": "Materialized code files are not imported, loaded, or executed.",
                "does_not_claim": "execution_permission_or_runtime_behavior",
            }
        )

    if policy["git_behavior"] == "not_performed":
        attention.append(
            {
                "code": "git_not_performed",
                "severity": "review",
                "basis": "The workspace is not treated as a Git checkout or branch.",
                "does_not_claim": "git_checkout_branch_merge_or_sync",
            }
        )

    return attention


def materialize_workspace(
    source: dict[str, Any],
    *,
    content_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Materialize declared managed content into a caller-provided workspace root."""
    _validate_references(source)
    versions = _version_by_id(source)
    selected_version_ids = {
        request["selected_version_id"] for request in source["materialization_requests"]
    }

    file_results = [
        file_result
        for request in source["materialization_requests"]
        for file_result in _file_results_for_request(
            request,
            versions[request["selected_version_id"]],
            content_root,
            workspace_root,
        )
    ]
    file_results_by_request = {
        request["request_id"]: [
            file_result
            for file_result in file_results
            if file_result["request_id"] == request["request_id"]
        ]
        for request in source["materialization_requests"]
    }

    return {
        "materialization_policy": copy.deepcopy(source["materialization_policy"]),
        "selected_versions": [
            _selected_version_summary(versions[version_id])
            for version_id in sorted(selected_version_ids)
        ],
        "materialization_requests": [
            _request_summary(request, file_results_by_request[request["request_id"]])
            for request in source["materialization_requests"]
        ],
        "file_results": file_results,
        "attention": _attention(source),
    }
