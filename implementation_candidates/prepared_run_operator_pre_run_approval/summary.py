"""Operator pre-run approval recording over an acknowledged review summary."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "approval_authority": "explicit_operator_pre_run_decision",
    "review_source": "prepared_run_acknowledgement_aware_review_gate_summary",
    "decision_scope": "operator_pre_run_decision_record_only",
    "automatic_run_start": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "compatibility_output": "not_produced",
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
    "durable_storage": "not_performed",
    "gui_workflow": "not_defined",
    "managed_runner": "not_defined",
    "shared_approval_schema": "not_defined",
}

_APPROVE = "approve_pre_run_review"
_REJECT = "reject_pre_run_review"
_DEFER = "defer_pre_run_review"
_SUPPORTED_DECISIONS = {_APPROVE, _REJECT, _DEFER}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["operator_approval_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("operator pre-run approval policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"operator pre-run approval policy {key} must be {expected}")


def _validate_review_summary(source: dict[str, Any]) -> None:
    summary = source["acknowledgement_aware_review_summary"]
    policy = summary["acknowledgement_aware_review_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "dependency_resolution",
        "dependency_sync",
        "package_install",
        "runtime_probe",
        "fresh_storage_read",
        "catalog_discovery",
        "setup_mutation",
        "workspace_mutation",
        "environment_operation",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"review summary policy {key} must be not_performed")
    if policy["compatibility_output"] != "not_produced":
        raise ValueError("review summary policy compatibility_output must be not_produced")
    if policy["gui_workflow"] != "not_defined":
        raise ValueError("review summary must not define GUI workflow")
    if policy["managed_runner"] != "not_defined":
        raise ValueError("review summary must not define managed runner")
    decision = summary["gate_decision"]
    for key in (
        "run_start_claim",
        "hardware_control",
        "parameter_write_back",
        "environment_operation",
        "code_import_execution",
    ):
        expected = "not_claimed" if key == "run_start_claim" else "not_performed"
        if decision[key] != expected:
            raise ValueError(f"review summary gate decision {key} must be {expected}")
    if decision["compatibility_output"] != "not_produced":
        raise ValueError("review summary gate decision compatibility_output must be not_produced")


def _validate_operator_decision(source: dict[str, Any]) -> None:
    decision = source["operator_decision"]
    review = source["acknowledgement_aware_review_summary"]
    review_request = review["review_request"]
    if decision["decision"] not in _SUPPORTED_DECISIONS:
        raise ValueError("operator pre-run decision is unsupported")
    if decision["review_gate_id"] != review_request["review_gate_id"]:
        raise ValueError("operator decision review_gate_id must match review summary")
    if decision["prepared_run_context_id"] != review_request["prepared_run_context_id"]:
        raise ValueError("operator decision prepared_run_context_id must match review summary")
    if decision["measurement_id"] != review_request["measurement_id"]:
        raise ValueError("operator decision measurement_id must match review summary")
    if decision["parameter_state_id"] != review_request["parameter_state_id"]:
        raise ValueError("operator decision parameter_state_id must match review summary")
    if not decision["operator_role"]:
        raise ValueError("operator decision requires operator_role")
    if not decision["decided_at"]:
        raise ValueError("operator decision requires decided_at")
    if not decision["rationale"]:
        raise ValueError("operator decision requires rationale")
    if (
        decision["decision"] == _APPROVE
        and review["gate_decision"]["overall_state"] != "ready_for_operator_pre_run_decision"
    ):
        raise ValueError("operator approval requires ready_for_operator_pre_run_decision")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_review_summary(source)
    _validate_operator_decision(source)


def _classification(source: dict[str, Any]) -> str:
    decision = source["operator_decision"]["decision"]
    if decision == _APPROVE:
        return "operator_pre_run_review_approved"
    if decision == _REJECT:
        return "operator_pre_run_review_rejected"
    return "operator_pre_run_review_deferred"


def _approval_state(decision: str) -> str:
    if decision == _APPROVE:
        return "operator_approved_review_recorded"
    if decision == _REJECT:
        return "operator_rejected_review_recorded"
    return "operator_deferred_review_recorded"


def _attention(decision: str) -> list[dict[str, str]]:
    if decision == _APPROVE:
        first = {
            "code": "operator_approval_recorded",
            "severity": "info",
            "basis": "The operator approved the reviewed pre-run context for downstream manual handling.",
            "does_not_claim": "automatic_run_start",
        }
    elif decision == _REJECT:
        first = {
            "code": "operator_rejection_recorded",
            "severity": "review",
            "basis": "The operator rejected the reviewed pre-run context and preserved rationale.",
            "does_not_claim": "context_mutation_or_repair",
        }
    else:
        first = {
            "code": "operator_deferral_recorded",
            "severity": "review",
            "basis": "The operator deferred the reviewed pre-run context and preserved rationale.",
            "does_not_claim": "context_mutation_or_repair",
        }
    return [
        first,
        {
            "code": "approval_record_only",
            "severity": "review",
            "basis": "This summary records an operator decision and performs no execution or storage action.",
            "does_not_claim": "run_started_or_persisted",
        },
        {
            "code": "hardware_and_write_back_not_performed",
            "severity": "review",
            "basis": "The decision record does not control hardware, write parameters, or emit compatibility output.",
            "does_not_claim": "hardware_safe_or_parameters_applied",
        },
    ]


def build_prepared_run_operator_pre_run_approval_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build an operator pre-run decision record from a review summary."""
    _validate_references(source)
    review = source["acknowledgement_aware_review_summary"]
    decision = source["operator_decision"]
    return {
        "operator_approval_policy": copy.deepcopy(source["operator_approval_policy"]),
        "classification": _classification(source),
        "review_request": copy.deepcopy(review["review_request"]),
        "prepared_run_context": copy.deepcopy(review["prepared_run_context"]),
        "selected_parameter_state": copy.deepcopy(review["selected_parameter_state"]),
        "review_gate_decision": copy.deepcopy(review["gate_decision"]),
        "operator_decision": {
            "approval_id": decision["approval_id"],
            "decision": decision["decision"],
            "approval_state": _approval_state(decision["decision"]),
            "operator_role": decision["operator_role"],
            "decided_at": decision["decided_at"],
            "rationale": decision["rationale"],
        },
        "decision_effects": {
            "automatic_run_start": "not_performed",
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "compatibility_output": "not_produced",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
            "durable_storage": "not_performed",
        },
        "carried_review_facts": {
            "acknowledged_review_findings": copy.deepcopy(review["acknowledged_review_findings"]),
            "remaining_acknowledgement_findings": copy.deepcopy(
                review["remaining_acknowledgement_findings"]
            ),
            "manual_review_findings": copy.deepcopy(review["manual_review_findings"]),
        },
        "attention": _attention(decision["decision"]),
    }
