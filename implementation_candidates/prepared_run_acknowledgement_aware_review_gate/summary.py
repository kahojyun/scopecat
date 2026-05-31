"""Acknowledgement-aware manual pre-run review composition."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "gate_authority": "explicit_acknowledgement_aware_pre_run_review_composition",
    "acknowledgement_source": "prepared_run_partial_target_acknowledgement_summary",
    "input_sources": "explicit_prior_review_summaries",
    "review_scope": "manual_pre_run_context_review_after_acknowledgement",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "dependency_resolution": "not_performed",
    "dependency_sync": "not_performed",
    "package_install": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "setup_mutation": "not_performed",
    "workspace_mutation": "not_performed",
    "environment_operation": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "manual_review_state_only",
    "gui_workflow": "not_defined",
    "managed_runner": "not_defined",
    "shared_gate_schema": "not_defined",
}

_REVIEW_FINDING_KEYS = (
    "required_context_findings",
    "workspace_findings",
    "environment_findings",
)


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["acknowledgement_aware_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("acknowledgement-aware review policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"acknowledgement-aware review policy {key} must be {expected}")


def _validate_acknowledgement_summary(source: dict[str, Any]) -> None:
    summary = source["partial_target_acknowledgement_summary"]
    policy = summary["acknowledgement_policy"]
    for key in (
        "parameter_invalidation",
        "parameter_write_back",
        "hardware_control",
        "automatic_run_start",
        "scope_repair",
        "setup_mutation",
        "catalog_discovery",
        "fresh_storage_read",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"partial target acknowledgement policy {key} must be not_performed")
    if policy["compatibility_output"] != "not_produced":
        raise ValueError("partial target acknowledgement must not produce compatibility output")
    side_effects = summary["side_effects"]
    for key in (
        "parameter_invalidation",
        "parameter_write_back",
        "hardware_control",
        "automatic_run_start",
        "scope_repair",
        "setup_mutation",
        "catalog_discovery",
        "fresh_storage_read",
    ):
        if side_effects[key] != "not_performed":
            raise ValueError(
                f"partial target acknowledgement side effect {key} must be not_performed"
            )
    if side_effects["compatibility_output"] != "not_produced":
        raise ValueError(
            "partial target acknowledgement side effect compatibility_output must be not_produced"
        )
    downstream = summary["downstream_review_state"]
    if downstream["run_start_claim"] != "not_claimed":
        raise ValueError("partial target acknowledgement must not claim run start")
    if downstream["hardware_control"] != "not_performed":
        raise ValueError("partial target acknowledgement must not control hardware")
    if downstream["parameter_write_back"] != "not_performed":
        raise ValueError("partial target acknowledgement must not write parameters")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["review_request"]
    acknowledgement = source["partial_target_acknowledgement_summary"]
    context = acknowledgement["prepared_run_context"]
    if request["prepared_run_context_id"] != context["prepared_run_context_id"]:
        raise ValueError("review request prepared_run_context_id must match acknowledgement")
    if request["measurement_id"] != context["measurement_id"]:
        raise ValueError("review request measurement_id must match acknowledgement")
    if request["parameter_state_id"] != acknowledgement["selected_parameter_state"]["state_id"]:
        raise ValueError("review request parameter_state_id must match acknowledgement")


def _validate_review_area_inputs(source: dict[str, Any]) -> None:
    prepared_run_context_id = source["review_request"]["prepared_run_context_id"]
    inputs = source["review_area_inputs"]
    if set(inputs) != set(_REVIEW_FINDING_KEYS):
        raise ValueError("review area input shape")
    for key in _REVIEW_FINDING_KEYS:
        for finding in inputs[key]:
            if finding["prepared_run_context_id"] != prepared_run_context_id:
                raise ValueError(f"{key} prepared_run_context_id must match request")
            if finding["severity"] != "review":
                raise ValueError(f"{key} only supports review severity")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_acknowledgement_summary(source)
    _validate_request(source)
    _validate_review_area_inputs(source)


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


def _finding_codes(findings: list[dict[str, Any]]) -> list[str]:
    return [finding["code"] for finding in findings]


def _acknowledgement_item(source: dict[str, Any]) -> dict[str, Any]:
    acknowledgement = source["partial_target_acknowledgement_summary"]
    classification = acknowledgement["classification"]
    remaining_findings = acknowledgement["remaining_review_findings"]
    if classification == "partial_target_coverage_acknowledgement_blocked":
        state = "blocked_by_acknowledgement_review"
    elif remaining_findings:
        state = "needs_acknowledgement_review"
    elif classification == "partial_target_coverage_acknowledged_for_manual_review":
        state = "ready_for_manual_review"
    else:
        state = "needs_acknowledgement_review"
    return _review_item(
        area="acknowledged_parameter_scope",
        state=state,
        reason_codes=_finding_codes(remaining_findings),
        finding_count=len(remaining_findings),
    )


def _area_item(source: dict[str, Any], key: str, area: str, needs_state: str) -> dict[str, Any]:
    findings = source["review_area_inputs"][key]
    return _review_item(
        area=area,
        state=needs_state if findings else "ready_for_manual_review",
        reason_codes=_finding_codes(findings),
        finding_count=len(findings),
    )


def _review_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _acknowledgement_item(source),
        _area_item(
            source,
            "required_context_findings",
            "required_context",
            "blocked_by_required_context",
        ),
        _area_item(source, "workspace_findings", "workspace", "needs_workspace_review"),
        _area_item(source, "environment_findings", "environment", "needs_environment_review"),
    ]


def _overall_state(items: list[dict[str, Any]]) -> str:
    states = {item["state"] for item in items}
    if "blocked_by_acknowledgement_review" in states:
        return "blocked_by_acknowledgement_review"
    if "blocked_by_required_context" in states:
        return "blocked_by_required_context"
    needs_review = sorted(state for state in states if state != "ready_for_manual_review")
    if needs_review:
        return "manual_pre_run_review_needed"
    return "ready_for_operator_pre_run_decision"


def _recommended_action(overall_state: str) -> str:
    if overall_state == "ready_for_operator_pre_run_decision":
        return "present_operator_pre_run_decision"
    if overall_state == "blocked_by_acknowledgement_review":
        return "repair_or_reject_acknowledgement_before_manual_pre_run_review"
    if overall_state == "blocked_by_required_context":
        return "repair_required_context_before_manual_pre_run_review"
    return "review_flagged_context_areas_before_operator_pre_run_decision"


def _manual_review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for source_area, key in (
        ("required_context", "required_context_findings"),
        ("workspace", "workspace_findings"),
        ("environment", "environment_findings"),
    ):
        findings.extend(
            {
                "source_area": source_area,
                "code": finding["code"],
                "severity": finding["severity"],
                "basis": copy.deepcopy(finding["basis"]),
                "does_not_claim": finding["does_not_claim"],
            }
            for finding in source["review_area_inputs"][key]
        )
    return findings


def _acknowledged_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    acknowledgement = source["partial_target_acknowledgement_summary"]
    finding = acknowledgement["acknowledged_finding"]
    user_acknowledgement = acknowledgement["user_acknowledgement"]
    return [
        {
            "source_area": "scope_alignment",
            "code": finding["code"],
            "severity": finding["severity"],
            "basis": copy.deepcopy(finding["basis"]),
            "acknowledgement_id": user_acknowledgement["acknowledgement_id"],
            "acknowledged_by_role": user_acknowledgement["acknowledged_by_role"],
            "acknowledged_at": user_acknowledgement["acknowledged_at"],
            "does_not_claim": finding["does_not_claim"],
        }
    ]


def _remaining_acknowledgement_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_area": finding["source"],
            "code": finding["code"],
            "severity": finding["severity"],
            "basis": copy.deepcopy(finding["basis"]),
            "does_not_claim": finding["does_not_claim"],
        }
        for finding in source["partial_target_acknowledgement_summary"]["remaining_review_findings"]
    ]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "acknowledgement_consumed_as_review_fact",
            "severity": "info",
            "basis": "The gate treats partial target acknowledgement as a local manual review fact.",
            "does_not_claim": "scope_repair_or_parameter_invalidation",
        },
        {
            "code": "operator_decision_not_execution",
            "severity": "review",
            "basis": "Ready for operator pre-run decision is not run-start permission.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
        {
            "code": "no_fresh_observation_or_operation",
            "severity": "review",
            "basis": "The gate does not inspect storage, files, environments, runtimes, or hardware.",
            "does_not_claim": "fresh_readiness_or_integrity_check",
        },
    ]


def build_prepared_run_acknowledgement_aware_review_gate_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build an acknowledgement-aware manual pre-run review summary."""
    _validate_references(source)
    items = _review_items(source)
    overall_state = _overall_state(items)
    acknowledgement = source["partial_target_acknowledgement_summary"]
    return {
        "acknowledgement_aware_review_policy": copy.deepcopy(
            source["acknowledgement_aware_review_policy"]
        ),
        "review_request": copy.deepcopy(source["review_request"]),
        "gate_decision": {
            "overall_state": overall_state,
            "recommended_action": _recommended_action(overall_state),
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "compatibility_output": "not_produced",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
        },
        "prepared_run_context": copy.deepcopy(acknowledgement["prepared_run_context"]),
        "selected_parameter_state": copy.deepcopy(acknowledgement["selected_parameter_state"]),
        "review_items": items,
        "acknowledged_review_findings": _acknowledged_findings(source),
        "remaining_acknowledgement_findings": _remaining_acknowledgement_findings(source),
        "manual_review_findings": _manual_review_findings(source),
        "attention": _attention(),
    }
