"""Structured summary builder for declared environment inventory records.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read environment files, inspect installed
packages, sync dependencies, install packages, import code, execute code, or
claim runnable readiness.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "inventory_authority": "declared_records_only",
    "environment_file_observation": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_check": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "not_claimed",
    "shared_environment_schema": "not_defined",
}

_DECLARATION_STATES = {
    "declared",
    "unavailable",
    "unverified",
    "redacted",
    "unsupported",
}

_PACKAGE_PIN_STATES = {
    "exact_pin",
    "range_declared",
    "unpinned",
    "unknown",
    "unavailable",
    "redacted",
}

_FINDING_STATES = {
    "unavailable",
    "unverified",
    "redacted",
    "unsupported",
}

_ENVIRONMENT_AUTHORITIES = {
    "user_declared_inventory",
}

_ENVIRONMENT_RECORD_STATUSES = {
    "declared",
    "declared_with_review_findings",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _environment_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["environment_records"], "environment_id")


def _source_records_by_id(environment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(environment["dependency_sources"], "source_id")


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["declared_environment_inventory_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("declared environment inventory policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"declared environment inventory policy {key} must be {expected}")


def _validate_state(
    *,
    owner: str,
    state: str,
    missing_reason: str | None,
) -> None:
    if state not in _DECLARATION_STATES:
        raise ValueError(f"{owner} has unsupported declaration_state: {state}")
    if state in _FINDING_STATES and not missing_reason:
        raise ValueError(f"{owner} declaration_state {state} requires missing_reason")
    if state == "declared" and missing_reason:
        raise ValueError(f"{owner} declared item must not carry missing_reason")


def _validate_dependency_source(source_record: dict[str, Any]) -> None:
    path = source_record["path"]
    if not _path_is_relative(path):
        raise ValueError("declared environment dependency source path must be relative")
    _validate_state(
        owner=f"dependency source {source_record['source_id']}",
        state=source_record["declaration_state"],
        missing_reason=source_record.get("missing_reason"),
    )


def _validate_runtime_hint(
    hint: dict[str, Any],
    source_records: dict[str, dict[str, Any]],
) -> None:
    _validate_state(
        owner=f"runtime hint {hint['label']}",
        state=hint["declaration_state"],
        missing_reason=hint.get("missing_reason"),
    )
    source_id = hint.get("source_id")
    if source_id is not None and source_id not in source_records:
        raise ValueError(f"runtime hint {hint['label']} references missing dependency source")


def _validate_package_declaration(
    package: dict[str, Any],
    source_records: dict[str, dict[str, Any]],
) -> None:
    if package["pin_state"] not in _PACKAGE_PIN_STATES:
        raise ValueError(f"package {package['name']} has unsupported pin_state")
    _validate_state(
        owner=f"package {package['name']}",
        state=package["declaration_state"],
        missing_reason=package.get("missing_reason"),
    )
    source_id = package.get("source_id")
    if source_id is not None and source_id not in source_records:
        raise ValueError(f"package {package['name']} references missing dependency source")
    if package["declaration_state"] == "declared" and source_id is None:
        raise ValueError(f"package {package['name']} declared item requires source_id")


def _validate_external_tool(
    tool: dict[str, Any],
    source_records: dict[str, dict[str, Any]],
) -> None:
    _validate_state(
        owner=f"external tool {tool['tool_id']}",
        state=tool["declaration_state"],
        missing_reason=tool.get("missing_reason"),
    )
    source_id = tool.get("source_id")
    if source_id is not None and source_id not in source_records:
        raise ValueError(f"external tool {tool['tool_id']} references missing dependency source")


def _validate_environment_record(environment: dict[str, Any]) -> None:
    if environment["authority"] not in _ENVIRONMENT_AUTHORITIES:
        raise ValueError("declared environment authority must stay declared-only")
    if environment["record_status"] not in _ENVIRONMENT_RECORD_STATUSES:
        raise ValueError("declared environment record_status must stay declaration-only")

    claims = environment["environment_claims"]
    if claims["readiness_claim"] != "not_checked":
        raise ValueError("declared environment readiness claim must stay unchecked")
    if claims["sync_claim"] != "not_synced":
        raise ValueError("declared environment sync claim must stay not synced")
    if claims["execution_claim"] != "not_imported_loaded_or_executed":
        raise ValueError("declared environment execution claim must stay non-executing")

    source_records = _source_records_by_id(environment)
    for source_record in environment["dependency_sources"]:
        _validate_dependency_source(source_record)
        lockfile_ref = source_record.get("lockfile_ref")
        if lockfile_ref is not None and lockfile_ref not in source_records:
            raise ValueError("dependency source lockfile_ref must reference known source")

    for hint in environment["runtime_hints"]:
        _validate_runtime_hint(hint, source_records)

    seen_packages = set()
    for package in environment["package_declarations"]:
        package_key = (package["name"], package["role"])
        if package_key in seen_packages:
            raise ValueError("declared environment contains duplicate package role")
        seen_packages.add(package_key)
        _validate_package_declaration(package, source_records)

    _records_by_key(environment["external_tools"], "tool_id")
    for tool in environment["external_tools"]:
        _validate_external_tool(tool, source_records)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _environment_records_by_id(source)
    for environment in source["environment_records"]:
        _validate_environment_record(environment)


def _dependency_source_counts(environment: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_DECLARATION_STATES)}
    for source_record in environment["dependency_sources"]:
        counts[source_record["declaration_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _package_pin_counts(environment: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_PACKAGE_PIN_STATES)}
    for package in environment["package_declarations"]:
        counts[package["pin_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _tool_state_counts(environment: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_DECLARATION_STATES)}
    for tool in environment["external_tools"]:
        counts[tool["declaration_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _environment_record_summary(environment: dict[str, Any]) -> dict[str, Any]:
    claims = environment["environment_claims"]
    return {
        "environment_id": environment["environment_id"],
        "label": environment["label"],
        "authority": environment["authority"],
        "record_status": environment["record_status"],
        "scope": copy.deepcopy(environment["scope"]),
        "runtime_hint_count": len(environment["runtime_hints"]),
        "dependency_source_count": len(environment["dependency_sources"]),
        "dependency_source_state_counts": _dependency_source_counts(environment),
        "package_declaration_count": len(environment["package_declarations"]),
        "package_pin_counts": _package_pin_counts(environment),
        "external_tool_count": len(environment["external_tools"]),
        "external_tool_state_counts": _tool_state_counts(environment),
        "readiness_claim": claims["readiness_claim"],
        "sync_claim": claims["sync_claim"],
        "execution_claim": claims["execution_claim"],
    }


def _runtime_hints(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "kind": hint["kind"],
            "label": hint["label"],
            "value": hint["value"],
            "source_id": hint.get("source_id"),
            "declaration_state": hint["declaration_state"],
            "missing_reason": hint.get("missing_reason"),
        }
        for environment in source["environment_records"]
        for hint in environment["runtime_hints"]
    ]


def _dependency_sources(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "source_id": source_record["source_id"],
            "path": source_record["path"],
            "kind": source_record["kind"],
            "package_manager_hint": source_record.get("package_manager_hint"),
            "lockfile_ref": source_record.get("lockfile_ref"),
            "declaration_state": source_record["declaration_state"],
            "missing_reason": source_record.get("missing_reason"),
        }
        for environment in source["environment_records"]
        for source_record in environment["dependency_sources"]
    ]


def _package_inventory(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "name": package["name"],
            "role": package["role"],
            "requirement": package.get("requirement"),
            "pin_state": package["pin_state"],
            "source_id": package.get("source_id"),
            "declaration_state": package["declaration_state"],
            "missing_reason": package.get("missing_reason"),
        }
        for environment in source["environment_records"]
        for package in environment["package_declarations"]
    ]


def _external_tool_inventory(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "tool_id": tool["tool_id"],
            "label": tool["label"],
            "role": tool["role"],
            "version_hint": tool.get("version_hint"),
            "source_id": tool.get("source_id"),
            "declaration_state": tool["declaration_state"],
            "missing_reason": tool.get("missing_reason"),
        }
        for environment in source["environment_records"]
        for tool in environment["external_tools"]
    ]


def _environment_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for environment in source["environment_records"]:
        environment_id = environment["environment_id"]
        for hint in environment["runtime_hints"]:
            state = hint["declaration_state"]
            if state in _FINDING_STATES:
                findings.append(
                    {
                        "environment_id": environment_id,
                        "subject_type": "runtime_hint",
                        "subject_id": hint["label"],
                        "severity": "review",
                        "finding": f"runtime_hint_{state}",
                        "basis": hint.get("missing_reason"),
                        "does_not_claim": "runtime_available_or_compatible",
                    }
                )
        for source_record in environment["dependency_sources"]:
            state = source_record["declaration_state"]
            if state in _FINDING_STATES:
                findings.append(
                    {
                        "environment_id": environment_id,
                        "subject_type": "dependency_source",
                        "subject_id": source_record["source_id"],
                        "severity": "review",
                        "finding": f"dependency_source_{state}",
                        "basis": source_record.get("missing_reason"),
                        "does_not_claim": "environment_is_unusable_or_runnable",
                    }
                )
        for package in environment["package_declarations"]:
            if package["pin_state"] in {"unpinned", "unknown", "unavailable", "redacted"}:
                findings.append(
                    {
                        "environment_id": environment_id,
                        "subject_type": "package",
                        "subject_id": package["name"],
                        "severity": "review",
                        "finding": f"package_pin_{package['pin_state']}",
                        "basis": package.get("missing_reason") or package["role"],
                        "does_not_claim": "dependency_resolution_or_runtime_readiness",
                    }
                )
            state = package["declaration_state"]
            if state in _FINDING_STATES:
                findings.append(
                    {
                        "environment_id": environment_id,
                        "subject_type": "package",
                        "subject_id": package["name"],
                        "severity": "review",
                        "finding": f"package_{state}",
                        "basis": package.get("missing_reason"),
                        "does_not_claim": "dependency_resolution_or_runtime_readiness",
                    }
                )
        for tool in environment["external_tools"]:
            state = tool["declaration_state"]
            if state in _FINDING_STATES:
                findings.append(
                    {
                        "environment_id": environment_id,
                        "subject_type": "external_tool",
                        "subject_id": tool["tool_id"],
                        "severity": "review",
                        "finding": f"external_tool_{state}",
                        "basis": tool.get("missing_reason"),
                        "does_not_claim": "external_tool_available_or_compatible",
                    }
                )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["declared_environment_inventory_policy"]
    attention = []

    if policy["inventory_authority"] == "declared_records_only":
        attention.append(
            {
                "code": "declared_inventory_only",
                "severity": "info",
                "basis": "Environment inventory uses explicit declared records only.",
                "does_not_claim": "observed_runtime_state",
            }
        )

    if policy["environment_file_observation"] == "not_performed":
        attention.append(
            {
                "code": "environment_files_not_read",
                "severity": "review",
                "basis": "Dependency files are referenced as declared sources, not opened or parsed.",
                "does_not_claim": "file_contents_verified",
            }
        )

    if policy["dependency_sync"] == "not_performed":
        attention.append(
            {
                "code": "dependency_sync_not_performed",
                "severity": "review",
                "basis": "Declared package facts are not resolved or synchronized.",
                "does_not_claim": "resolved_environment",
            }
        )

    if policy["package_install"] == "not_performed":
        attention.append(
            {
                "code": "package_install_not_performed",
                "severity": "review",
                "basis": "No package manager, installer, or external tool setup is invoked.",
                "does_not_claim": "installed_dependencies",
            }
        )

    if policy["runtime_check"] == "not_performed":
        attention.append(
            {
                "code": "runtime_check_not_performed",
                "severity": "review",
                "basis": "Interpreter and external tool hints are declarations, not live checks.",
                "does_not_claim": "compatible_runtime",
            }
        )

    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Environment inventory does not import, load, or execute selected code.",
                "does_not_claim": "execution_permission",
            }
        )

    if policy["readiness_claim"] == "not_claimed":
        attention.append(
            {
                "code": "environment_readiness_not_claimed",
                "severity": "review",
                "basis": "Declared environment inventory is not a runnable-readiness check.",
                "does_not_claim": "run_can_start",
            }
        )

    return attention


def build_declared_environment_inventory_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a declared environment inventory summary from explicit fixture input."""
    _validate_references(source)
    return {
        "declared_environment_inventory_policy": copy.deepcopy(
            source["declared_environment_inventory_policy"]
        ),
        "environment_records": [
            _environment_record_summary(environment)
            for environment in source["environment_records"]
        ],
        "runtime_hints": _runtime_hints(source),
        "dependency_sources": _dependency_sources(source),
        "package_inventory": _package_inventory(source),
        "external_tool_inventory": _external_tool_inventory(source),
        "environment_findings": _environment_findings(source),
        "attention": _attention(source),
    }
