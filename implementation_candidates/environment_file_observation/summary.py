"""Read-only declared environment file observation implementation candidate.

This module observes explicitly declared environment files under a
caller-provided workspace root. It validates availability, sha256, byte size,
and a narrow ``pyproject.toml`` declaration summary without resolving
dependencies, syncing packages, probing runtimes, importing code, executing
code, probing hardware, or claiming runnable readiness.
"""

from __future__ import annotations

import copy
import hashlib
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "observation_authority": "explicit_environment_file_observation_request",
    "workspace_root_authority": "caller_provided_workspace_root_plus_declared_relative_paths",
    "environment_file_observation": "explicit_declared_files_only",
    "checksum_algorithm": "sha256",
    "pyproject_parse": "stdlib_tomllib_declared_manifest_summary_only",
    "lockfile_parse": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "code_import_execution": "not_performed",
    "hardware_probe": "not_performed",
    "readiness_claim": "not_claimed",
    "shared_environment_schema": "not_defined",
}

_EXPECTED_SCOPE_KEYS = {
    "managed_code_version_id",
    "editable_workspace_id",
    "prepared_run_context_id",
}

_EXPECTED_ENVIRONMENT_CLAIMS = {
    "readiness_claim": "not_checked",
    "sync_claim": "not_synced",
    "execution_claim": "not_imported_loaded_or_executed",
    "hardware_claim": "not_probed",
}

_ENVIRONMENT_AUTHORITIES = {
    "user_declared_inventory",
}

_ENVIRONMENT_RECORD_STATUSES = {
    "declared",
    "declared_with_review_findings",
}

_FILE_ROLES = {
    "modern_python_manifest",
    "modern_python_lockfile",
}

_FILE_FORMATS = {
    "pyproject_toml",
    "uv_lock",
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANAGED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_DEPENDENCY_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_DEPENDENCY_NAME_PREFIX = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\s*(?:\[|[<>=!~;]|$))"
)
_DIRECT_REFERENCE = re.compile(r"\s@\s")
_MISMATCH_FINDING_CODES = {
    "environment_file_digest_mismatch",
    "environment_file_size_mismatch",
}


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


def _validate_nonnegative_int(value: Any, owner: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{owner} must be an integer")
    if value < 0:
        raise ValueError(f"{owner} must not be negative")


def _validate_managed_id(value: Any, owner: str) -> None:
    if not isinstance(value, str) or not _MANAGED_ID.fullmatch(value):
        raise ValueError(f"{owner} must be a non-empty managed identifier")


def _validate_root_display_label(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ValueError("workspace_root_label must be a non-path display label")


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("environment file observation workspace root must not be a symlink")
    if not root.is_dir():
        raise ValueError(
            "environment file observation workspace root must be an existing directory"
        )
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("environment file observation parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("environment file observation parent is not a directory")


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["environment_file_observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected environment file observation policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"environment file observation policy {key} must be {expected}")


def _validate_scope(scope: dict[str, Any]) -> None:
    if set(scope) != _EXPECTED_SCOPE_KEYS:
        raise ValueError("declared environment scope must match expected shape")
    for key in _EXPECTED_SCOPE_KEYS:
        _validate_managed_id(scope[key], f"declared environment scope {key}")


def _validate_environment_record(environment: dict[str, Any]) -> None:
    _validate_managed_id(environment["environment_id"], "declared environment environment_id")
    if environment["authority"] not in _ENVIRONMENT_AUTHORITIES:
        raise ValueError("declared environment authority must stay declared-only")
    if environment["record_status"] not in _ENVIRONMENT_RECORD_STATUSES:
        raise ValueError("declared environment record_status must stay declaration-only")
    _validate_scope(environment["scope"])

    claims = environment["environment_claims"]
    if set(claims) != set(_EXPECTED_ENVIRONMENT_CLAIMS):
        raise ValueError("declared environment claims must match expected shape")
    for key, expected in _EXPECTED_ENVIRONMENT_CLAIMS.items():
        if claims[key] != expected:
            raise ValueError(f"declared environment {key} must be {expected}")


def _validate_declared_file(file_record: dict[str, Any]) -> None:
    _validate_managed_id(file_record["file_id"], "declared environment file_id")
    if file_record["file_role"] not in _FILE_ROLES:
        raise ValueError("declared environment file role is unsupported")
    if file_record["format"] not in _FILE_FORMATS:
        raise ValueError("declared environment file format is unsupported")
    if (
        file_record["file_role"] == "modern_python_manifest"
        and file_record["format"] != "pyproject_toml"
    ):
        raise ValueError("modern_python_manifest file must use pyproject_toml format")
    if file_record["file_role"] == "modern_python_lockfile" and file_record["format"] != "uv_lock":
        raise ValueError("modern_python_lockfile file must use uv_lock format")
    _validate_relative_path(file_record["relative_path"], "declared environment file")
    if not _SHA256_DIGEST.fullmatch(file_record["expected_digest"]):
        raise ValueError("expected environment file digest must be a sha256-prefixed hex digest")
    _validate_nonnegative_int(file_record["expected_size_bytes"], "expected_size_bytes")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["observation_request"]
    _validate_managed_id(request["request_id"], "environment file observation request_id")
    _validate_root_display_label(request["workspace_root_label"])
    if not request["declared_files"]:
        raise ValueError("environment file observation requires at least one declared file")
    _records_by_key(request["declared_files"], "file_id")
    for file_record in request["declared_files"]:
        _validate_declared_file(file_record)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_environment_record(source["environment_record"])
    _validate_request(source)


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _dependency_name(dependency: Any) -> str | None:
    if not isinstance(dependency, str) or not dependency or _DIRECT_REFERENCE.search(dependency):
        return None
    match = _DEPENDENCY_NAME_PREFIX.match(dependency)
    if not match:
        return None
    return match.group(1)


def _dependency_names(dependencies: Any) -> list[str]:
    if not isinstance(dependencies, list):
        return []
    names = []
    for dependency in dependencies:
        name = _dependency_name(dependency)
        if name:
            names.append(name)
    return sorted(set(names))


def _skipped_dependency_count(dependencies: Any) -> int:
    if not isinstance(dependencies, list):
        return 0
    return sum(1 for dependency in dependencies if _dependency_name(dependency) is None)


def _pyproject_summary(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)

    project = parsed.get("project", {})
    dependency_groups = parsed.get("dependency-groups", {})
    if not isinstance(project, dict):
        project = {}
    if not isinstance(dependency_groups, dict):
        dependency_groups = {}

    return {
        "summary_kind": "pyproject_declared_manifest",
        "project_name": project.get("name") if isinstance(project.get("name"), str) else None,
        "requires_python": (
            project.get("requires-python")
            if isinstance(project.get("requires-python"), str)
            else None
        ),
        "dependency_names": _dependency_names(project.get("dependencies")),
        "skipped_dependency_entry_count": _skipped_dependency_count(project.get("dependencies")),
        "dependency_group_names": sorted(
            name
            for name in dependency_groups
            if isinstance(name, str) and _DEPENDENCY_NAME.fullmatch(name)
        ),
        "does_not_claim": "dependency_resolution_or_runtime_compatibility",
    }


def _parse_summary(
    file_record: dict[str, Any], target: Path
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    if file_record["format"] == "pyproject_toml":
        try:
            return _pyproject_summary(target), None
        except tomllib.TOMLDecodeError:
            return None, _finding(
                "environment_file_parse_failed",
                file_record["file_id"],
                "Observed pyproject.toml could not be parsed as TOML.",
                "dependency_resolution_or_runtime_compatibility",
            )
    return None, None


def _observe_declared_file(
    file_record: dict[str, Any], workspace_root: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    relative_path = file_record["relative_path"]
    _ensure_no_symlink_parents(workspace_root, relative_path)
    target = _path_under(workspace_root, relative_path)
    if target.is_symlink():
        raise ValueError("environment file observation target is a symlink")
    if not target.is_file():
        return (
            {
                "file_id": file_record["file_id"],
                "file_role": file_record["file_role"],
                "relative_path": relative_path,
                "format": file_record["format"],
                "status": "unavailable",
                "expected_digest": file_record["expected_digest"],
                "observed_digest": None,
                "expected_size_bytes": file_record["expected_size_bytes"],
                "observed_size_bytes": None,
                "parsed_summary": None,
            },
            [],
        )

    parsed_summary, parse_finding = _parse_summary(file_record, target)
    return (
        {
            "file_id": file_record["file_id"],
            "file_role": file_record["file_role"],
            "relative_path": relative_path,
            "format": file_record["format"],
            "status": "observed",
            "expected_digest": file_record["expected_digest"],
            "observed_digest": _sha256_digest(target),
            "expected_size_bytes": file_record["expected_size_bytes"],
            "observed_size_bytes": target.stat().st_size,
            "parsed_summary": parsed_summary,
        },
        [parse_finding] if parse_finding else [],
    )


def _finding(code: str, file_id: str, basis: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "file_id": file_id,
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _file_findings(observed: dict[str, Any]) -> list[dict[str, str]]:
    if observed["status"] == "unavailable":
        return [
            _finding(
                "environment_file_unavailable",
                observed["file_id"],
                "Declared environment file could not be observed under the caller root.",
                "environment_repair_or_dependency_sync",
            )
        ]

    findings = []
    if observed["observed_digest"] != observed["expected_digest"]:
        findings.append(
            _finding(
                "environment_file_digest_mismatch",
                observed["file_id"],
                "Observed sha256 digest differs from the declared environment file digest.",
                "dependency_resolution_or_file_repair",
            )
        )
    if observed["observed_size_bytes"] != observed["expected_size_bytes"]:
        findings.append(
            _finding(
                "environment_file_size_mismatch",
                observed["file_id"],
                "Observed byte size differs from the declared environment file size.",
                "dependency_resolution_or_file_repair",
            )
        )
    return findings


def _classification(observed_files: list[dict[str, Any]], findings: list[dict[str, str]]) -> str:
    if any(file_record["status"] == "unavailable" for file_record in observed_files):
        return "environment_files_unavailable_for_review"
    if any(finding["code"] in _MISMATCH_FINDING_CODES for finding in findings):
        return "environment_files_observed_with_mismatch"
    if findings:
        return "environment_files_observed_with_review_findings"
    return "environment_files_observed_match_declared_facts"


def _state_counts(observed_files: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for file_record in observed_files:
        status = file_record["status"]
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "environment_files_observed",
            "severity": "review",
            "basis": "Only explicitly declared environment files are observed.",
            "does_not_claim": "workspace_scan_or_environment_discovery",
        },
        {
            "code": "pyproject_summary_parsed",
            "severity": "info",
            "basis": "pyproject.toml is parsed only for declared manifest summary fields.",
            "does_not_claim": "dependency_resolution_or_build_backend_validation",
        },
        {
            "code": "lockfile_parse_not_performed",
            "severity": "review",
            "basis": "Lockfile availability, sha256, and size are observed without parsing package locks.",
            "does_not_claim": "locked_dependency_graph",
        },
        {
            "code": "dependency_sync_not_performed",
            "severity": "review",
            "basis": "The observer reads files and does not run package managers or install dependencies.",
            "does_not_claim": "synced_or_runnable_environment",
        },
        {
            "code": "runtime_and_hardware_probe_not_performed",
            "severity": "review",
            "basis": "The observer does not inspect interpreters, installed packages, tools, or hardware.",
            "does_not_claim": "runtime_or_control_pc_ready",
        },
    ]


def observe_environment_files(source: dict[str, Any], *, workspace_root: Path) -> dict[str, Any]:
    """Observe declared environment files under a caller-provided workspace root."""
    _validate_references(source)
    workspace_root_resolved = _existing_root(workspace_root)
    observations = [
        _observe_declared_file(file_record, workspace_root_resolved)
        for file_record in source["observation_request"]["declared_files"]
    ]
    observed_files = [observed_file for observed_file, _parse_findings in observations]
    findings = [
        finding for observed_file in observed_files for finding in _file_findings(observed_file)
    ]
    findings.extend(
        finding for _observed_file, parse_findings in observations for finding in parse_findings
    )
    environment = source["environment_record"]

    return {
        "environment_file_observation_policy": copy.deepcopy(
            source["environment_file_observation_policy"]
        ),
        "environment_record": {
            "environment_id": environment["environment_id"],
            "label": environment["label"],
            "authority": environment["authority"],
            "record_status": environment["record_status"],
            "scope": copy.deepcopy(environment["scope"]),
            "environment_claims": copy.deepcopy(environment["environment_claims"]),
            "classification": _classification(observed_files, findings),
        },
        "observation_request": {
            "request_id": source["observation_request"]["request_id"],
            "workspace_root_label": source["observation_request"]["workspace_root_label"],
            "declared_file_count": len(source["observation_request"]["declared_files"]),
        },
        "observed_files": observed_files,
        "observation_status_counts": _state_counts(observed_files),
        "review_findings": findings,
        "attention": _attention(),
    }
