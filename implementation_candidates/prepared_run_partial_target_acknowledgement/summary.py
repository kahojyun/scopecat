"""User acknowledgement for prepared-run partial target coverage findings."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "acknowledgement_authority": "explicit_user_review_decision",
    "review_chain_source": "prepared_run_source_agnostic_parameter_state_review_chain_summary",
    "acknowledgement_scope": "partial_target_coverage_findings_only",
    "finding_resolution": "local_review_acknowledgement_only",
    "parameter_invalidation": "not_performed",
    "parameter_write_back": "not_performed",
    "compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "scope_repair": "not_performed",
    "setup_mutation": "not_performed",
    "catalog_discovery": "not_performed",
    "fresh_storage_read": "not_performed",
    "gui_workflow": "not_defined",
    "shared_acknowledgement_schema": "not_defined",
}

_ACKNOWLEDGEABLE_FINDING = "parameter_lineage_partial_target_coverage"


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["acknowledgement_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run partial-target acknowledgement policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"partial-target acknowledgement policy {key} must be {expected}")


def _validate_review_chain(source: dict[str, Any]) -> None:
    chain = source["review_chain_summary"]
    policy = chain["review_chain_policy"]
    for key in (
        "fresh_storage_read",
        "catalog_discovery",
        "storage_mutation",
        "parameter_write_back",
        "hardware_control",
        "automatic_run_start",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"review chain policy {key} must be not_performed")
    if policy["compatibility_output"] != "not_produced":
        raise ValueError("review chain policy compatibility_output must be not_produced")
    if chain["selected_parameter_state"]["source_kind"] != "calibration_handoff":
        raise ValueError("first partial-target acknowledgement fixture expects calibration_handoff")


def _partial_target_findings(chain: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding
        for finding in chain["review_findings"]
        if finding["source"] == "scope_alignment" and finding["code"] == _ACKNOWLEDGEABLE_FINDING
    ]


def _find_acknowledged_finding(
    chain: dict[str, Any],
    acknowledgement: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        finding
        for finding in _partial_target_findings(chain)
        if finding["source"] == acknowledgement["finding_source"]
        and finding["code"] == acknowledgement["finding_code"]
        and finding["basis"] == acknowledgement["finding_basis"]
    ]
    if len(matches) != 1:
        raise ValueError("acknowledgement must match exactly one partial target finding")
    return matches[0]


def _validate_acknowledgement(source: dict[str, Any]) -> None:
    acknowledgement = source["user_acknowledgement"]
    chain = source["review_chain_summary"]
    if acknowledgement["decision"] != "acknowledged_for_manual_review":
        raise ValueError("partial target acknowledgement decision is unsupported")
    if acknowledgement["finding_code"] != _ACKNOWLEDGEABLE_FINDING:
        raise ValueError("partial target acknowledgement can only acknowledge partial coverage")
    if (
        acknowledgement["prepared_run_context_id"]
        != chain["prepared_run_context"]["prepared_run_context_id"]
    ):
        raise ValueError("partial target acknowledgement prepared run context must match")
    if acknowledgement["parameter_state_id"] != chain["selected_parameter_state"]["state_id"]:
        raise ValueError("partial target acknowledgement parameter state must match")
    if not acknowledgement["acknowledged_by_role"]:
        raise ValueError("partial target acknowledgement requires acknowledged_by_role")
    if not acknowledgement["acknowledged_at"]:
        raise ValueError("partial target acknowledgement requires acknowledged_at")
    if not acknowledgement["review_note"]:
        raise ValueError("partial target acknowledgement requires review_note")
    _find_acknowledged_finding(source["review_chain_summary"], acknowledgement)


def _validate_side_effects(source: dict[str, Any]) -> None:
    side_effects = source["side_effect_claims"]
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
            raise ValueError(f"side effect claim {key} must be not_performed")
    if side_effects["compatibility_output"] != "not_produced":
        raise ValueError("side effect claim compatibility_output must be not_produced")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_review_chain(source)
    _validate_acknowledgement(source)
    _validate_side_effects(source)


def _remaining_findings(
    chain: dict[str, Any],
    acknowledged: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(finding)
        for finding in chain["review_findings"]
        if not (
            finding["source"] == acknowledged["source"]
            and finding["code"] == acknowledged["code"]
            and finding["basis"] == acknowledged["basis"]
        )
    ]


def _classification(chain: dict[str, Any], remaining_findings: list[dict[str, Any]]) -> str:
    if chain["classification"] == "parameter_review_chain_blocked":
        return "partial_target_coverage_acknowledgement_blocked"
    if remaining_findings:
        return "manual_pre_run_review_still_needs_review"
    return "partial_target_coverage_acknowledged_for_manual_review"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "partial_target_coverage_acknowledged",
            "severity": "info",
            "basis": "The user explicitly acknowledged known partial parameter lineage coverage for manual review.",
            "does_not_claim": "parameter_scope_repair_or_invalidation",
        },
        {
            "code": "run_start_not_granted",
            "severity": "review",
            "basis": "Acknowledgement is a local review decision and does not grant execution permission.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
        {
            "code": "hardware_and_write_back_not_performed",
            "severity": "review",
            "basis": "Acknowledgement does not apply parameters, write compatibility output, or control instruments.",
            "does_not_claim": "parameter_application_or_external_output",
        },
    ]


def build_prepared_run_partial_target_acknowledgement_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a local acknowledgement summary for partial target coverage."""
    _validate_references(source)
    chain = source["review_chain_summary"]
    acknowledgement = source["user_acknowledgement"]
    acknowledged = _find_acknowledged_finding(chain, acknowledgement)
    remaining_findings = _remaining_findings(chain, acknowledged)
    return {
        "acknowledgement_policy": copy.deepcopy(source["acknowledgement_policy"]),
        "classification": _classification(chain, remaining_findings),
        "prepared_run_context": copy.deepcopy(chain["prepared_run_context"]),
        "selected_parameter_state": copy.deepcopy(chain["selected_parameter_state"]),
        "acknowledged_finding": copy.deepcopy(acknowledged),
        "user_acknowledgement": {
            "acknowledgement_id": acknowledgement["acknowledgement_id"],
            "prepared_run_context_id": acknowledgement["prepared_run_context_id"],
            "parameter_state_id": acknowledgement["parameter_state_id"],
            "decision": acknowledgement["decision"],
            "acknowledged_by_role": acknowledgement["acknowledged_by_role"],
            "acknowledged_at": acknowledgement["acknowledged_at"],
            "review_note": acknowledgement["review_note"],
        },
        "remaining_review_findings": remaining_findings,
        "downstream_review_state": {
            "gate_state": chain["gate_summary"]["gate_decision"]["gate_state"],
            "scope_alignment_classification": chain["scope_alignment_summary"]["classification"],
            "chain_classification_before_acknowledgement": chain["classification"],
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
        },
        "side_effects": copy.deepcopy(source["side_effect_claims"]),
        "attention": _attention(),
    }
