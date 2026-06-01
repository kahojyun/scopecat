"""Review findings for degraded calibration-to-measurement backbone context."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "finding_authority": "declared_calibration_backbone_context_findings",
    "source_backbone": "calibration_derived_parameter_state_measurement_context",
    "finding_posture": "review_only",
    "payload_handling": "reference_and_summary_facts_only",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "fresh_storage_read": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "compatibility_output": "not_produced",
    "recursive_traversal": "not_performed",
    "measurement_validity_decision": "not_performed",
    "shared_route_schema": "not_defined",
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
    policy = source["backbone_findings_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("calibration backbone context findings policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"calibration backbone context findings policy {key} must be {expected}"
            )


def _validate_case_boundary(case: dict[str, Any]) -> None:
    handoff = case.get("accepted_write_handoff")
    if handoff is not None and handoff["apply_state"] != "not_applied":
        raise ValueError("accepted write handoff must not imply hardware apply")
    link = case.get("measurement_context_link")
    if link is not None and link["required_for_record_validity"]:
        raise ValueError("measurement context link must remain optional for record validity")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _records_by_key(source["backbone_cases"], "case_id")
    for case in source["backbone_cases"]:
        _validate_case_boundary(case)


def _finding(
    code: str,
    severity: str,
    basis: str,
    does_not_claim: str,
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _case_findings(case: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    expected_state_id = case["expected_parameter_state_id"]
    observation = case.get("calibration_observation")
    handoff = case.get("accepted_write_handoff")
    intake = case.get("parameter_state_intake")
    stored_state = case.get("stored_parameter_state")
    prepared_run = case.get("prepared_run_selection")
    measurement_link = case.get("measurement_context_link")

    if observation is None:
        findings.append(
            _finding(
                "calibration_observation_missing",
                "blocked",
                "No calibration observation summary is available for the accepted-write chain.",
                "remeasurement_or_fit_decision",
            )
        )

    if handoff is None:
        findings.append(
            _finding(
                "accepted_write_handoff_missing",
                "blocked",
                "No accepted calibration write handoff is available for parameter-state intake.",
                "parameter_state_intake_creation",
            )
        )
    elif handoff["handoff_state"] != "ready_for_parameter_state_review":
        findings.append(
            _finding(
                "accepted_write_handoff_not_ready",
                "blocked",
                f"Accepted write handoff state is {handoff['handoff_state']}.",
                "automatic_handoff_repair",
            )
        )
    elif observation is not None and (
        handoff["step_record_id"] != observation["step_record_id"]
        or handoff["observation_measurement_record_id"] != observation["measurement_record_id"]
    ):
        findings.append(
            _finding(
                "calibration_handoff_observation_mismatch",
                "blocked",
                "Accepted write handoff does not match the calibration observation identity.",
                "relation_graph_repair",
            )
        )

    if intake is None:
        findings.append(
            _finding(
                "parameter_state_intake_unavailable",
                "blocked",
                "No parameter-state intake summary is available for the accepted handoff.",
                "parameter_state_commit_or_storage",
            )
        )
    elif handoff is not None and intake["source_handoff_id"] != handoff["handoff_id"]:
        findings.append(
            _finding(
                "parameter_state_intake_handoff_mismatch",
                "blocked",
                "Parameter-state intake does not cite the accepted handoff.",
                "automatic_provenance_repair",
            )
        )
    elif intake["state_id"] != expected_state_id:
        findings.append(
            _finding(
                "parameter_state_intake_snapshot_mismatch",
                "blocked",
                "Parameter-state intake produced a different managed snapshot than expected.",
                "snapshot_equivalence",
            )
        )

    if stored_state is None:
        findings.append(
            _finding(
                "stored_parameter_state_unavailable",
                "blocked",
                "No stored parameter-state summary is available for prepared-run selection.",
                "fresh_storage_read_or_catalog_discovery",
            )
        )
    elif stored_state["state_id"] != expected_state_id:
        findings.append(
            _finding(
                "stored_parameter_state_snapshot_mismatch",
                "blocked",
                "Stored parameter-state summary does not match the expected managed snapshot.",
                "storage_repair",
            )
        )
    elif stored_state["source_kind"] != "calibration_handoff":
        findings.append(
            _finding(
                "stored_parameter_state_source_kind_mismatch",
                "review",
                "Stored parameter-state summary is not marked calibration-derived.",
                "universal_provenance_schema",
            )
        )

    if prepared_run is None:
        findings.append(
            _finding(
                "prepared_run_selection_missing",
                "blocked",
                "No prepared-run parameter-context selection is available.",
                "automatic_run_start",
            )
        )
    elif prepared_run["selected_parameter_state_id"] != expected_state_id:
        findings.append(
            _finding(
                "prepared_run_selected_snapshot_mismatch",
                "blocked",
                "Prepared run selected a different parameter-state snapshot.",
                "automatic_selection_repair",
            )
        )

    if measurement_link is None:
        findings.append(
            _finding(
                "measurement_context_link_missing",
                "review",
                "Later measurement record has no parameter-state run-start context link.",
                "measurement_record_invalid",
            )
        )
    elif measurement_link["context_id"] != expected_state_id:
        findings.append(
            _finding(
                "measurement_context_link_snapshot_mismatch",
                "review",
                "Later measurement record links a different parameter-state snapshot.",
                "measurement_record_invalid_or_context_repair",
            )
        )
    elif measurement_link["include_state"] != "linked":
        findings.append(
            _finding(
                "measurement_context_link_not_linked",
                "review",
                "Later measurement record parameter context is not linked.",
                "measurement_record_invalid",
            )
        )

    return findings


def _classification(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "calibration_backbone_context_ready"
    if any(finding["severity"] == "blocked" for finding in findings):
        return "calibration_backbone_context_blocked"
    return "calibration_backbone_context_needs_review"


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    findings = _case_findings(case)
    return {
        "case_id": case["case_id"],
        "label": case["label"],
        "expected_parameter_state_id": case["expected_parameter_state_id"],
        "classification": _classification(findings),
        "finding_count": len(findings),
        "findings": findings,
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "degraded_backbone_facts_are_findings",
            "severity": "info",
            "basis": "Missing or mismatched route facts become review findings instead of schema expansion.",
            "does_not_claim": "shared_route_schema",
        },
        {
            "code": "measurement_context_remains_optional",
            "severity": "info",
            "basis": "Missing or mismatched measurement context links do not invalidate primary measurement data.",
            "does_not_claim": "measurement_record_invalid",
        },
        {
            "code": "execution_not_performed",
            "severity": "review",
            "basis": "The slice does not fit, rerun, write parameters, apply hardware, or start runs.",
            "does_not_claim": "runner_or_hardware_safety",
        },
    ]


def build_calibration_backbone_context_findings_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build review-only findings for missing or partial backbone context."""
    _validate_references(source)
    case_summaries = [_case_summary(case) for case in source["backbone_cases"]]
    all_findings = [
        {"case_id": case["case_id"], **finding}
        for case in case_summaries
        for finding in case["findings"]
    ]
    return {
        "backbone_findings_policy": copy.deepcopy(source["backbone_findings_policy"]),
        "classification": _classification(all_findings),
        "case_count": len(case_summaries),
        "blocked_case_count": sum(
            1
            for case in case_summaries
            if case["classification"] == "calibration_backbone_context_blocked"
        ),
        "review_case_count": sum(
            1
            for case in case_summaries
            if case["classification"] == "calibration_backbone_context_needs_review"
        ),
        "ready_case_count": sum(
            1
            for case in case_summaries
            if case["classification"] == "calibration_backbone_context_ready"
        ),
        "case_summaries": case_summaries,
        "review_findings": all_findings,
        "attention": _attention(),
    }
