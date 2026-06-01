"""Read-only view-state projection for prepared-run parameter approval."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "projection_authority": "explicit_prepared_run_approval_view_state",
    "source_summary_handling": "operator_pre_run_approval_summary",
    "projection_posture": "read_only_view_state",
    "canonical_parameter_context": "managed_parameter_state_snapshot",
    "compatibility_artifact_handling": "omitted_unless_explicit_debug_attachment",
    "available_actions": "labels_only",
    "gui_workflow": "not_defined",
    "action_execution": "not_performed",
    "automatic_run_start": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "compatibility_output": "not_produced",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "durable_storage": "not_performed",
    "environment_operation": "not_performed",
    "code_import_execution": "not_performed",
    "managed_runner": "not_defined",
    "shared_view_schema": "not_defined",
}

_SUPPORTED_APPROVAL_CLASSIFICATIONS = {
    "operator_pre_run_review_approved",
    "operator_pre_run_review_rejected",
    "operator_pre_run_review_deferred",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["view_state_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run approval view-state policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared-run approval view-state policy {key} must be {expected}")


def _validate_approval_summary(source: dict[str, Any]) -> None:
    summary = source["operator_approval_summary"]
    if summary["classification"] not in _SUPPORTED_APPROVAL_CLASSIFICATIONS:
        raise ValueError("operator approval classification is unsupported")
    effects = summary["decision_effects"]
    for key in (
        "automatic_run_start",
        "hardware_control",
        "parameter_write_back",
        "environment_operation",
        "code_import_execution",
        "durable_storage",
    ):
        if effects[key] != "not_performed":
            raise ValueError(f"operator approval effect {key} must be not_performed")
    if effects["run_start_claim"] != "not_claimed":
        raise ValueError("operator approval must not claim run start")
    if effects["compatibility_output"] != "not_produced":
        raise ValueError("operator approval must not produce compatibility output")
    review_decision = summary["review_gate_decision"]
    if review_decision["run_start_claim"] != "not_claimed":
        raise ValueError("review gate decision must not claim run start")
    if review_decision["hardware_control"] != "not_performed":
        raise ValueError("review gate decision must not control hardware")
    if review_decision["parameter_write_back"] != "not_performed":
        raise ValueError("review gate decision must not write parameters")
    if review_decision["compatibility_output"] != "not_produced":
        raise ValueError("review gate decision must not produce compatibility output")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["view_request"]
    approval = source["operator_approval_summary"]
    review_request = approval["review_request"]
    if request["approval_id"] != approval["operator_decision"]["approval_id"]:
        raise ValueError("view request approval_id must match operator approval")
    if request["review_gate_id"] != review_request["review_gate_id"]:
        raise ValueError("view request review_gate_id must match approval")
    if request["prepared_run_context_id"] != review_request["prepared_run_context_id"]:
        raise ValueError("view request prepared_run_context_id must match approval")
    if request["measurement_id"] != review_request["measurement_id"]:
        raise ValueError("view request measurement_id must match approval")
    if request["parameter_state_id"] != review_request["parameter_state_id"]:
        raise ValueError("view request parameter_state_id must match approval")


def _validate_debug_attachments(source: dict[str, Any]) -> None:
    attachments = source["debug_attachments"]
    if not isinstance(attachments, list):
        raise ValueError("debug_attachments must be a list")
    for attachment in attachments:
        if attachment["artifact_posture"] != "debug_attachment_reference":
            raise ValueError("debug attachment posture must remain debug attachment reference")
        if attachment["source_authority"] != "user_supplied":
            raise ValueError("debug attachment source authority must remain user supplied")
        if attachment["payload_import"] != "not_performed":
            raise ValueError("debug attachment payload import must not be performed")
        if attachment["relation_to_parameter_context"] != "derivative_debug_evidence":
            raise ValueError("debug attachment must remain derivative debug evidence")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_approval_summary(source)
    _validate_request(source)
    _validate_debug_attachments(source)
    if "compatibility_artifacts" in source:
        raise ValueError(
            "compatibility artifacts must use debug_attachments if explicitly supplied"
        )


def _classification(source: dict[str, Any]) -> str:
    summary = source["operator_approval_summary"]
    facts = summary["carried_review_facts"]
    if facts["remaining_acknowledgement_findings"] or facts["manual_review_findings"]:
        return "prepared_run_approval_view_needs_review"
    if summary["classification"] == "operator_pre_run_review_approved":
        return "prepared_run_approval_view_approved"
    if summary["classification"] == "operator_pre_run_review_rejected":
        return "prepared_run_approval_view_rejected"
    return "prepared_run_approval_view_deferred"


def _decision_label(classification: str) -> str:
    if classification == "operator_pre_run_review_approved":
        return "approved"
    if classification == "operator_pre_run_review_rejected":
        return "rejected"
    return "deferred"


def _available_actions(classification: str) -> list[str]:
    base = [
        "inspect_parameter_snapshot",
        "inspect_scope_acknowledgement",
        "inspect_operator_decision",
    ]
    if classification == "operator_pre_run_review_approved":
        return base + ["copy_parameter_state_id"]
    if classification == "operator_pre_run_review_rejected":
        return base + ["review_rejection_rationale"]
    return base + ["review_deferral_rationale"]


def _parameter_context_card(summary: dict[str, Any]) -> dict[str, Any]:
    state = summary["selected_parameter_state"]
    return {
        "card": "parameter_context",
        "context_role": "canonical_parameter_context",
        "state_id": state["state_id"],
        "source_kind": state["source_kind"],
        "trust_status": state["trust_status"],
        "trusted_entry_count": state["trusted_entry_count"],
        "does_not_claim": "compatibility_artifact_or_hardware_state",
    }


def _acknowledgement_card(summary: dict[str, Any]) -> dict[str, Any]:
    facts = summary["carried_review_facts"]
    return {
        "card": "scope_acknowledgement",
        "acknowledged_finding_codes": [
            finding["code"] for finding in facts["acknowledged_review_findings"]
        ],
        "remaining_acknowledgement_finding_count": len(facts["remaining_acknowledgement_findings"]),
        "manual_review_finding_count": len(facts["manual_review_findings"]),
        "does_not_claim": "scope_repair_or_parameter_invalidation",
    }


def _operator_decision_card(summary: dict[str, Any]) -> dict[str, Any]:
    decision = summary["operator_decision"]
    return {
        "card": "operator_decision",
        "decision": decision["decision"],
        "decision_label": _decision_label(summary["classification"]),
        "approval_state": decision["approval_state"],
        "operator_role": decision["operator_role"],
        "decided_at": decision["decided_at"],
        "rationale": decision["rationale"],
        "run_start_claim": "not_claimed",
    }


def _review_cards(source: dict[str, Any]) -> list[dict[str, Any]]:
    summary = source["operator_approval_summary"]
    return [
        _parameter_context_card(summary),
        _acknowledgement_card(summary),
        _operator_decision_card(summary),
    ]


def _debug_attachment_summary(source: dict[str, Any]) -> dict[str, Any]:
    attachments = source["debug_attachments"]
    return {
        "state": "omitted" if not attachments else "debug_attachments_present",
        "count": len(attachments),
        "attachment_refs": [
            {
                "attachment_id": attachment["attachment_id"],
                "artifact_posture": attachment["artifact_posture"],
                "payload_import": attachment["payload_import"],
            }
            for attachment in attachments
        ],
        "does_not_claim": "compatibility_artifacts_as_parameter_context",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "parameter_state_is_canonical_context",
            "severity": "info",
            "basis": "The selected managed parameter-state snapshot is the parameter context shown by the view.",
            "does_not_claim": "compatibility_output_as_context",
        },
        {
            "code": "view_state_is_read_only",
            "severity": "review",
            "basis": "The projection exposes review state and action labels only.",
            "does_not_claim": "action_execution_or_gui_contract",
        },
        {
            "code": "execution_not_granted",
            "severity": "review",
            "basis": "The view does not start runs, control hardware, write parameters, or execute code.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
    ]


def build_prepared_run_approval_view_state_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only prepared-run approval view-state summary."""
    _validate_references(source)
    approval = source["operator_approval_summary"]
    return {
        "view_state_policy": copy.deepcopy(source["view_state_policy"]),
        "classification": _classification(source),
        "view_request": copy.deepcopy(source["view_request"]),
        "prepared_run_context": copy.deepcopy(approval["prepared_run_context"]),
        "selected_parameter_state": copy.deepcopy(approval["selected_parameter_state"]),
        "review_gate_decision": copy.deepcopy(approval["review_gate_decision"]),
        "operator_decision": copy.deepcopy(approval["operator_decision"]),
        "review_cards": _review_cards(source),
        "remaining_findings": copy.deepcopy(approval["carried_review_facts"]),
        "debug_attachments": _debug_attachment_summary(source),
        "available_review_actions": _available_actions(approval["classification"]),
        "action_posture": "labels_only_not_executed",
        "view_effects": {
            "gui_workflow": "not_defined",
            "action_execution": "not_performed",
            "automatic_run_start": "not_performed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "compatibility_output": "not_produced",
            "durable_storage": "not_performed",
        },
        "attention": _attention(),
    }
