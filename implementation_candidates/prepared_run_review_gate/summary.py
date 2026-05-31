"""Manual pre-run review gate over explicit prior review summaries.

This module composes prepared-run context, parameter-state gate, scope
alignment, and environment review facts into one manual pre-run review state.
It deliberately does not start runs, control hardware, write parameters, sync
dependencies, mutate workspaces, read storage, probe runtimes, import or
execute code, open GUIs, or define a shared gate schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "gate_authority": "explicit_prepared_run_review_composition",
    "input_sources": "explicit_prior_review_summaries",
    "review_scope": "manual_pre_run_context_review",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "workspace_mutation": "not_performed",
    "environment_operation": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "manual_review_state_only",
    "gui_workflow": "not_defined",
    "shared_gate_schema": "not_defined",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["review_gate_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run review gate policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared-run review gate policy {key} must be {expected}")


def _prepared_context_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["prepared_run_context_summary"]["prepared_run_contexts"],
        "prepared_run_context_id",
    )


def _validate_prepared_context_summary(source: dict[str, Any]) -> None:
    summary = source["prepared_run_context_summary"]
    policy = summary["prepared_run_context_policy"]
    for key in (
        "hardware_control",
        "parameter_write_back",
        "setup_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"prepared run context summary {key} must be not_performed")
    _prepared_context_by_id(source)


def _validate_parameter_gate_summary(source: dict[str, Any]) -> None:
    summary = source["parameter_state_gate_summary"]
    policy = summary["gate_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "fresh_storage_read",
        "catalog_discovery",
        "storage_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"parameter-state gate summary {key} must be not_performed")
    decision = summary["gate_decision"]
    if decision["run_start_claim"] != "not_claimed":
        raise ValueError("parameter-state gate summary must not claim run start")
    if decision["parameter_write_back"] != "not_performed":
        raise ValueError("parameter-state gate summary must not write parameters")
    if decision["hardware_control"] != "not_performed":
        raise ValueError("parameter-state gate summary must not control hardware")


def _validate_scope_alignment_summary(source: dict[str, Any]) -> None:
    summary = source["scope_alignment_summary"]
    policy = summary["alignment_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "fresh_storage_read",
        "catalog_discovery",
        "setup_mutation",
        "environment_sync",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"scope alignment summary {key} must be not_performed")


def _validate_environment_review_summary(source: dict[str, Any]) -> None:
    summary = source["environment_review_summary"]
    policy = summary["environment_review_bundle_policy"]
    for key in (
        "dependency_resolution",
        "dependency_sync",
        "package_install",
        "runtime_probe",
        "code_import_execution",
        "hardware_probe",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"environment review summary {key} must be not_performed")
    if policy["readiness_claim"] != "not_claimed":
        raise ValueError("environment review summary must not claim readiness")
    if policy["managed_runner"] != "not_defined":
        raise ValueError("environment review summary must not define managed runner")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["review_gate_request"]
    prepared_contexts = _prepared_context_by_id(source)
    prepared_context_id = request["prepared_run_context_id"]
    if prepared_context_id not in prepared_contexts:
        raise ValueError("review gate request references missing prepared run context")
    prepared_context = prepared_contexts[prepared_context_id]
    if prepared_context["manual_run_target"]["measurement_id"] != request["measurement_id"]:
        raise ValueError("review gate request measurement_id must match prepared run target")
    if (
        source["parameter_state_gate_summary"]["prepared_run_context"]["prepared_run_context_id"]
        != prepared_context_id
    ):
        raise ValueError("parameter-state gate prepared_run_context_id must match request")
    if (
        source["scope_alignment_summary"]["scope_summary"]["prepared_run_context_id"]
        != prepared_context_id
    ):
        raise ValueError("scope alignment prepared_run_context_id must match request")
    if (
        source["scope_alignment_summary"]["scope_summary"]["measurement_id"]
        != request["measurement_id"]
    ):
        raise ValueError("scope alignment measurement_id must match request")
    for bundle in source["environment_review_summary"]["review_bundles"]:
        if bundle["prepared_run_context_id"] != prepared_context_id:
            raise ValueError("environment review bundle prepared_run_context_id must match request")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_prepared_context_summary(source)
    _validate_parameter_gate_summary(source)
    _validate_scope_alignment_summary(source)
    _validate_environment_review_summary(source)
    _validate_request(source)


def _review_item(
    *,
    area: str,
    state: str,
    reason_codes: list[str],
    finding_count: int,
) -> dict[str, Any]:
    return {
        "area": area,
        "state": state,
        "reason_codes": list(reason_codes),
        "finding_count": finding_count,
    }


def _prepared_context_findings(
    source: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    prepared_context_id = source["review_gate_request"]["prepared_run_context_id"]
    return [
        finding
        for finding in source["prepared_run_context_summary"][key]
        if finding["prepared_run_context_id"] == prepared_context_id
    ]


def _required_context_item(source: dict[str, Any]) -> dict[str, Any]:
    findings = _prepared_context_findings(source, "missing_context_findings")
    return _review_item(
        area="required_context",
        state="blocked_by_required_context" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _workspace_item(source: dict[str, Any]) -> dict[str, Any]:
    findings = _prepared_context_findings(source, "workspace_context_findings")
    return _review_item(
        area="workspace",
        state="needs_workspace_review" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _parameter_item(source: dict[str, Any]) -> dict[str, Any]:
    decision = source["parameter_state_gate_summary"]["gate_decision"]
    state_map = {
        "ready_for_manual_run_review": "ready_for_manual_review",
        "needs_parameter_review": "needs_parameter_review",
        "blocked_by_required_parameter_context": "blocked_by_required_context",
    }
    return _review_item(
        area="parameter_state",
        state=state_map[decision["gate_state"]],
        reason_codes=list(decision["reason_codes"]),
        finding_count=len(source["parameter_state_gate_summary"]["review_findings"]),
    )


def _scope_item(source: dict[str, Any]) -> dict[str, Any]:
    summary = source["scope_alignment_summary"]
    state_map = {
        "scope_alignment_ready": "ready_for_manual_review",
        "scope_alignment_needs_review": "needs_scope_review",
        "scope_alignment_blocked_for_review": "needs_scope_review",
    }
    return _review_item(
        area="scope_alignment",
        state=state_map[summary["classification"]],
        reason_codes=[finding["code"] for finding in summary["review_findings"]],
        finding_count=len(summary["review_findings"]),
    )


def _environment_item(source: dict[str, Any]) -> dict[str, Any]:
    findings = source["environment_review_summary"]["environment_review_findings"]
    return _review_item(
        area="environment",
        state="needs_environment_review" if findings else "ready_for_manual_review",
        reason_codes=[finding["finding"] for finding in findings],
        finding_count=len(findings),
    )


def _review_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _required_context_item(source),
        _parameter_item(source),
        _scope_item(source),
        _workspace_item(source),
        _environment_item(source),
    ]


def _overall_state(items: list[dict[str, Any]]) -> str:
    states = {item["state"] for item in items}
    if "blocked_by_required_context" in states:
        return "blocked_by_required_context"
    needs_review = sorted(state for state in states if state != "ready_for_manual_review")
    if needs_review:
        return "manual_pre_run_review_needed"
    return "ready_for_manual_review"


def _recommended_action(overall_state: str) -> str:
    if overall_state == "ready_for_manual_review":
        return "present_manual_pre_run_review"
    if overall_state == "blocked_by_required_context":
        return "repair_required_context_before_manual_pre_run_review"
    return "review_flagged_context_areas_before_manual_pre_run_review"


def _finding(
    source_area: str,
    source_finding: dict[str, Any],
    *,
    code_key: str,
) -> dict[str, Any]:
    return {
        "source_area": source_area,
        "code": source_finding[code_key],
        "severity": "review",
        "basis": copy.deepcopy(source_finding["basis"]),
        "does_not_claim": source_finding["does_not_claim"],
    }


def _aggregated_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    findings.extend(
        _finding("required_context", finding, code_key="finding")
        for finding in _prepared_context_findings(source, "missing_context_findings")
    )
    findings.extend(
        _finding("workspace", finding, code_key="finding")
        for finding in _prepared_context_findings(source, "workspace_context_findings")
    )
    findings.extend(
        _finding("parameter_state", finding, code_key="code")
        for finding in source["parameter_state_gate_summary"]["review_findings"]
    )
    findings.extend(
        _finding("scope_alignment", finding, code_key="code")
        for finding in source["scope_alignment_summary"]["review_findings"]
    )
    findings.extend(
        _finding("environment", finding, code_key="finding")
        for finding in source["environment_review_summary"]["environment_review_findings"]
    )
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "manual_review_gate_only",
            "severity": "info",
            "basis": "The gate composes prior review summaries into one manual pre-run review state.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
        {
            "code": "no_fresh_observation_or_operation",
            "severity": "review",
            "basis": "The gate does not inspect files, storage, environments, runtimes, or hardware.",
            "does_not_claim": "fresh_readiness_or_integrity_check",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "The gate does not apply selected parameter values.",
            "does_not_claim": "parameter_application",
        },
        {
            "code": "execution_not_granted",
            "severity": "review",
            "basis": "The gate does not import code, sync dependencies, or start a run.",
            "does_not_claim": "execution_permission",
        },
    ]


def build_prepared_run_review_gate_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a manual pre-run review gate from explicit prior summaries."""
    _validate_references(source)
    items = _review_items(source)
    overall_state = _overall_state(items)
    return {
        "review_gate_policy": copy.deepcopy(source["review_gate_policy"]),
        "review_gate_request": copy.deepcopy(source["review_gate_request"]),
        "gate_decision": {
            "overall_state": overall_state,
            "recommended_action": _recommended_action(overall_state),
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
        },
        "prepared_run_context": copy.deepcopy(
            _prepared_context_by_id(source)[
                source["review_gate_request"]["prepared_run_context_id"]
            ]
        ),
        "review_items": items,
        "aggregated_review_findings": _aggregated_findings(source),
        "attention": _attention(),
    }
