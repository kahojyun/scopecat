"""Bridge legacy sidecar adoption to calibration-derived parameter state.

This module validates an explicit review bridge from a post-run legacy sidecar
adoption summary to a calibration accepted-write handoff and parameter-state
intake summary. It does not execute legacy code, parse payloads, inspect
artifacts, write parameter-state storage, write legacy parameter files, apply
hardware changes, repair references, or define GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "bridge_authority": "explicit_legacy_calibration_handoff_parameter_state_bridge",
    "legacy_adoption_input": "legacy_brownfield_adoption_backbone_summary",
    "calibration_input": "validated_calibration_accepted_write_handoff",
    "parameter_state_input": "calibration_parameter_state_intake_summary",
    "adoption_mode": "post_run_first",
    "handoff_posture": "review_debug_evidence_to_parameter_state_intake",
    "fresh_observation": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "parameter_state_storage_mutation": "not_performed",
    "legacy_parameter_write_back": "not_performed",
    "hardware_write_back": "not_performed",
    "reference_repair": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_workflow_schema": "not_defined",
}

_LEGACY_POLICY_EXPECTATIONS = {
    "adoption_authority": "explicit_legacy_brownfield_adoption_backbone",
    "adoption_mode": "post_run_first",
    "during_run_compatibility": "declared_lifecycle_events_only",
    "execution_owner": "external_legacy_system",
    "fresh_observation": "not_performed",
    "new_storage_mutation": "not_performed",
    "primary_data_import": "not_performed",
    "legacy_payload_import": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
}

_HANDOFF_POLICY_EXPECTATIONS = {
    "handoff_authority": "explicit_accepted_calibration_write_handoff",
    "source_write_review": "accepted_for_parameter_state_handoff_only",
    "parameter_state_authority": "parameter_state_management_route",
    "handoff_payload": "summary_only",
    "parameter_state_draft_write": "not_performed",
    "parameter_state_commit": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "rollback": "not_defined",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
}

_INTAKE_POLICY_EXPECTATIONS = {
    "input_authority": "validated_calibration_accepted_write_handoff",
    "intake_authority": "parameter_state_management_route",
    "review_required": "explicit_parameter_state_review_acceptance",
    "managed_parameter_state_creation": "summary_only_not_written",
    "durable_history": "summary_only_not_written",
    "calibration_payload_handling": "summary_only",
    "storage_mutation": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_write_back": "not_performed",
    "rollback": "not_defined",
    "calibration_execution": "not_performed",
}

_BRIDGE_FIELDS = {
    "bridge_id",
    "measurement_id",
    "legacy_adoption_measurement_id",
    "calibration_handoff_id",
    "parameter_state_intake_review_id",
    "link_authority",
    "link_posture",
    "operator_approval",
}

_APPROVAL_FIELDS = {"approval_state", "operator_role", "approved_at", "rationale"}


def _validate_expected_values(
    policy: dict[str, Any], expectations: dict[str, str], owner: str
) -> None:
    for key, expected in expectations.items():
        if policy.get(key) != expected:
            raise ValueError(f"{owner} policy {key} must be {expected}")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["bridge_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy calibration handoff bridge policy must match expected shape")
    _validate_expected_values(policy, _EXPECTED_POLICY, "legacy calibration handoff bridge")


def _validate_approval(approval: dict[str, Any]) -> None:
    if set(approval) != _APPROVAL_FIELDS:
        raise ValueError("bridge operator approval must match expected shape")
    if approval["approval_state"] != "approved":
        raise ValueError("bridge operator approval must be approved")
    if approval["operator_role"] != "local_reviewer":
        raise ValueError("bridge operator role must be local_reviewer")
    if not approval["approved_at"]:
        raise ValueError("bridge operator approved_at is required")
    if not approval["rationale"]:
        raise ValueError("bridge operator rationale is required")


def _validate_bridge(source: dict[str, Any]) -> None:
    bridge = source["bridge"]
    if set(bridge) != _BRIDGE_FIELDS:
        raise ValueError("legacy calibration handoff bridge must match expected shape")
    if bridge["link_authority"] != "operator_declared":
        raise ValueError("bridge link_authority must be operator_declared")
    if bridge["link_posture"] != "review_debug_evidence_to_parameter_state_intake":
        raise ValueError("bridge link_posture is unsupported")
    _validate_approval(bridge["operator_approval"])


def _handoff_by_id(summary: dict[str, Any], handoff_id: str) -> dict[str, Any]:
    matches = [
        request for request in summary["handoff_requests"] if request["handoff_id"] == handoff_id
    ]
    if len(matches) != 1:
        raise ValueError("bridge calibration_handoff_id must match exactly one handoff request")
    return matches[0]


def _validate_source(source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _validate_policy(source)
    _validate_bridge(source)
    legacy = source["legacy_brownfield_adoption_summary"]
    handoff = source["calibration_accepted_write_handoff_summary"]
    intake = source["calibration_parameter_state_intake_summary"]
    bridge = source["bridge"]

    _validate_expected_values(
        legacy["adoption_backbone_policy"], _LEGACY_POLICY_EXPECTATIONS, "legacy adoption"
    )
    _validate_expected_values(handoff["handoff_policy"], _HANDOFF_POLICY_EXPECTATIONS, "handoff")
    _validate_expected_values(intake["policy"], _INTAKE_POLICY_EXPECTATIONS, "intake")

    measurement_id = legacy["measurement_id"]
    if bridge["measurement_id"] != measurement_id:
        raise ValueError("bridge measurement_id must match legacy adoption measurement")
    if bridge["legacy_adoption_measurement_id"] != measurement_id:
        raise ValueError("bridge legacy_adoption_measurement_id must match legacy adoption")

    handoff_request = _handoff_by_id(handoff, bridge["calibration_handoff_id"])
    if intake["source_handoff"]["handoff_id"] != handoff_request["handoff_id"]:
        raise ValueError("intake source handoff must match bridge handoff")
    if bridge["parameter_state_intake_review_id"] != intake["intake_review"]["review_id"]:
        raise ValueError("bridge intake review id must match parameter-state intake")
    if intake["source_handoff"]["apply_state"] != "not_applied":
        raise ValueError("bridge requires not_applied calibration handoff")

    handoff_measurements = {
        link["measurement_record_id"]
        for step in handoff["calibration_step_records"]
        for link in step["observation_link_refs"]
    }
    intake_measurements = set(intake["provenance"]["measurement_record_refs"])
    if measurement_id not in handoff_measurements:
        raise ValueError("legacy adoption measurement must be referenced by calibration handoff")
    if measurement_id not in intake_measurements:
        raise ValueError("legacy adoption measurement must be referenced by parameter-state intake")
    return measurement_id, handoff_request


def _classification(legacy: dict[str, Any], intake: dict[str, Any]) -> str:
    if legacy["classification"] != "legacy_brownfield_adoption_ready_for_review_evidence_readback":
        return "legacy_calibration_handoff_bridge_needs_legacy_review"
    if intake["review_findings"]:
        return "legacy_calibration_handoff_bridge_needs_parameter_state_review"
    return "legacy_calibration_handoff_bridge_ready"


def _bridge_summary(source: dict[str, Any], handoff_request: dict[str, Any]) -> dict[str, Any]:
    bridge = source["bridge"]
    intake = source["calibration_parameter_state_intake_summary"]
    return {
        "bridge_id": bridge["bridge_id"],
        "measurement_id": bridge["measurement_id"],
        "legacy_adoption_measurement_id": bridge["legacy_adoption_measurement_id"],
        "calibration_handoff_id": bridge["calibration_handoff_id"],
        "parameter_state_intake_review_id": bridge["parameter_state_intake_review_id"],
        "operator_approval": copy.deepcopy(bridge["operator_approval"]),
        "handoff_request_state": handoff_request["request_state"],
        "handoff_apply_state": intake["source_handoff"]["apply_state"],
        "link_posture": bridge["link_posture"],
    }


def _parameter_state_summary(intake: dict[str, Any]) -> dict[str, Any]:
    state = intake["managed_parameter_state"]
    return {
        "state_id": state["state_id"],
        "state_kind": state["state_kind"],
        "source_handoff_id": state["source_handoff_id"],
        "base_state_id": state["base_state_id"],
        "created_by_review_id": state["created_by_review_id"],
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "changed_entry_paths": [entry["path"] for entry in intake["changed_entries"]],
    }


def _evidence_posture() -> dict[str, str]:
    return {
        "legacy_sidecar_role": "review_debug_evidence",
        "calibration_handoff_role": "parameter_state_intake_source",
        "managed_parameter_state_role": "canonical_parameter_context_after_intake",
        "legacy_snapshots_or_debug_artifacts": "supporting_evidence_not_canonical_context",
    }


def _effects() -> dict[str, str]:
    return {
        "fresh_observation": "not_performed",
        "primary_data_import": "not_performed",
        "legacy_payload_import": "not_performed",
        "legacy_source_parsing": "not_performed_by_scopecat",
        "parameter_state_storage_mutation": "not_performed",
        "legacy_parameter_write_back": "not_performed",
        "hardware_write_back": "not_performed",
        "reference_repair": "not_performed",
        "measurement_validity": "not_claimed",
        "gui_workflow": "not_defined",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "legacy_sidecar_can_reference_calibration_handoff",
            "severity": "info",
            "basis": "The bridge links reviewed legacy sidecar evidence to a validated calibration accepted-write handoff.",
            "does_not_claim": "legacy_payload_inference",
        },
        {
            "code": "parameter_state_intake_remains_authoritative",
            "severity": "info",
            "basis": "The managed parameter-state summary comes from parameter-state intake, not sidecar evidence.",
            "does_not_claim": "sidecar_owned_parameter_state",
        },
        {
            "code": "legacy_write_back_not_performed",
            "severity": "review",
            "basis": "The bridge does not write accepted calibration values back to legacy parameter files.",
            "does_not_claim": "legacy_parameter_file_updated",
        },
        {
            "code": "hardware_write_back_not_performed",
            "severity": "review",
            "basis": "Parameter-state intake does not apply values to instruments.",
            "does_not_claim": "instrument_command_or_current_hardware_state",
        },
    ]


def build_legacy_calibration_handoff_parameter_state_bridge_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a review bridge from legacy sidecar adoption to parameter-state intake."""
    measurement_id, handoff_request = _validate_source(source)
    legacy = source["legacy_brownfield_adoption_summary"]
    intake = source["calibration_parameter_state_intake_summary"]
    return {
        "bridge_policy": copy.deepcopy(source["bridge_policy"]),
        "classification": _classification(legacy, intake),
        "measurement_id": measurement_id,
        "bridge": _bridge_summary(source, handoff_request),
        "legacy_adoption": {
            "classification": legacy["classification"],
            "adoption_mode": copy.deepcopy(legacy["adoption_mode"]),
            "receipt_observed_count": legacy["receipt_readback"]["observed_receipt_count"],
        },
        "parameter_state": _parameter_state_summary(intake),
        "evidence_posture": _evidence_posture(),
        "review_finding_count": len(intake["review_findings"]),
        "review_findings": copy.deepcopy(intake["review_findings"]),
        "effects": _effects(),
        "attention": _attention(),
    }
