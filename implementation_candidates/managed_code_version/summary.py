"""Structured summary builder for a managed code version candidate.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read source files, inspect Git state, create
archives, restore environments, materialize workspaces, import code, execute
code, or define workflow/DAG contracts.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "storage_contract": "candidate_record_only",
    "file_content_source": "declared_fixture_records",
    "integrity_contract": "content_integrity_hints_only",
    "materialization": "intent_recorded_not_performed",
    "environment_restoration": "not_performed",
    "code_execution": "not_performed",
    "internal_git_inspection": "not_performed",
    "default_file_inclusion": "not_recorded_unless_included",
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


def _candidate_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["captured_version_candidates"], "candidate_id")


def _version_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["managed_code_versions"], "version_id")


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _file_paths(version: dict[str, Any]) -> list[str]:
    return [file_record["path"] for file_record in version["file_records"]]


def _validate_file_record(version_id: str, file_record: dict[str, Any]) -> None:
    path = file_record["path"]
    if not _path_is_relative(path):
        raise ValueError(f"managed code version {version_id} contains non-relative file path")

    materialization_path = file_record["materialization_path"]
    if not _path_is_relative(materialization_path):
        raise ValueError(
            f"managed code version {version_id} contains non-relative materialization path"
        )

    content_state = file_record["content_state"]
    if content_state["digest_algorithm"] != "sha256":
        raise ValueError("managed code version integrity hint must use sha256")
    if not _SHA256_DIGEST.fullmatch(content_state["digest"]):
        raise ValueError("managed code version digest must be a sha256-prefixed hex digest")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["managed_version_policy"]
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"managed code version policy {key} must be {expected}")


def _validate_boundary_claims(version: dict[str, Any]) -> None:
    if version["restore_claim"] != "not_restored_by_fixture":
        raise ValueError("managed code version restore claim must stay fixture-local")
    if version["environment_claim"] != "environment_not_restored_or_checked":
        raise ValueError("managed code version environment claim must stay fixture-local")
    if version["execution_claim"] != "not_imported_loaded_or_executed":
        raise ValueError("managed code version execution claim must stay fixture-local")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    candidates = _candidate_by_id(source)
    _version_by_id(source)

    for version in source["managed_code_versions"]:
        version_id = version["version_id"]
        source_candidate_id = version["source_candidate_id"]
        if source_candidate_id not in candidates:
            raise ValueError(
                f"managed code version references missing candidate: {source_candidate_id}"
            )
        _validate_boundary_claims(version)

        for file_record in version["file_records"]:
            _validate_file_record(version_id, file_record)

        candidate = candidates[source_candidate_id]
        expected_paths = candidate["capture_scope"]["included_files"]
        actual_paths = _file_paths(version)
        if len(set(actual_paths)) != len(actual_paths):
            raise ValueError(f"managed code version {version_id} contains duplicate file paths")
        if actual_paths != expected_paths:
            raise ValueError("managed code version file records must match candidate include list")

        notebook_recording_policy = candidate["capture_scope"]["notebook_recording_policy"]
        for file_record in version["file_records"]:
            if (
                file_record["path"].endswith(".ipynb")
                and file_record["recorded_form"] != notebook_recording_policy
            ):
                raise ValueError("managed code version notebook files must match recording policy")

        materialization_paths = [
            file_record["materialization_path"] for file_record in version["file_records"]
        ]
        if len(set(materialization_paths)) != len(materialization_paths):
            raise ValueError(
                f"managed code version {version_id} contains duplicate materialization paths"
            )


def _captured_version_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    scope = candidate["capture_scope"]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_context_id": candidate["source_context_id"],
        "candidate_status": candidate["candidate_status"],
        "root_id": scope["root_id"],
        "included_files": list(scope["included_files"]),
        "notebook_recording_policy": scope["notebook_recording_policy"],
        "default_file_inclusion": scope["default_file_inclusion"],
    }


def _file_inventory(version: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "version_id": version["version_id"],
            "path": file_record["path"],
            "role": file_record["role"],
            "recorded_form": file_record["recorded_form"],
            "digest_algorithm": file_record["content_state"]["digest_algorithm"],
            "digest": file_record["content_state"]["digest"],
            "size_bytes": file_record["content_state"]["size_bytes"],
            "observed_at": file_record["content_state"]["observed_at"],
            "materialization_path": file_record["materialization_path"],
        }
        for file_record in version["file_records"]
    ]


def _managed_version_summary(version: dict[str, Any]) -> dict[str, Any]:
    notebook_count = sum(
        1 for file_record in version["file_records"] if file_record["path"].endswith(".ipynb")
    )
    return {
        "version_id": version["version_id"],
        "source_candidate_id": version["source_candidate_id"],
        "stable_identity": copy.deepcopy(version["stable_identity"]),
        "storage_authority": version["storage_authority"],
        "version_status": version["version_status"],
        "file_count": len(version["file_records"]),
        "notebook_file_count": notebook_count,
        "integrity_hint_count": len(version["file_records"]),
        "materialization_intent": copy.deepcopy(version["materialization_intent"]),
        "restore_claim": version["restore_claim"],
        "environment_claim": version["environment_claim"],
        "execution_claim": version["execution_claim"],
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    attention = []
    policy = source["managed_version_policy"]

    if policy["storage_contract"] == "candidate_record_only":
        attention.append(
            {
                "code": "managed_storage_candidate_only",
                "severity": "info",
                "basis": (
                    "The managed code version is a candidate record, not a final storage backend."
                ),
                "does_not_claim": "final_storage_architecture",
            }
        )

    if policy["integrity_contract"] == "content_integrity_hints_only":
        attention.append(
            {
                "code": "integrity_hints_not_storage_contract",
                "severity": "info",
                "basis": "Checksums and file sizes are recorded as integrity hints.",
                "does_not_claim": "content_addressed_store_or_archive",
            }
        )

    if policy["materialization"] == "intent_recorded_not_performed":
        attention.append(
            {
                "code": "materialization_not_performed",
                "severity": "review",
                "basis": (
                    "Workspace materialization intent is recorded but no workspace is created."
                ),
                "does_not_claim": "editable_workspace_available",
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

    if policy["code_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Managed version records do not import, load, or execute recorded code.",
                "does_not_claim": "execution_permission",
            }
        )

    if policy["internal_git_inspection"] == "not_performed":
        attention.append(
            {
                "code": "internal_git_not_inspected",
                "severity": "info",
                "basis": "Git state remains outside this managed-version boundary.",
                "does_not_claim": "git_clean_or_dirty_status",
            }
        )

    return attention


def build_managed_code_version_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured managed-code-version summary from explicit fixture input."""
    _validate_references(source)
    return {
        "managed_version_policy": copy.deepcopy(source["managed_version_policy"]),
        "captured_version_candidates": [
            _captured_version_candidate_summary(candidate)
            for candidate in source["captured_version_candidates"]
        ],
        "managed_code_versions": [
            _managed_version_summary(version) for version in source["managed_code_versions"]
        ],
        "file_inventory": [
            file_summary
            for version in source["managed_code_versions"]
            for file_summary in _file_inventory(version)
        ],
        "attention": _attention(source),
    }
