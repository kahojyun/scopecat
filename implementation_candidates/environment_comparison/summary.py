"""Structured summary builder for declared environment comparison findings.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read environment files, resolve dependencies,
sync dependencies, install packages, probe runtimes, import code, execute code,
probe hardware, or claim runnable readiness.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "fact_source": "declared_environment_context_facts",
    "comparison_scope": "explicit_declared_environment_facts",
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

_DECLARATION_STATES = {
    "declared",
    "unverified",
    "unsupported",
    "unavailable",
    "redacted",
}

_FINDING_STATES = {
    "unverified",
    "unsupported",
    "unavailable",
    "redacted",
}

_PATH_FACT_KEYS = {
    ("modern_python_environment", "pyproject_path"),
    ("modern_python_environment", "lockfile_path"),
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


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["environment_comparison_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("environment comparison policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"environment comparison policy {key} must be {expected}")


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


def _validate_scope(scope: dict[str, Any], *, owner: str) -> None:
    if set(scope) != _EXPECTED_SCOPE_KEYS:
        raise ValueError(f"{owner} scope must match expected shape")
    for key in _EXPECTED_SCOPE_KEYS:
        if not isinstance(scope[key], str) or not scope[key]:
            raise ValueError(f"{owner} scope {key} must be a non-empty string")


def _fact_key(fact: dict[str, Any]) -> tuple[str, str]:
    return (fact["fact_type"], fact["fact_id"])


def _facts_by_key(environment: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    output = {}
    for fact in environment["declared_environment_facts"]:
        key = _fact_key(fact)
        if key in output:
            raise ValueError(
                "duplicate declared environment fact: "
                f"{environment['environment_id']} {key[0]} {key[1]}"
            )
        output[key] = fact
    return output


def _validate_fact(environment_id: str, fact: dict[str, Any]) -> None:
    if not fact["fact_type"] or not fact["fact_id"]:
        raise ValueError(f"declared environment fact in {environment_id} requires identity")
    state = fact["declaration_state"]
    if state not in _DECLARATION_STATES:
        raise ValueError(f"declared environment fact {fact['fact_id']} has unsupported state")
    reason = fact.get("review_reason")
    if state in _FINDING_STATES and not reason:
        raise ValueError(f"declared environment fact {fact['fact_id']} requires review_reason")
    if state == "declared" and reason:
        raise ValueError(f"declared environment fact {fact['fact_id']} must not carry reason")
    if (
        state != "redacted"
        and _fact_key(fact) in _PATH_FACT_KEYS
        and not _path_is_relative(fact["value"])
    ):
        raise ValueError(f"declared environment path fact {fact['fact_id']} must be relative")


def _validate_environment_record(environment: dict[str, Any]) -> None:
    if environment["authority"] not in _ENVIRONMENT_AUTHORITIES:
        raise ValueError("declared environment authority must stay declared-only")
    if environment["record_status"] not in _ENVIRONMENT_RECORD_STATUSES:
        raise ValueError("declared environment record_status must stay declaration-only")
    _validate_scope(environment["scope"], owner="declared environment")

    claims = environment["environment_claims"]
    if set(claims) != set(_EXPECTED_ENVIRONMENT_CLAIMS):
        raise ValueError("declared environment claims must match expected shape")
    for key, expected in _EXPECTED_ENVIRONMENT_CLAIMS.items():
        if claims[key] != expected:
            raise ValueError(f"declared environment {key} must be {expected}")

    has_review_facts = any(
        fact["declaration_state"] in _FINDING_STATES
        for fact in environment["declared_environment_facts"]
    )
    expected_status = "declared_with_review_findings" if has_review_facts else "declared"
    if environment["record_status"] != expected_status:
        raise ValueError(f"declared environment record_status must be {expected_status}")

    _facts_by_key(environment)
    for fact in environment["declared_environment_facts"]:
        _validate_fact(environment["environment_id"], fact)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    environments = _environment_records_by_id(source)
    for environment in source["environment_records"]:
        _validate_environment_record(environment)

    _records_by_key(source["comparison_sets"], "comparison_id")
    for comparison in source["comparison_sets"]:
        baseline_id = comparison["baseline_environment_id"]
        comparison_id = comparison["comparison_environment_id"]
        if baseline_id not in environments:
            raise ValueError(f"comparison references missing baseline environment: {baseline_id}")
        if comparison_id not in environments:
            raise ValueError(
                f"comparison references missing comparison environment: {comparison_id}"
            )
        if baseline_id == comparison_id:
            raise ValueError("comparison must use two distinct declared environments")


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _environment_summaries(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "label": environment["label"],
            "authority": environment["authority"],
            "record_status": environment["record_status"],
            "scope": copy.deepcopy(environment["scope"]),
            "fact_count": len(environment["declared_environment_facts"]),
            "declaration_state_counts": _state_counts(
                environment["declared_environment_facts"], "declaration_state"
            ),
            "readiness_claim": environment["environment_claims"]["readiness_claim"],
            "sync_claim": environment["environment_claims"]["sync_claim"],
            "execution_claim": environment["environment_claims"]["execution_claim"],
            "hardware_claim": environment["environment_claims"]["hardware_claim"],
        }
        for environment in source["environment_records"]
    ]


def _environment_facts(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "environment_id": environment["environment_id"],
            "fact_type": fact["fact_type"],
            "fact_id": fact["fact_id"],
            "label": fact["label"],
            "value": _public_fact_value(fact),
            "declaration_state": fact["declaration_state"],
            "review_reason": fact.get("review_reason"),
        }
        for environment in source["environment_records"]
        for fact in environment["declared_environment_facts"]
    ]


def _fact_state(fact: dict[str, Any] | None) -> str:
    if fact is None:
        return "absent"
    return fact["declaration_state"]


def _public_fact_value(fact: dict[str, Any] | None) -> Any:
    if fact is None or fact["declaration_state"] == "redacted":
        return None
    return copy.deepcopy(fact["value"])


def _finding_for_fact(
    comparison: dict[str, Any],
    baseline_fact: dict[str, Any] | None,
    comparison_fact: dict[str, Any] | None,
) -> dict[str, Any]:
    baseline_state = _fact_state(baseline_fact)
    comparison_state = _fact_state(comparison_fact)

    if baseline_fact is None or comparison_fact is None:
        finding = "missing"
        basis = "Fact is present on only one declared environment record."
        does_not_claim = "intentional_removal_or_runtime_absence"
    elif "redacted" in {baseline_state, comparison_state}:
        finding = "redacted"
        basis = "At least one side is declared redacted, so the fact is hidden."
        does_not_claim = "hidden_fact_equality_or_difference"
    elif "unsupported" in {baseline_state, comparison_state}:
        finding = "unsupported"
        basis = "At least one side uses an unsupported declared environment fact."
        does_not_claim = "comparable_runtime_meaning"
    elif {baseline_state, comparison_state} & {"unverified", "unavailable"}:
        finding = "unverified"
        basis = "At least one side lacks a verified declaration for this fact."
        does_not_claim = "fact_truth_or_runtime_availability"
    elif baseline_fact["value"] == comparison_fact["value"]:
        finding = "same_declared"
        basis = "Both sides declare the same value for this environment fact."
        does_not_claim = "runtime_equivalence_or_environment_readiness"
    else:
        finding = "changed"
        basis = "Both sides declare different values for this environment fact."
        does_not_claim = "dependency_resolution_or_runtime_effect"

    fact = baseline_fact if baseline_fact is not None else comparison_fact
    return {
        "comparison_id": comparison["comparison_id"],
        "fact_type": fact["fact_type"],
        "fact_id": fact["fact_id"],
        "label": fact["label"],
        "finding": finding,
        "baseline_environment_id": comparison["baseline_environment_id"],
        "comparison_environment_id": comparison["comparison_environment_id"],
        "baseline_declaration_state": baseline_state,
        "comparison_declaration_state": comparison_state,
        "baseline_value": _public_fact_value(baseline_fact),
        "comparison_value": _public_fact_value(comparison_fact),
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _findings_for_comparison(
    comparison: dict[str, Any],
    baseline_environment: dict[str, Any],
    comparison_environment: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_facts = _facts_by_key(baseline_environment)
    comparison_facts = _facts_by_key(comparison_environment)
    keys = sorted(set(baseline_facts) | set(comparison_facts))
    return [
        _finding_for_fact(comparison, baseline_facts.get(key), comparison_facts.get(key))
        for key in keys
    ]


def _all_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    environments = _environment_records_by_id(source)
    return [
        finding
        for comparison in source["comparison_sets"]
        for finding in _findings_for_comparison(
            comparison,
            environments[comparison["baseline_environment_id"]],
            environments[comparison["comparison_environment_id"]],
        )
    ]


def _finding_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        code = finding["finding"]
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _comparison_set_summaries(
    source: dict[str, Any],
    findings_by_comparison: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        {
            "comparison_id": comparison["comparison_id"],
            "baseline_environment_id": comparison["baseline_environment_id"],
            "comparison_environment_id": comparison["comparison_environment_id"],
            "comparison_purpose": comparison["comparison_purpose"],
            "compared_fact_count": len(findings_by_comparison[comparison["comparison_id"]]),
            "finding_counts": _finding_counts(findings_by_comparison[comparison["comparison_id"]]),
        }
        for comparison in source["comparison_sets"]
    ]


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["environment_comparison_policy"]
    attention = []

    if policy["fact_source"] == "declared_environment_context_facts":
        attention.append(
            {
                "code": "comparison_uses_declared_environment_facts",
                "severity": "info",
                "basis": "Comparison uses explicit declared environment facts only.",
                "does_not_claim": "observed_runtime_state",
            }
        )
    if policy["environment_file_observation"] == "not_performed":
        attention.append(
            {
                "code": "environment_files_not_read",
                "severity": "review",
                "basis": "Manifest and lockfile facts are declarations, not opened files.",
                "does_not_claim": "file_contents_verified",
            }
        )
    if policy["dependency_resolution"] == "not_performed":
        attention.append(
            {
                "code": "dependency_resolution_not_performed",
                "severity": "review",
                "basis": "Changed or missing dependency declarations are not resolved.",
                "does_not_claim": "resolved_environment",
            }
        )
    if policy["dependency_sync"] == "not_performed":
        attention.append(
            {
                "code": "dependency_sync_not_performed",
                "severity": "review",
                "basis": "No dependency sync operation is invoked by comparison.",
                "does_not_claim": "synchronized_environment",
            }
        )
    if policy["runtime_probe"] == "not_performed":
        attention.append(
            {
                "code": "runtime_probe_not_performed",
                "severity": "review",
                "basis": "Python and external-runtime facts are not live runtime probes.",
                "does_not_claim": "compatible_runtime",
            }
        )
    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Environment comparison does not import, load, or execute code.",
                "does_not_claim": "execution_permission",
            }
        )
    if policy["hardware_probe"] == "not_performed":
        attention.append(
            {
                "code": "hardware_probe_not_performed",
                "severity": "review",
                "basis": "External runtime differences are not control-PC or hardware probes.",
                "does_not_claim": "control_pc_or_hardware_ready",
            }
        )
    if policy["readiness_claim"] == "not_claimed":
        attention.append(
            {
                "code": "environment_readiness_not_claimed",
                "severity": "review",
                "basis": "Comparison does not decide whether the selected run can start.",
                "does_not_claim": "run_can_start",
            }
        )

    return attention


def build_environment_comparison_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build declared environment comparison findings from explicit fixture input."""
    _validate_references(source)
    findings = _all_findings(source)
    findings_by_comparison = {
        comparison["comparison_id"]: [
            finding
            for finding in findings
            if finding["comparison_id"] == comparison["comparison_id"]
        ]
        for comparison in source["comparison_sets"]
    }
    return {
        "environment_comparison_policy": copy.deepcopy(source["environment_comparison_policy"]),
        "environment_records": _environment_summaries(source),
        "environment_facts": _environment_facts(source),
        "comparison_sets": _comparison_set_summaries(source, findings_by_comparison),
        "environment_fact_findings": findings,
        "attention": _attention(source),
    }
