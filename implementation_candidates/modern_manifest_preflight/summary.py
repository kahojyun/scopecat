"""Approved modern manifest preflight implementation candidate.

This module reads one explicitly approved ``pyproject.toml`` file and projects
declared manifest facts. It does not read lockfiles, resolve dependencies,
sync packages, install packages, inspect runtimes, import code, execute code,
probe hardware, or claim runnable readiness.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from implementation_candidates.modern_manifest_preflight.contracts import (
    POLICY_ATTENTION_MATRIX,
    ModernManifestPreflightContract,
    path_is_relative,
    validate_modern_manifest_preflight_contract,
)

DEPENDENCY_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
DEPENDENCY_NAME_PREFIX = re.compile(
    r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\s*(?:\[|[<>=!~;]|$))"
)
DIRECT_REFERENCE = re.compile(r"\s@\s")
NORMALIZED_NAME_SEPARATOR = re.compile(r"[-_.]+")
PYTHON_SPECIFIER = re.compile(
    r"^\s*(?P<operator>~=|==|!=|<=|>=|<|>)\s*"
    r"(?P<version>[0-9]+(?:\.[0-9]+)*(?:\.\*)?)\s*$"
)


def build_modern_manifest_preflight_summary(
    source: dict[str, Any], *, workspace_root: Path
) -> dict[str, Any]:
    """Build a modern manifest preflight summary from explicit approved input."""
    contract = validate_modern_manifest_preflight_contract(source)
    workspace_root_resolved = _existing_root(workspace_root)
    manifest_summary, findings = _preflight_manifest(contract, workspace_root_resolved)
    return _build_from_contract(
        contract,
        manifest_summary=manifest_summary,
        findings=findings,
    )


def _build_from_contract(
    contract: ModernManifestPreflightContract,
    *,
    manifest_summary: dict[str, Any],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "modern_manifest_preflight_policy": contract.policy.to_summary(),
        "preflight_request": contract.request.to_summary(),
        "prepared_run_context": contract.prepared_context.to_summary(),
        "declared_environment": contract.declared_environment.to_summary(),
        "preflight_status": _preflight_status(manifest_summary, findings),
        "manifest_summary": manifest_summary,
        "dependency_group_checks": _dependency_group_checks(contract, manifest_summary),
        "preflight_findings": findings,
        "attention": _attention(contract.policy.values),
    }


def _preflight_manifest(
    contract: ModernManifestPreflightContract, workspace_root: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    request = contract.request
    _ensure_no_symlink_parents(workspace_root, request.manifest_path)
    target = _path_under(workspace_root, request.manifest_path)
    if target.is_symlink():
        raise ValueError("modern manifest preflight target is a symlink")
    if not target.is_file():
        return (
            _unavailable_manifest_summary(),
            [
                _finding(
                    "manifest_unavailable",
                    "Declared pyproject.toml could not be observed under the caller root.",
                    "environment_repair_or_dependency_sync",
                )
            ],
        )
    try:
        parsed = _parse_pyproject(target)
    except tomllib.TOMLDecodeError:
        return (
            _parse_failed_manifest_summary(),
            [
                _finding(
                    "manifest_parse_failed",
                    "Approved pyproject.toml could not be parsed as TOML.",
                    "dependency_resolution_or_runtime_compatibility",
                )
            ],
        )
    findings = _manifest_findings(contract, parsed)
    return parsed, findings


def _parse_pyproject(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    project = parsed.get("project", {})
    dependency_groups = parsed.get("dependency-groups", {})
    if not isinstance(project, dict):
        project = {}
    if not isinstance(dependency_groups, dict):
        dependency_groups = {}

    dependencies = project.get("dependencies")
    dependency_group_shapes = _dependency_group_shapes(dependency_groups)
    group_names = sorted(
        name for name, state in dependency_group_shapes.items() if state == "declared_list"
    )
    requires_python = (
        project.get("requires-python") if isinstance(project.get("requires-python"), str) else None
    )
    default_group_present = isinstance(dependencies, list)
    all_group_names = ["default"] if default_group_present else []
    all_group_names.extend(group_names)
    return {
        "manifest_kind": "pyproject_toml",
        "status": "parsed",
        "project_name": project.get("name") if isinstance(project.get("name"), str) else None,
        "requires_python": requires_python,
        "requires_python_status": (
            "declared" if _valid_requires_python(requires_python) else "missing_or_malformed"
        ),
        "dependency_names": _dependency_names(dependencies),
        "skipped_dependency_entry_count": _skipped_dependency_count(dependencies),
        "dependency_group_names": all_group_names,
        "dependency_group_shapes": dependency_group_shapes,
        "does_not_claim": "dependency_resolution_or_runtime_compatibility",
    }


def _unavailable_manifest_summary() -> dict[str, Any]:
    return {
        "manifest_kind": "pyproject_toml",
        "status": "unavailable",
        "project_name": None,
        "requires_python": None,
        "requires_python_status": "unavailable",
        "dependency_names": [],
        "skipped_dependency_entry_count": 0,
        "dependency_group_names": [],
        "dependency_group_shapes": {},
        "does_not_claim": "dependency_resolution_or_runtime_compatibility",
    }


def _parse_failed_manifest_summary() -> dict[str, Any]:
    return {
        "manifest_kind": "pyproject_toml",
        "status": "parse_failed",
        "project_name": None,
        "requires_python": None,
        "requires_python_status": "parse_failed",
        "dependency_names": [],
        "skipped_dependency_entry_count": 0,
        "dependency_group_names": [],
        "dependency_group_shapes": {},
        "does_not_claim": "dependency_resolution_or_runtime_compatibility",
    }


def _manifest_findings(
    contract: ModernManifestPreflightContract, manifest_summary: dict[str, Any]
) -> list[dict[str, str]]:
    findings = []
    if manifest_summary["requires_python_status"] == "missing_or_malformed":
        findings.append(
            _finding(
                "requires_python_missing_or_malformed",
                "Declared python_version_source is requires-python, but approved pyproject.toml does not declare a simple numeric requires-python specifier.",
                "runtime_available_or_compatible",
            )
        )
    for group, state in manifest_summary["dependency_group_shapes"].items():
        if state == "malformed_value":
            findings.append(
                _finding(
                    "dependency_group_malformed",
                    f"Dependency group {group!r} is present but is not a list-shaped declaration.",
                    "dependency_resolution_or_dependency_sync",
                    dependency_group=group,
                )
            )
    for normalized_group, groups in _duplicate_normalized_dependency_groups(
        manifest_summary["dependency_group_names"]
    ).items():
        findings.append(
            _finding(
                "dependency_group_normalization_collision",
                f"Dependency groups {groups!r} collapse to normalized name {normalized_group!r}.",
                "dependency_resolution_or_dependency_sync",
            )
        )
    manifest_groups = {
        _normalize_dependency_group(group) for group in manifest_summary["dependency_group_names"]
    }
    for group in contract.request.expected_dependency_groups:
        if _normalize_dependency_group(group) not in manifest_groups:
            findings.append(
                _finding(
                    "declared_dependency_group_missing",
                    f"Declared dependency group {group!r} is absent from approved pyproject.toml.",
                    "dependency_resolution_or_dependency_sync",
                    dependency_group=group,
                )
            )
    return findings


def _dependency_group_shapes(dependency_groups: dict[str, Any]) -> dict[str, str]:
    output = {}
    for name, value in dependency_groups.items():
        if not isinstance(name, str) or not DEPENDENCY_NAME.fullmatch(name):
            continue
        output[name] = "declared_list" if isinstance(value, list) else "malformed_value"
    return dict(sorted(output.items()))


def _normalize_dependency_group(name: str) -> str:
    return NORMALIZED_NAME_SEPARATOR.sub("-", name).lower()


def _duplicate_normalized_dependency_groups(groups: list[str]) -> dict[str, list[str]]:
    by_normalized_name: dict[str, list[str]] = {}
    for group in groups:
        by_normalized_name.setdefault(_normalize_dependency_group(group), []).append(group)
    return {
        normalized: sorted(group_names)
        for normalized, group_names in sorted(by_normalized_name.items())
        if len(group_names) > 1
    }


def _valid_requires_python(value: str | None) -> bool:
    if value is None:
        return False
    parts = [part.strip() for part in value.split(",")]
    if not parts:
        return False
    for part in parts:
        match = PYTHON_SPECIFIER.fullmatch(part)
        if not match:
            return False
        operator = match.group("operator")
        version = match.group("version")
        if "*" in version and operator not in {"==", "!="}:
            return False
        if operator == "~=" and ("*" in version or "." not in version):
            return False
    return True


def _dependency_name(dependency: Any) -> str | None:
    if not isinstance(dependency, str) or not dependency or DIRECT_REFERENCE.search(dependency):
        return None
    match = DEPENDENCY_NAME_PREFIX.match(dependency)
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


def _dependency_group_checks(
    contract: ModernManifestPreflightContract, manifest_summary: dict[str, Any]
) -> list[dict[str, str]]:
    manifest_groups = {
        _normalize_dependency_group(group) for group in manifest_summary["dependency_group_names"]
    }
    return [
        {
            "dependency_group": group,
            "state": (
                "declared_in_manifest"
                if _normalize_dependency_group(group) in manifest_groups
                else "missing_from_manifest"
            ),
            "does_not_claim": "dependency_resolution_or_dependency_sync",
        }
        for group in contract.request.expected_dependency_groups
    ]


def _preflight_status(manifest_summary: dict[str, Any], findings: list[dict[str, str]]) -> str:
    if manifest_summary["status"] == "unavailable":
        return "manifest_unavailable_for_preflight"
    if manifest_summary["status"] == "parse_failed":
        return "manifest_parse_failed_for_preflight"
    if findings:
        return "manifest_preflight_has_review_findings"
    return "manifest_preflight_passed_declared_checks"


def _attention(policy: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "code": row["code"],
            "severity": row["severity"],
            "basis": row["basis"],
            "does_not_claim": row["does_not_claim"],
        }
        for row in POLICY_ATTENTION_MATRIX
        if policy[row["policy_key"]] == row["policy_value"]
    ]


def _finding(
    code: str,
    basis: str,
    does_not_claim: str,
    *,
    dependency_group: str | None = None,
) -> dict[str, str]:
    finding = {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }
    if dependency_group is not None:
        finding["dependency_group"] = dependency_group
    return finding


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("modern manifest preflight workspace root must not be a symlink")
    if not root.is_dir():
        raise ValueError("modern manifest preflight workspace root must be an existing directory")
    return root.resolve()


def _relative_parts(relative_path: str) -> tuple[str, ...]:
    if not path_is_relative(relative_path):
        raise ValueError("modern manifest preflight path must be relative")
    return PurePosixPath(relative_path).parts


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("modern manifest preflight parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("modern manifest preflight parent is not a directory")
