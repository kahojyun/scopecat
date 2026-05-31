"""Intent to append reviewed legacy sidecar facts later.

This module validates an explicit operator-approved intent to append reviewed
legacy sidecar and locator-observation facts as review/debug evidence. It does
not write storage, import primary data, parse legacy payloads, repair
references, write parameters, decide measurement validity, or define GUI
behavior.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.contract_primitives import validate_public_identifier

_EXPECTED_POLICY = {
    "intent_authority": "explicit_reviewed_legacy_sidecar_append_intent",
    "source_review_handling": "legacy_locator_observation_review_bundle_summary",
    "approval_required": "explicit_operator_approval",
    "append_target": "existing_measurement_record_review_evidence",
    "fact_posture": "review_debug_evidence",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_import": "not_performed",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_append_schema": "not_defined",
}

_SOURCE_POLICY_EXPECTATIONS = {
    "review_authority": "explicit_legacy_locator_observation_review_bundle",
    "review_posture": "local_review_summary",
    "locator_observation_handling": "prior_summary_only",
    "fresh_file_observation": "not_performed",
    "backend_lookup": "not_performed",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
}

_REQUEST_FIELDS = {
    "request_id",
    "measurement_id",
    "operator_approval",
    "append_destination",
    "selected_fact_sets",
    "include_primary_data",
    "include_legacy_payloads",
    "include_reference_repair",
    "include_measurement_validity",
}

_APPROVAL_FIELDS = {
    "approval_state",
    "operator_role",
    "approved_at",
    "rationale",
}

_DESTINATION_FIELDS = {
    "destination_kind",
    "append_posture",
    "record_write",
}

_SELECTED_FACT_SETS = {
    "sidecar_post_run_review",
    "legacy_locator_observation_review",
}

_READY_SOURCE_CLASSIFICATIONS = {
    "legacy_locator_observation_review_ready",
    "legacy_locator_observation_review_ready_without_observation",
    "legacy_locator_observation_review_no_file_backed_locators",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["append_intent_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("reviewed legacy sidecar append intent policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"reviewed legacy sidecar append intent policy {key} must be {expected}"
            )


def _validate_source_review(summary: dict[str, Any]) -> None:
    policy = summary["locator_observation_review_policy"]
    for key, expected in _SOURCE_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"source locator observation review policy {key} must be {expected}")
    if summary["review_finding_count"] != len(summary["review_findings"]):
        raise ValueError("source review_finding_count must match review_findings")
    if not summary["source_review"]["measurement_id"]:
        raise ValueError("source review measurement_id is required")
    sections = summary["review_sections"]
    for section in ("sidecar_post_run_review", "legacy_locator_observation"):
        if section not in sections:
            raise ValueError(f"source review missing {section} section")


def _validate_approval(approval: dict[str, Any]) -> None:
    if set(approval) != _APPROVAL_FIELDS:
        raise ValueError("operator approval must match expected shape")
    if approval["approval_state"] != "approved":
        raise ValueError(
            "reviewed legacy sidecar append intent requires approved operator approval"
        )
    if approval["operator_role"] != "local_reviewer":
        raise ValueError("operator approval role must be local_reviewer")
    if not approval["approved_at"]:
        raise ValueError("operator approval approved_at is required")
    if not approval["rationale"]:
        raise ValueError("operator approval rationale is required")


def _validate_destination(destination: dict[str, Any]) -> None:
    if set(destination) != _DESTINATION_FIELDS:
        raise ValueError("append destination must match expected shape")
    if destination["destination_kind"] != "existing_measurement_record_review_evidence":
        raise ValueError("append destination must target review evidence")
    if destination["append_posture"] != "intent_only":
        raise ValueError("append destination posture must be intent_only")
    if destination["record_write"] != "not_performed":
        raise ValueError("append destination record_write must be not_performed")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["append_request"]
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("reviewed legacy sidecar append request must match expected shape")
    validate_public_identifier(request["request_id"], "append request_id")
    validate_public_identifier(request["measurement_id"], "append measurement_id")
    _validate_approval(request["operator_approval"])
    _validate_destination(request["append_destination"])
    if set(request["selected_fact_sets"]) != _SELECTED_FACT_SETS:
        raise ValueError("append request must select expected reviewed fact sets")
    if request["include_primary_data"] is not False:
        raise ValueError("append request must not include primary data")
    if request["include_legacy_payloads"] is not False:
        raise ValueError("append request must not include legacy payloads")
    if request["include_reference_repair"] is not False:
        raise ValueError("append request must not include reference repair")
    if request["include_measurement_validity"] is not False:
        raise ValueError("append request must not include measurement validity")

    source_review = source["legacy_locator_observation_review_bundle_summary"]
    if request["measurement_id"] != source_review["source_review"]["measurement_id"]:
        raise ValueError("append request measurement_id must match source review")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_source_review(source["legacy_locator_observation_review_bundle_summary"])
    _validate_request(source)


def _classification(source_review: dict[str, Any]) -> str:
    if source_review["classification"] in _READY_SOURCE_CLASSIFICATIONS:
        return "reviewed_legacy_sidecar_append_intent_ready"
    return "reviewed_legacy_sidecar_append_intent_ready_with_review_findings"


def _planned_review_evidence(source_review: dict[str, Any]) -> dict[str, Any]:
    sidecar = source_review["review_sections"]["sidecar_post_run_review"]
    locator = source_review["review_sections"]["legacy_locator_observation"]
    return {
        "sidecar_post_run_review": {
            "classification": sidecar["classification"],
            "review_finding_count": sidecar["review_finding_count"],
            "fact_posture": "review_summary_reference",
        },
        "legacy_locator_observation_review": {
            "classification": source_review["classification"],
            "locator_observation_count": locator["locator_observation_count"],
            "file_backed_locator_count": locator["file_backed_locator_count"],
            "classification_counts": copy.deepcopy(locator["classification_counts"]),
            "observation_status_counts": copy.deepcopy(locator["observation_status_counts"]),
            "observation_finding_count": locator["observation_finding_count"],
            "fact_posture": "review_debug_evidence",
            "does_not_claim": "primary_data_import_or_preview_verification",
        },
    }


def _append_intent_summary(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "measurement_id": request["measurement_id"],
        "approval_state": request["operator_approval"]["approval_state"],
        "operator_role": request["operator_approval"]["operator_role"],
        "approved_at": request["operator_approval"]["approved_at"],
        "append_destination": copy.deepcopy(request["append_destination"]),
        "selected_fact_sets": list(request["selected_fact_sets"]),
        "include_primary_data": request["include_primary_data"],
        "include_legacy_payloads": request["include_legacy_payloads"],
        "include_reference_repair": request["include_reference_repair"],
        "include_measurement_validity": request["include_measurement_validity"],
    }


def _intent_effects() -> dict[str, str]:
    return {
        "storage_mutation": "not_performed",
        "record_write": "not_performed",
        "primary_data_import": "not_performed",
        "data_observation": "not_performed",
        "row_count": "not_performed",
        "schema_inference": "not_performed",
        "preview_verification": "not_performed",
        "legacy_source_parsing": "not_performed_by_scopecat",
        "reference_repair": "not_performed",
        "parameter_write_back": "not_performed",
        "measurement_validity": "not_claimed",
        "gui_workflow": "not_defined",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "append_intent_only",
            "severity": "info",
            "basis": "The summary records an approved intent to append reviewed legacy facts later.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "review_debug_evidence_only",
            "severity": "review",
            "basis": "Selected facts are review/debug evidence, not normalized primary data.",
            "does_not_claim": "primary_data_import_or_payload_materialization",
        },
        {
            "code": "legacy_payload_not_parsed",
            "severity": "review",
            "basis": "The intent does not parse legacy payloads or verify declared preview metadata.",
            "does_not_claim": "row_count_schema_preview_or_data_validation",
        },
        {
            "code": "reference_repair_not_performed",
            "severity": "review",
            "basis": "Locator findings remain review evidence rather than repair instructions.",
            "does_not_claim": "moved_reference_discovery_or_repair",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "The intent does not decide measurement validity or scientific quality.",
            "does_not_claim": "measurement_validity",
        },
    ]


def build_reviewed_legacy_sidecar_append_intent_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build an approved intent summary for later legacy sidecar fact append."""
    _validate_references(source)
    source_review = source["legacy_locator_observation_review_bundle_summary"]
    request = source["append_request"]
    return {
        "append_intent_policy": copy.deepcopy(source["append_intent_policy"]),
        "classification": _classification(source_review),
        "source_review": {
            "measurement_id": source_review["source_review"]["measurement_id"],
            "locator_observation_review_classification": source_review["classification"],
            "review_finding_count": source_review["review_finding_count"],
        },
        "append_intent": _append_intent_summary(request),
        "planned_review_evidence": _planned_review_evidence(source_review),
        "review_findings": copy.deepcopy(source_review["review_findings"]),
        "intent_effects": _intent_effects(),
        "attention": _attention(),
    }
