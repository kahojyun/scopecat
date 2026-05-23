"""Structured summary builder for environment readiness planning.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read dependency files, inspect installed
packages, sync dependencies, install packages, import code, execute code,
probe hardware, or claim runnable readiness.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "readiness_authority": "planned_checks_from_declared_context",
    "environment_file_observation": "not_performed",
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

_EXPECTED_READINESS_CLAIMS = {
    "readiness_claim": "not_checked",
    "sync_claim": "not_performed",
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

_READINESS_AUTHORITIES = {
    "planned_checks_from_declared_context",
}

_READINESS_STATUSES = {
    "planned",
    "planned_with_review_findings",
}

_CHECK_STATES = {
    "planned",
    "review_required",
    "blocked",
    "unsupported",
}

_CHECK_STATES_WITH_FINDINGS = {
    "review_required",
    "blocked",
    "unsupported",
}

_MODERN_MANAGERS = {
    "uv",
}

_MANIFEST_STATES = {
    "declared",
}

_NOTE_STATES = {
    "declared",
    "review_required",
    "blocked",
    "unsupported",
}

_CHECK_RULES = {
    "modern_manifest_review": {
        "subject_type": "modern_python_environment",
        "does_not_claim": "environment_files_verified_or_synced",
    },
    "python_version_review": {
        "subject_type": "modern_python_environment",
        "does_not_claim": "runtime_available_or_compatible",
    },
    "dependency_group_review": {
        "subject_type": "modern_python_environment",
        "does_not_claim": "resolved_or_synced_environment",
    },
    "external_runtime_review": {
        "subject_type": "external_runtime_note",
        "does_not_claim": "external_tool_available_or_compatible",
    },
    "migration_review": {
        "subject_type": "migration_note",
        "does_not_claim": "legacy_environment_migrated",
    },
}


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
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["environment_readiness_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("environment readiness policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"environment readiness policy {key} must be {expected}")


def _validate_modern_environment(environment: dict[str, Any]) -> None:
    manifest = environment["modern_python_environment"]
    if manifest["manager"] not in _MODERN_MANAGERS:
        raise ValueError("environment readiness currently supports uv as the modern manager")
    if manifest["manifest_state"] not in _MANIFEST_STATES:
        raise ValueError("modern python environment has unsupported manifest_state")
    for key in ("pyproject_path", "lockfile_path"):
        if not _path_is_relative(manifest[key]):
            raise ValueError(f"modern python environment {key} must be relative")
    dependency_groups = manifest["dependency_groups"]
    if not dependency_groups:
        raise ValueError("modern python environment requires at least one dependency group")
    seen_groups = set()
    for group in dependency_groups:
        if not isinstance(group, str) or not group:
            raise ValueError(
                "modern python environment dependency groups must be non-empty strings"
            )
        if group in seen_groups:
            raise ValueError(f"duplicate dependency group: {group}")
        seen_groups.add(group)
    if manifest["python_version_source"] != "requires-python":
        raise ValueError("modern python environment python_version_source must be requires-python")


def _validate_scope(scope: dict[str, Any], *, owner: str) -> None:
    if set(scope) != _EXPECTED_SCOPE_KEYS:
        raise ValueError(f"{owner} scope must match expected shape")
    for key in _EXPECTED_SCOPE_KEYS:
        if not isinstance(scope[key], str) or not scope[key]:
            raise ValueError(f"{owner} scope {key} must be a non-empty string")


def _validate_note(note: dict[str, Any], *, key: str, owner: str) -> None:
    if not note[key]:
        raise ValueError(f"{owner} requires {key}")
    if note["state"] not in _NOTE_STATES:
        raise ValueError(f"{owner} has unsupported state")
    if note["state"] != "declared" and not note.get("review_reason"):
        raise ValueError(f"{owner} state requires review_reason")
    if note["state"] == "declared" and note.get("review_reason"):
        raise ValueError(f"{owner} declared note must not carry review_reason")


def _validate_environment_record(environment: dict[str, Any]) -> None:
    if environment["authority"] not in _ENVIRONMENT_AUTHORITIES:
        raise ValueError("declared environment authority must stay declared-only")
    _validate_scope(environment["scope"], owner="declared environment")
    has_review_notes = any(
        note["state"] != "declared"
        for note in [
            *environment["external_runtime_notes"],
            *environment["migration_notes"],
        ]
    )
    expected_status = "declared_with_review_findings" if has_review_notes else "declared"
    if environment["record_status"] not in _ENVIRONMENT_RECORD_STATUSES:
        raise ValueError("declared environment record_status must stay declaration-only")
    if environment["record_status"] != expected_status:
        raise ValueError(f"declared environment record_status must be {expected_status}")
    _validate_modern_environment(environment)
    _records_by_key(environment["external_runtime_notes"], "note_id")
    _records_by_key(environment["migration_notes"], "note_id")
    for note in environment["external_runtime_notes"]:
        _validate_note(note, key="note_id", owner=f"external runtime note {note['note_id']}")
    for note in environment["migration_notes"]:
        _validate_note(note, key="note_id", owner=f"migration note {note['note_id']}")


def _subjects(environment: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    manifest = environment["modern_python_environment"]
    subjects = {
        (
            "modern_python_environment",
            manifest["environment_ref"],
        ): manifest,
    }
    subjects.update(
        {
            ("external_runtime_note", note["note_id"]): note
            for note in environment["external_runtime_notes"]
        }
    )
    subjects.update(
        {("migration_note", note["note_id"]): note for note in environment["migration_notes"]}
    )
    return subjects


def _validate_readiness_plan(
    plan: dict[str, Any],
    environments: dict[str, dict[str, Any]],
) -> None:
    if plan["authority"] not in _READINESS_AUTHORITIES:
        raise ValueError("environment readiness authority must stay planned-only")
    if plan["record_status"] not in _READINESS_STATUSES:
        raise ValueError("environment readiness record_status must stay planning-only")
    environment_id = plan["declared_environment_id"]
    if environment_id not in environments:
        raise ValueError("readiness plan references missing declared environment")
    environment = environments[environment_id]
    if plan["scope"] != environment["scope"]:
        raise ValueError("readiness plan scope must match declared environment scope")
    has_review_checks = any(
        check["state"] in _CHECK_STATES_WITH_FINDINGS for check in plan["check_intentions"]
    )
    expected_status = "planned_with_review_findings" if has_review_checks else "planned"

    claims = plan["readiness_claims"]
    if set(claims) != set(_EXPECTED_READINESS_CLAIMS):
        raise ValueError("environment readiness claims must match expected shape")
    if plan["record_status"] != expected_status:
        raise ValueError(f"environment readiness record_status must be {expected_status}")
    for key, expected in _EXPECTED_READINESS_CLAIMS.items():
        if claims[key] != expected:
            raise ValueError(f"environment readiness {key} must be {expected}")

    subjects = _subjects(environment)
    _records_by_key(plan["check_intentions"], "check_id")

    for check in plan["check_intentions"]:
        check_type = check["check_type"]
        if check_type not in _CHECK_RULES:
            raise ValueError(f"check {check['check_id']} has unsupported check_type")
        if check["state"] not in _CHECK_STATES:
            raise ValueError(f"check {check['check_id']} has unsupported state")
        expected_subject_type = _CHECK_RULES[check_type]["subject_type"]
        if check["subject_type"] != expected_subject_type:
            raise ValueError(
                f"check {check['check_id']} subject_type must be {expected_subject_type}"
            )
        if (check["subject_type"], check["subject_id"]) not in subjects:
            raise ValueError(f"check {check['check_id']} references missing subject")
        if check["state"] in _CHECK_STATES_WITH_FINDINGS and not check.get("review_reason"):
            raise ValueError(f"check {check['check_id']} state requires review_reason")
        if check["state"] == "planned" and check.get("review_reason"):
            raise ValueError(f"check {check['check_id']} planned check must not carry reason")

    check_subjects = {
        (check["subject_type"], check["subject_id"], check["check_type"], check["state"])
        for check in plan["check_intentions"]
    }
    for note in environment["external_runtime_notes"]:
        if (
            note["state"] != "declared"
            and (
                "external_runtime_note",
                note["note_id"],
                "external_runtime_review",
                note["state"],
            )
            not in check_subjects
        ):
            raise ValueError(
                f"external runtime note {note['note_id']} requires matching review check"
            )
    for note in environment["migration_notes"]:
        if (
            note["state"] != "declared"
            and (
                "migration_note",
                note["note_id"],
                "migration_review",
                note["state"],
            )
            not in check_subjects
        ):
            raise ValueError(f"migration note {note['note_id']} requires matching review check")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    environments = _records_by_key(source["declared_environment_records"], "environment_id")
    for environment in source["declared_environment_records"]:
        _validate_environment_record(environment)
    _records_by_key(source["readiness_plans"], "readiness_plan_id")
    for plan in source["readiness_plans"]:
        _validate_readiness_plan(plan, environments)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _environment_summaries(source: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for environment in source["declared_environment_records"]:
        manifest = environment["modern_python_environment"]
        summaries.append(
            {
                "environment_id": environment["environment_id"],
                "label": environment["label"],
                "authority": environment["authority"],
                "record_status": environment["record_status"],
                "scope": copy.deepcopy(environment["scope"]),
                "manager": manifest["manager"],
                "pyproject_path": manifest["pyproject_path"],
                "lockfile_path": manifest["lockfile_path"],
                "python_version_source": manifest["python_version_source"],
                "dependency_groups": list(manifest["dependency_groups"]),
                "manifest_state": manifest["manifest_state"],
                "external_runtime_note_count": len(environment["external_runtime_notes"]),
                "external_runtime_state_counts": _state_counts(
                    environment["external_runtime_notes"], "state"
                ),
                "migration_note_count": len(environment["migration_notes"]),
                "migration_state_counts": _state_counts(environment["migration_notes"], "state"),
            }
        )
    return summaries


def _readiness_plan_summaries(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "readiness_plan_id": plan["readiness_plan_id"],
            "label": plan["label"],
            "authority": plan["authority"],
            "record_status": plan["record_status"],
            "declared_environment_id": plan["declared_environment_id"],
            "scope": copy.deepcopy(plan["scope"]),
            "check_count": len(plan["check_intentions"]),
            "check_state_counts": _state_counts(plan["check_intentions"], "state"),
            "readiness_claim": plan["readiness_claims"]["readiness_claim"],
            "sync_claim": plan["readiness_claims"]["sync_claim"],
            "execution_claim": plan["readiness_claims"]["execution_claim"],
            "hardware_claim": plan["readiness_claims"]["hardware_claim"],
        }
        for plan in source["readiness_plans"]
    ]


def _planned_checks(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "readiness_plan_id": plan["readiness_plan_id"],
            "check_id": check["check_id"],
            "check_type": check["check_type"],
            "subject_type": check["subject_type"],
            "subject_id": check["subject_id"],
            "state": check["state"],
            "review_reason": check.get("review_reason"),
            "does_not_claim": _CHECK_RULES[check["check_type"]]["does_not_claim"],
        }
        for plan in source["readiness_plans"]
        for check in plan["check_intentions"]
    ]


def _readiness_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for plan in source["readiness_plans"]:
        for check in plan["check_intentions"]:
            if check["state"] in _CHECK_STATES_WITH_FINDINGS:
                findings.append(
                    {
                        "readiness_plan_id": plan["readiness_plan_id"],
                        "check_id": check["check_id"],
                        "subject_type": check["subject_type"],
                        "subject_id": check["subject_id"],
                        "severity": "review",
                        "finding": f"check_{check['state']}",
                        "basis": check.get("review_reason"),
                        "does_not_claim": _CHECK_RULES[check["check_type"]]["does_not_claim"],
                    }
                )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["environment_readiness_policy"]
    attention = []

    if policy["readiness_authority"] == "planned_checks_from_declared_context":
        attention.append(
            {
                "code": "readiness_plan_only",
                "severity": "info",
                "basis": "Readiness output is a plan from explicit declared context.",
                "does_not_claim": "observed_runtime_state",
            }
        )
    if policy["environment_file_observation"] == "not_performed":
        attention.append(
            {
                "code": "environment_files_not_read",
                "severity": "review",
                "basis": "pyproject.toml and lockfile paths are declared, not opened or parsed.",
                "does_not_claim": "file_contents_verified",
            }
        )
    if policy["dependency_resolution"] == "not_performed":
        attention.append(
            {
                "code": "dependency_resolution_not_performed",
                "severity": "review",
                "basis": "Dependency group resolution is planned but not run.",
                "does_not_claim": "resolved_environment",
            }
        )
    if policy["dependency_sync"] == "not_performed":
        attention.append(
            {
                "code": "dependency_sync_not_performed",
                "severity": "review",
                "basis": "No uv sync operation is invoked.",
                "does_not_claim": "synchronized_environment",
            }
        )
    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Readiness planning does not import, load, or execute selected code.",
                "does_not_claim": "execution_permission",
            }
        )
    if policy["hardware_probe"] == "not_performed":
        attention.append(
            {
                "code": "hardware_probe_not_performed",
                "severity": "review",
                "basis": "External runtime notes are not control-PC or hardware probes.",
                "does_not_claim": "control_pc_or_hardware_ready",
            }
        )
    if policy["readiness_claim"] == "not_claimed":
        attention.append(
            {
                "code": "environment_readiness_not_claimed",
                "severity": "review",
                "basis": "The plan does not decide whether the run can start.",
                "does_not_claim": "run_can_start",
            }
        )

    return attention


def build_environment_readiness_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build an environment readiness plan summary from explicit fixture input."""
    _validate_references(source)
    return {
        "environment_readiness_policy": copy.deepcopy(source["environment_readiness_policy"]),
        "declared_environment_records": _environment_summaries(source),
        "readiness_plans": _readiness_plan_summaries(source),
        "planned_checks": _planned_checks(source),
        "readiness_findings": _readiness_findings(source),
        "attention": _attention(source),
    }
