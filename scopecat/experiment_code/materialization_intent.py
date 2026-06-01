"""Workspace materialization intent engineering prototype.

This route-local module is deliberately side-effect free: it does not inspect
the filesystem, create directories, write files, overwrite existing files,
merge workspaces, inspect Git state, restore environments, import code,
execute code, or define workflow/DAG contracts.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "fact_source": "declared_fixture_materialization_facts",
    "planning_scope": "selected_managed_code_version",
    "destination_authority": "declared_candidate_destination",
    "filesystem_inspection": "not_performed",
    "workspace_creation": "not_performed",
    "overwrite_behavior": "plan_only_requires_review",
    "environment_restoration": "not_performed",
    "code_import": "not_performed",
    "code_execution": "not_performed",
}
_MATERIALIZATION_SOURCE_STATES = {
    "content_available",
    "redacted",
    "skipped",
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


def _join_relative_path(root_path: str, materialization_path: str) -> str:
    return str(PurePosixPath(root_path) / PurePosixPath(materialization_path))


def _is_under_or_equal(root_path: str, path: str) -> bool:
    return path == root_path or path.startswith(f"{root_path}/")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["materialization_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected workspace materialization intent policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"workspace materialization intent policy {key} must be {expected}")


def _validate_content_state(file_record: dict[str, Any]) -> None:
    source_state = file_record["materialization_source_state"]
    content_state = file_record.get("content_state")

    if source_state == "content_available":
        if content_state is None:
            raise ValueError("content-available materialization entries require content_state")
        if content_state["digest_algorithm"] != "sha256":
            raise ValueError("workspace materialization integrity hint must use sha256")
        if not _SHA256_DIGEST.fullmatch(content_state["digest"]):
            raise ValueError(
                "workspace materialization digest must be a sha256-prefixed hex digest"
            )
    elif content_state is not None:
        raise ValueError(
            "non-content-available materialization entries must not carry content_state"
        )


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
    if destination["path_kind"] != "declared_relative_workspace_path":
        raise ValueError("workspace materialization destination path kind must stay declared")
    if destination["collision_policy"] != "no_overwrite_without_review":
        raise ValueError("workspace materialization collision policy must require review")
    if not _path_is_relative(destination["root_path"]):
        raise ValueError("workspace materialization destination root path must be relative")

    existing_paths = [entry["path"] for entry in request["existing_destination_entries"]]
    if len(set(existing_paths)) != len(existing_paths):
        raise ValueError("workspace materialization request contains duplicate existing paths")
    for path in existing_paths:
        if not _path_is_relative(path):
            raise ValueError("workspace materialization existing paths must be relative")


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


def _existing_destination_paths(request: dict[str, Any]) -> set[str]:
    root_path = request["destination"]["root_path"]
    existing_paths = set()
    for entry in request["existing_destination_entries"]:
        path = entry["path"]
        if _is_under_or_equal(root_path, path):
            existing_paths.add(path)
        else:
            existing_paths.add(_join_relative_path(root_path, path))
    return existing_paths


def _file_plan_for_record(
    request: dict[str, Any],
    version: dict[str, Any],
    file_record: dict[str, Any],
) -> dict[str, Any]:
    destination = request["destination"]
    destination_path = _join_relative_path(
        destination["root_path"], file_record["materialization_path"]
    )
    source_state = file_record["materialization_source_state"]
    existing_paths = _existing_destination_paths(request)

    if source_state == "redacted":
        finding = "skipped_redacted"
        basis = "The selected managed version declares this file redacted."
        does_not_claim = "file_content_available_for_materialization"
    elif source_state == "unavailable":
        finding = "unavailable"
        basis = "The selected managed version declares this file unavailable."
        does_not_claim = "file_can_be_restored"
    elif source_state == "skipped":
        finding = "skipped"
        basis = "The selected managed version declares this file skipped for materialization."
        does_not_claim = "file_should_be_created"
    elif destination_path in existing_paths:
        finding = "collision_requires_review"
        basis = "The declared destination already has an entry at this path."
        does_not_claim = "overwrite_or_merge_performed"
    else:
        finding = "planned"
        basis = "The file has available managed content and no declared destination collision."
        does_not_claim = "file_written_or_workspace_created"

    return {
        "request_id": request["request_id"],
        "version_id": version["version_id"],
        "source_path": file_record["path"],
        "destination_path": destination_path,
        "role": file_record["role"],
        "recorded_form": file_record["recorded_form"],
        "materialization_source_state": source_state,
        "finding": finding,
        "provenance_label": (f"{version['stable_identity']['stable_id']}:{file_record['path']}"),
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _file_plans_for_request(
    request: dict[str, Any],
    version: dict[str, Any],
) -> list[dict[str, Any]]:
    file_plans = [
        _file_plan_for_record(request, version, file_record)
        for file_record in version["file_inventory"]
    ]
    destination_paths = [file_plan["destination_path"] for file_plan in file_plans]
    if len(set(destination_paths)) != len(destination_paths):
        raise ValueError("workspace materialization plan contains duplicate destination paths")
    return file_plans


def _finding_counts(file_plans: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for file_plan in file_plans:
        finding = file_plan["finding"]
        counts[finding] = counts.get(finding, 0) + 1
    return dict(sorted(counts.items()))


def _request_summary(request: dict[str, Any], file_plans: list[dict[str, Any]]) -> dict[str, Any]:
    destination = request["destination"]
    return {
        "request_id": request["request_id"],
        "selected_version_id": request["selected_version_id"],
        "request_purpose": request["request_purpose"],
        "destination_id": destination["destination_id"],
        "root_label": destination["root_label"],
        "root_path": destination["root_path"],
        "collision_policy": destination["collision_policy"],
        "planned_path_count": len(file_plans),
        "finding_counts": _finding_counts(file_plans),
    }


def _all_file_plans(source: dict[str, Any]) -> list[dict[str, Any]]:
    versions = _version_by_id(source)
    return [
        file_plan
        for request in source["materialization_requests"]
        for file_plan in _file_plans_for_request(request, versions[request["selected_version_id"]])
    ]


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["materialization_policy"]
    attention = []

    if policy["filesystem_inspection"] == "not_performed":
        attention.append(
            {
                "code": "filesystem_not_inspected",
                "severity": "info",
                "basis": "Destination state comes from declared fixture facts only.",
                "does_not_claim": "current_filesystem_state",
            }
        )

    if policy["workspace_creation"] == "not_performed":
        attention.append(
            {
                "code": "workspace_not_created",
                "severity": "review",
                "basis": "The plan names destination paths but creates no editable workspace.",
                "does_not_claim": "restored_or_materialized_workspace",
            }
        )

    if policy["overwrite_behavior"] == "plan_only_requires_review":
        attention.append(
            {
                "code": "overwrite_not_performed",
                "severity": "review",
                "basis": "Declared destination collisions require review before any overwrite.",
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
                "basis": "Materialization intent does not import, load, or execute code files.",
                "does_not_claim": "execution_permission_or_runtime_behavior",
            }
        )

    return attention


@dataclass(frozen=True, init=False)
class WorkspaceMaterializationIntentRequest:
    """Typed local request for workspace materialization planning facts."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> WorkspaceMaterializationIntentRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class WorkspaceMaterializationIntentResult:
    """Workspace materialization intent summary projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def materialization_requests(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["materialization_requests"])

    @property
    def file_plans(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["file_plans"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def plan_workspace_materialization(
    request: WorkspaceMaterializationIntentRequest,
) -> WorkspaceMaterializationIntentResult:
    """Build a side-effect-free workspace materialization plan."""
    source = request.source
    versions = _version_by_id(source)
    selected_version_ids = {
        request["selected_version_id"] for request in source["materialization_requests"]
    }
    file_plans = _all_file_plans(source)
    file_plans_by_request = {
        request["request_id"]: [
            file_plan
            for file_plan in file_plans
            if file_plan["request_id"] == request["request_id"]
        ]
        for request in source["materialization_requests"]
    }
    summary = {
        "materialization_policy": copy.deepcopy(source["materialization_policy"]),
        "selected_versions": [
            _selected_version_summary(versions[version_id])
            for version_id in sorted(selected_version_ids)
        ],
        "materialization_requests": [
            _request_summary(
                request,
                file_plans_by_request[request["request_id"]],
            )
            for request in source["materialization_requests"]
        ],
        "file_plans": file_plans,
        "attention": _attention(source),
    }
    return WorkspaceMaterializationIntentResult(summary=summary)


def build_workspace_materialization_intent_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for workspace-materialization-intent fixtures."""
    return plan_workspace_materialization(
        WorkspaceMaterializationIntentRequest.from_dict(source)
    ).to_dict()
