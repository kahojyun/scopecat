"""Editable folder observation engineering prototype.

This module is read-only. It observes a caller-provided editable workspace root
against a selected managed code version without importing code, executing code,
inspecting Git state, restoring environments, mutating files, or claiming
runnable readiness.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "fact_source": "declared_selected_managed_version_plus_observed_filesystem",
    "selected_source": "materialized_workspace_reference",
    "filesystem_inspection": "selected_workspace_root_only",
    "content_observation": "sha256_and_size_only",
    "semantic_source_diff": "not_performed",
    "internal_git_inspection": "not_performed",
    "environment_readiness": "not_performed",
    "code_import": "not_performed",
    "code_execution": "not_performed",
    "workspace_mutation": "not_performed",
}
_SOURCE_STATES = {
    "content_available",
    "redacted",
    "unavailable",
}
_EXPECTED_EXTRA_OBSERVATION_POLICY = {
    "selected_code_surface_authority": "managed_version_file_inventory",
    "extra_file_authority": "bounded_workspace_observation_only",
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
    policy = source["observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected editable folder observation policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"editable folder observation policy {key} must be {expected}")


def _validate_extra_observation_policy(source: dict[str, Any]) -> None:
    policy = source["extra_observation_policy"]
    expected_keys = set(_EXPECTED_EXTRA_OBSERVATION_POLICY) | {"ignored_directory_names"}
    if set(policy) != expected_keys:
        raise ValueError("expected editable folder extra-observation policy shape")
    for key, expected in _EXPECTED_EXTRA_OBSERVATION_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"editable folder extra-observation policy {key} must be {expected}")

    ignored_directory_names = policy["ignored_directory_names"]
    if not ignored_directory_names:
        raise ValueError("editable folder observation requires ignored directory names")
    if len(set(ignored_directory_names)) != len(ignored_directory_names):
        raise ValueError("editable folder observation ignored directory names must be unique")
    for name in ignored_directory_names:
        if "/" in name or "\\" in name or not _path_is_relative(name):
            raise ValueError("editable folder observation ignored directory names must be names")


def _validate_content_state(file_record: dict[str, Any]) -> None:
    source_state = file_record["materialization_source_state"]
    content_state = file_record.get("content_state")

    if source_state == "content_available":
        if content_state is None:
            raise ValueError("content-available observation entries require content_state")
        if content_state["digest_algorithm"] != "sha256":
            raise ValueError("editable folder observation integrity hint must use sha256")
        if not _SHA256_DIGEST.fullmatch(content_state["digest"]):
            raise ValueError(
                "editable folder observation digest must be a sha256-prefixed hex digest"
            )
    elif content_state is not None:
        raise ValueError("non-content-available observation entries must not carry content_state")


def _validate_file_record(version_id: str, file_record: dict[str, Any]) -> None:
    if not _path_is_relative(file_record["path"]):
        raise ValueError(f"managed code version {version_id} contains non-relative file path")
    if not _path_is_relative(file_record["materialization_path"]):
        raise ValueError(
            f"managed code version {version_id} contains non-relative materialization path"
        )

    source_state = file_record["materialization_source_state"]
    if source_state not in _SOURCE_STATES:
        raise ValueError("managed code version has unsupported materialization source state")
    _validate_content_state(file_record)


def _validate_workspace_reference(request: dict[str, Any]) -> None:
    reference = request["workspace_reference"]
    if reference["path_kind"] != "relative_workspace_path_under_caller_root":
        raise ValueError("editable folder observation workspace path kind must stay relative")
    if not _path_is_relative(reference["root_path"]):
        raise ValueError("editable folder observation root path must be relative")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_extra_observation_policy(source)
    versions = _version_by_id(source)
    _records_by_key(source["observation_requests"], "request_id")

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

    for request in source["observation_requests"]:
        selected_version_id = request["selected_version_id"]
        if selected_version_id not in versions:
            raise ValueError(
                f"observation request references missing managed version: {selected_version_id}"
            )
        _validate_workspace_reference(request)


def _existing_root(root: Path, label: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"editable folder observation {label} root must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"editable folder observation {label} root must be an existing directory")
    return root.resolve()


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("editable folder observation parent path is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("editable folder observation parent path is not a directory")


def _read_observed_content(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except FileNotFoundError:
        return {"path_state": "missing"}
    except NotADirectoryError:
        return {"path_state": "missing"}
    except OSError as error:
        if error.errno == errno.ELOOP:
            return {"path_state": "symlink"}
        raise

    try:
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            return {"path_state": "not_a_file"}
        with os.fdopen(file_descriptor, "rb") as handle:
            file_descriptor = -1
            content = handle.read()
    finally:
        if file_descriptor != -1:
            os.close(file_descriptor)

    return {
        "path_state": "regular_file",
        "digest_algorithm": "sha256",
        "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        "size_bytes": len(content),
    }


def _relative_workspace_path(request: dict[str, Any], file_record: dict[str, Any]) -> str:
    return str(
        PurePosixPath(request["workspace_reference"]["root_path"])
        / file_record["materialization_path"]
    )


def _selected_version_summary(version: dict[str, Any]) -> dict[str, Any]:
    comparable_count = sum(
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
        "content_comparable_file_count": comparable_count,
        "non_content_comparable_file_count": len(version["file_inventory"]) - comparable_count,
    }


def _expected_file_observation(
    request: dict[str, Any],
    version: dict[str, Any],
    file_record: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    workspace_path = _relative_workspace_path(request, file_record)
    target_path = _path_under(workspace_root, workspace_path)
    source_state = file_record["materialization_source_state"]
    observed_state: dict[str, Any] | None = None

    if source_state == "redacted":
        finding = "skipped_redacted"
        basis = "The selected managed version declares this file redacted."
        does_not_claim = "file_content_observed_or_available"
    elif source_state == "unavailable":
        finding = "unavailable_reference"
        basis = "The selected managed version declares this file unavailable."
        does_not_claim = "file_should_exist_in_editable_workspace"
    else:
        _ensure_no_symlink_parents(workspace_root, workspace_path)
        observed_content = _read_observed_content(target_path)
        path_state = observed_content["path_state"]
        if path_state == "symlink":
            finding = "target_is_symlink"
            basis = "The editable workspace target is a symlink and was not followed."
            does_not_claim = "target_content_observed"
        elif path_state == "missing":
            finding = "missing_expected"
            basis = "The selected managed version expected content at this workspace path."
            does_not_claim = "user_deleted_file_or_materialization_failure_cause"
        elif path_state == "not_a_file":
            finding = "not_a_file"
            basis = "The editable workspace path exists but is not a regular file."
            does_not_claim = "target_content_observed"
        else:
            observed_state = {
                key: value for key, value in observed_content.items() if key != "path_state"
            }
            expected_state = file_record["content_state"]
            if (
                observed_state["digest"] == expected_state["digest"]
                and observed_state["size_bytes"] == expected_state["size_bytes"]
            ):
                finding = "same_observed"
                basis = "Observed editable file size and sha256 match the selected version."
                does_not_claim = "semantic_equivalence_or_runnable_readiness"
            else:
                finding = "changed_observed"
                basis = "Observed editable file size or sha256 differs from the selected version."
                does_not_claim = "semantic_source_diff_or_change_cause"

    observation = {
        "request_id": request["request_id"],
        "version_id": version["version_id"],
        "source_path": file_record["path"],
        "workspace_path": workspace_path,
        "role": file_record["role"],
        "recorded_form": file_record["recorded_form"],
        "materialization_source_state": source_state,
        "finding": finding,
        "provenance_label": f"{version['stable_identity']['stable_id']}:{file_record['path']}",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }
    if observed_state is not None:
        observation["observed_content_state"] = observed_state
        observation["expected_digest"] = file_record["content_state"]["digest"]
    return observation


def _scan_regular_and_symlink_files(
    root: Path, ignored_directory_names: set[str]
) -> tuple[dict[str, str], int]:
    observed: dict[str, str] = {}
    ignored_count = 0
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in os.scandir(current):
            entry_path = Path(entry.path)
            relative = entry_path.relative_to(root).as_posix()
            if entry.name in ignored_directory_names:
                ignored_count += 1
            elif entry.is_symlink():
                observed[relative] = "symlink"
            elif entry.is_dir(follow_symlinks=False):
                stack.append(entry_path)
            elif entry.is_file(follow_symlinks=False):
                observed[relative] = "regular_file"
    return dict(sorted(observed.items())), ignored_count


def _extra_file_observations(
    request: dict[str, Any],
    version: dict[str, Any],
    workspace_root: Path,
    expected_paths: set[str],
    ignored_directory_names: set[str],
) -> tuple[list[dict[str, Any]], int]:
    root_path = request["workspace_reference"]["root_path"]
    _ensure_no_symlink_parents(workspace_root, root_path)
    request_root = _path_under(workspace_root, root_path)
    if request_root.is_symlink():
        raise ValueError("editable folder observation request root must not be a symlink")
    if not request_root.is_dir():
        raise ValueError("editable folder observation request root must be an existing directory")

    observations = []
    scanned_paths, ignored_count = _scan_regular_and_symlink_files(
        request_root, ignored_directory_names
    )
    for relative_path, path_kind in scanned_paths.items():
        workspace_path = str(PurePosixPath(root_path) / relative_path)
        if workspace_path in expected_paths:
            continue

        observed_content: dict[str, Any] | None = None
        if path_kind == "regular_file":
            observed_content = _read_observed_content(_path_under(workspace_root, workspace_path))
            path_kind = observed_content["path_state"]

        observation = {
            "request_id": request["request_id"],
            "version_id": version["version_id"],
            "source_path": None,
            "workspace_path": workspace_path,
            "role": "extra_workspace_file",
            "recorded_form": "observed_workspace_file",
            "materialization_source_state": "not_in_selected_version",
            "finding": _extra_finding_for_path_state(path_kind),
            "provenance_label": f"observed:{workspace_path}",
            "basis": "The editable workspace contains a path not declared by the selected version.",
            "does_not_claim": "generated_artifact_dependency_or_user_intent",
        }
        if path_kind == "regular_file" and observed_content is not None:
            observation["observed_content_state"] = {
                key: value for key, value in observed_content.items() if key != "path_state"
            }
        observations.append(observation)
    return observations, ignored_count


def _extra_finding_for_path_state(path_state: str) -> str:
    if path_state == "regular_file":
        return "extra_observed"
    if path_state == "symlink":
        return "extra_symlink_not_read"
    return "extra_unstable_not_read"


def _file_observations_for_request(
    request: dict[str, Any],
    version: dict[str, Any],
    workspace_root: Path,
    ignored_directory_names: set[str],
) -> tuple[list[dict[str, Any]], int]:
    expected_paths = {
        _relative_workspace_path(request, file_record) for file_record in version["file_inventory"]
    }
    expected = [
        _expected_file_observation(request, version, file_record, workspace_root)
        for file_record in version["file_inventory"]
    ]
    extras, ignored_count = _extra_file_observations(
        request, version, workspace_root, expected_paths, ignored_directory_names
    )
    return expected + extras, ignored_count


def _finding_counts(file_observations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for observation in file_observations:
        finding = observation["finding"]
        counts[finding] = counts.get(finding, 0) + 1
    return dict(sorted(counts.items()))


def _request_summary(
    request: dict[str, Any],
    file_observations: list[dict[str, Any]],
    ignored_path_count: int,
) -> dict[str, Any]:
    expected_observations = [
        item
        for item in file_observations
        if item["materialization_source_state"] != "not_in_selected_version"
    ]
    extra_observations = [
        item
        for item in file_observations
        if item["materialization_source_state"] == "not_in_selected_version"
    ]
    reference = request["workspace_reference"]
    return {
        "request_id": request["request_id"],
        "selected_version_id": request["selected_version_id"],
        "observation_purpose": request["observation_purpose"],
        "workspace_id": reference["workspace_id"],
        "root_label": reference["root_label"],
        "root_path": reference["root_path"],
        "expected_path_count": len(expected_observations),
        "extra_path_count": len(extra_observations),
        "ignored_path_count": ignored_path_count,
        "observed_content_path_count": sum(
            1 for item in file_observations if "observed_content_state" in item
        ),
        "finding_counts": _finding_counts(file_observations),
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["observation_policy"]
    extra_policy = source["extra_observation_policy"]
    attention = []

    if policy["filesystem_inspection"] == "selected_workspace_root_only":
        attention.append(
            {
                "code": "selected_workspace_root_inspected",
                "severity": "info",
                "basis": "Observation is limited to the declared editable workspace root.",
                "does_not_claim": "full_machine_or_storage_scan",
            }
        )

    if policy["content_observation"] == "sha256_and_size_only":
        attention.append(
            {
                "code": "content_observed_by_size_and_digest_only",
                "severity": "review",
                "basis": "Content observation records size and sha256 facts only.",
                "does_not_claim": "semantic_source_diff_or_runtime_behavior",
            }
        )

    if extra_policy["extra_file_authority"] == "bounded_workspace_observation_only":
        attention.append(
            {
                "code": "extra_files_are_non_authoritative",
                "severity": "info",
                "basis": "Extra files are observations around the selected code surface only.",
                "does_not_claim": "extra_files_belong_to_selected_code_context",
            }
        )

    if extra_policy["ignored_directory_names"]:
        attention.append(
            {
                "code": "workspace_internal_paths_ignored",
                "severity": "info",
                "basis": "Declared workspace-internal directory names are skipped during extra-file observation.",
                "does_not_claim": "ignored_paths_are_absent_or_safe",
            }
        )

    if policy["semantic_source_diff"] == "not_performed":
        attention.append(
            {
                "code": "semantic_source_diff_not_performed",
                "severity": "review",
                "basis": "Changed files are identified by observed digest or size difference only.",
                "does_not_claim": "semantic_change_or_cause_attribution",
            }
        )

    if policy["internal_git_inspection"] == "not_performed":
        attention.append(
            {
                "code": "internal_git_not_inspected",
                "severity": "info",
                "basis": "Git state remains outside this observation boundary.",
                "does_not_claim": "git_clean_dirty_branch_or_commit_status",
            }
        )

    if policy["environment_readiness"] == "not_performed":
        attention.append(
            {
                "code": "environment_readiness_not_checked",
                "severity": "review",
                "basis": "Environment files, dependency sync, and runnable readiness are not checked.",
                "does_not_claim": "runnable_environment",
            }
        )

    if policy["code_import"] == "not_performed" and policy["code_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_not_imported_or_executed",
                "severity": "review",
                "basis": "Observed code files are not imported, loaded, or executed.",
                "does_not_claim": "execution_permission_or_runtime_behavior",
            }
        )

    if policy["workspace_mutation"] == "not_performed":
        attention.append(
            {
                "code": "workspace_not_mutated",
                "severity": "info",
                "basis": "Observation does not create, edit, overwrite, or delete workspace files.",
                "does_not_claim": "repair_or_materialization_performed",
            }
        )

    return attention


@dataclass(frozen=True, init=False)
class EditableFolderObservationRequest:
    """Typed local request for read-only editable-folder observation."""

    _source: dict[str, Any] = field(repr=False)
    workspace_root: Path

    def __init__(self, *, source: dict[str, Any], workspace_root: Path) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))
        object.__setattr__(self, "workspace_root", Path(workspace_root))

    @classmethod
    def from_dict(
        cls,
        source: dict[str, Any],
        *,
        workspace_root: Path,
    ) -> EditableFolderObservationRequest:
        return cls(source=source, workspace_root=workspace_root)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class EditableFolderObservationResult:
    """Editable-folder observation summary projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def observation_requests(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["observation_requests"])

    @property
    def file_observations(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["file_observations"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def observe_editable_folder(
    request: EditableFolderObservationRequest,
) -> EditableFolderObservationResult:
    """Observe an editable workspace against a selected managed code version."""
    source = request.source
    versions = _version_by_id(source)
    workspace_root_resolved = _existing_root(request.workspace_root, "workspace")
    ignored_directory_names = set(source["extra_observation_policy"]["ignored_directory_names"])
    selected_version_ids = {
        request["selected_version_id"] for request in source["observation_requests"]
    }

    observations_and_ignored_counts = {
        request["request_id"]: _file_observations_for_request(
            request,
            versions[request["selected_version_id"]],
            workspace_root_resolved,
            ignored_directory_names,
        )
        for request in source["observation_requests"]
    }
    file_observations = [
        observation
        for request in source["observation_requests"]
        for observation in observations_and_ignored_counts[request["request_id"]][0]
    ]
    file_observations_by_request = {
        request["request_id"]: [
            observation
            for observation in file_observations
            if observation["request_id"] == request["request_id"]
        ]
        for request in source["observation_requests"]
    }

    summary = {
        "observation_policy": copy.deepcopy(source["observation_policy"]),
        "extra_observation_policy": copy.deepcopy(source["extra_observation_policy"]),
        "selected_versions": [
            _selected_version_summary(versions[version_id])
            for version_id in sorted(selected_version_ids)
        ],
        "observation_requests": [
            _request_summary(
                request,
                file_observations_by_request[request["request_id"]],
                observations_and_ignored_counts[request["request_id"]][1],
            )
            for request in source["observation_requests"]
        ],
        "file_observations": file_observations,
        "attention": _attention(source),
    }
    return EditableFolderObservationResult(summary=summary)


def build_editable_folder_observation_summary(
    source: dict[str, Any],
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    """Raw-dictionary adapter for editable-folder-observation fixtures."""
    return observe_editable_folder(
        EditableFolderObservationRequest.from_dict(source, workspace_root=workspace_root)
    ).to_dict()
