"""Structured summary builder for calibration step intent resolution.

This module is an experimental production-shaped boundary. It resolves
explicit fixture selectors only and deliberately avoids measurement payload
reads, dynamic selector lookup, calibration execution, fitting, continuation
decisions, parameter write-back, scheduling, and hardware control.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "resolution_authority": "explicit_step_start_resolution",
    "intent_reference_semantics": "moving_selectors_allowed",
    "step_record_context": "optional_resolved_links",
    "observation_link_handling": "reference_only",
    "shared_context_schema": "not_defined",
    "measurement_payload_read": "not_performed",
    "dynamic_selector_resolution": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "scheduler": "not_defined",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
}

_RESOLUTION_STATES = {
    "resolved",
    "optional_unavailable",
    "optional_not_selected",
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
    policy = source["resolution_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("resolution policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"resolution policy {key} must be {expected}")


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _selectors_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["calibration_step_intent"]["moving_context_selectors"], "selector_id"
    )


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_intent(source: dict[str, Any]) -> None:
    intent = source["calibration_step_intent"]
    planned = intent["planned_observation"]
    if planned["kind"] != "measurement_request":
        raise ValueError("planned observation kind must be measurement_request")
    if planned["measurement_payload_required"]:
        raise ValueError("planned observation must not require measurement payload reads")

    _selectors_by_id(source)
    for selector in intent["moving_context_selectors"]:
        family = selector["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported selector family: {family}")
        if selector["reference_semantics"] != "moving_reference":
            raise ValueError("step intent selectors must be moving references")
        if selector["required_for_step_record"]:
            raise ValueError("context selectors must remain optional for step record validity")


def _validate_resolution(source: dict[str, Any]) -> None:
    step_record = source["calibration_step_record"]
    receipt = source["step_start_resolution"]
    if receipt["step_record_id"] != step_record["step_record_id"]:
        raise ValueError("resolution step_record_id must match calibration step record")
    if receipt["step_intent_id"] != source["calibration_step_intent"]["step_intent_id"]:
        raise ValueError("resolution step_intent_id must match calibration step intent")

    context_records = _context_records_by_id(source)
    selectors = _selectors_by_id(source)
    resolution_items = _records_by_key(receipt["resolved_contexts"], "selector_id")
    if set(resolution_items) != set(selectors):
        raise ValueError("resolution receipt must cover every step intent selector")

    for selector_id, item in resolution_items.items():
        selector = selectors[selector_id]
        if item["family"] != selector["family"] or item["role"] != selector["role"]:
            raise ValueError("resolution item must match selector family and role")
        if item["resolution_state"] not in _RESOLUTION_STATES:
            raise ValueError("unsupported resolution state")

        context_id = item.get("resolved_context_id")
        if item["resolution_state"] == "resolved":
            if context_id not in context_records:
                raise ValueError("resolved context must reference a known context record")
            if context_records[context_id]["family"] != item["family"]:
                raise ValueError("resolved context family must match resolution item")
            continue

        if context_id is not None:
            raise ValueError("unresolved optional context must not carry resolved_context_id")
        if not item.get("finding"):
            raise ValueError("unresolved optional context requires a finding")


def _validate_step_record(source: dict[str, Any]) -> None:
    record = source["calibration_step_record"]
    if record["step_intent_id"] != source["calibration_step_intent"]["step_intent_id"]:
        raise ValueError("step record must reference calibration step intent")
    for ref in record["observation_link_refs"]:
        if ref["payload_handling"] != "reference_only":
            raise ValueError("observation link refs must remain reference-only")


def _validate_lineage_state(source: dict[str, Any]) -> None:
    context_records = _context_records_by_id(source)
    seen_lineages = set()
    for lineage in source["post_step_lineage_state"]:
        lineage_id = lineage["lineage_id"]
        if lineage_id in seen_lineages:
            raise ValueError(f"duplicate lineage_id: {lineage_id}")
        seen_lineages.add(lineage_id)
        if lineage["current_context_id"] not in context_records:
            raise ValueError("post-step lineage current context must be known")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    _validate_intent(source)
    _validate_resolution(source)
    _validate_step_record(source)
    _validate_lineage_state(source)


def _selector_summary(selector: dict[str, Any]) -> dict[str, Any]:
    return {
        "selector_id": selector["selector_id"],
        "family": selector["family"],
        "role": selector["role"],
        "selector_kind": selector["selector_kind"],
        "reference_semantics": selector["reference_semantics"],
        "required_for_step_record": selector["required_for_step_record"],
        "selector_basis": copy.deepcopy(selector["selector_basis"]),
    }


def _resolved_context_summary(
    item: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "selector_id": item["selector_id"],
        "family": item["family"],
        "role": item["role"],
        "resolution_state": item["resolution_state"],
        "resolved_context_id": item.get("resolved_context_id"),
        "used_in_step_record": item["used_in_step_record"],
    }
    context = context_records.get(item.get("resolved_context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["finding"] = item["finding"]
    return output


def _step_context_links(source: dict[str, Any]) -> list[dict[str, Any]]:
    context_records = _context_records_by_id(source)
    links = []
    for item in source["step_start_resolution"]["resolved_contexts"]:
        if item["resolution_state"] != "resolved" or not item["used_in_step_record"]:
            continue
        context = context_records[item["resolved_context_id"]]
        links.append(
            {
                "step_record_id": source["calibration_step_record"]["step_record_id"],
                "family": item["family"],
                "role": item["role"],
                "context_id": item["resolved_context_id"],
                "context_label": context["label"],
                "record_status": context["record_status"],
                "link_semantics": "resolved_snapshot_used_at_step_start",
            }
        )
    return links


def _optional_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for item in source["step_start_resolution"]["resolved_contexts"]:
        if item["resolution_state"] == "resolved":
            continue
        findings.append(
            {
                "step_record_id": source["calibration_step_record"]["step_record_id"],
                "selector_id": item["selector_id"],
                "family": item["family"],
                "role": item["role"],
                "severity": "review",
                "finding": item["finding"],
                "basis": item["basis"],
                "does_not_claim": "calibration_step_invalid_or_blocked",
            }
        )
    return findings


def _lineage_movement_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    context_records = _context_records_by_id(source)
    lineage_by_id = {
        lineage["lineage_id"]: lineage for lineage in source["post_step_lineage_state"]
    }
    findings = []
    for item in source["step_start_resolution"]["resolved_contexts"]:
        if item["resolution_state"] != "resolved":
            continue
        context = context_records[item["resolved_context_id"]]
        lineage_id = context["declared_summary"].get("lineage_id")
        if lineage_id is None or lineage_id not in lineage_by_id:
            continue
        current_context_id = lineage_by_id[lineage_id]["current_context_id"]
        if current_context_id == item["resolved_context_id"]:
            continue
        findings.append(
            {
                "step_record_id": source["calibration_step_record"]["step_record_id"],
                "selector_id": item["selector_id"],
                "lineage_id": lineage_id,
                "resolved_context_id": item["resolved_context_id"],
                "post_step_current_context_id": current_context_id,
                "severity": "info",
                "finding": "lineage_moved_after_step_start",
                "does_not_change": "calibration_step_record_resolved_context_link",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "step_intent_selectors_are_moving_references",
            "severity": "info",
            "basis": "Calibration step intent can name selector rules rather than final context snapshots.",
            "does_not_claim": "intent_is_the_recorded_context",
        },
        {
            "code": "step_record_context_links_are_resolved_snapshots",
            "severity": "info",
            "basis": "Calibration step record context links are copied from explicit step-start resolution.",
            "does_not_claim": "live_lineage_reference",
        },
        {
            "code": "observation_links_are_reference_only",
            "severity": "info",
            "basis": "Observation links are referenced but not read or interpreted by this slice.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "Resolved context and observation refs do not run fitting.",
            "does_not_claim": "fit_result_or_quality_score",
        },
        {
            "code": "write_back_not_performed",
            "severity": "review",
            "basis": "Step context resolution does not apply or propose parameter writes.",
            "does_not_claim": "parameter_update",
        },
    ]
    if _optional_context_findings(source):
        attention.append(
            {
                "code": "optional_context_unavailable",
                "severity": "review",
                "basis": "Missing optional context is surfaced as a review finding.",
                "does_not_claim": "calibration_step_invalid_or_blocked",
            }
        )
    if _lineage_movement_findings(source):
        attention.append(
            {
                "code": "lineage_moved_after_step_start",
                "severity": "info",
                "basis": "A post-step lineage current pointer differs from the resolved snapshot used by the step record.",
                "does_not_claim": "step_record_context_rewritten",
            }
        )
    return attention


def build_calibration_step_intent_resolution_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a calibration step intent-resolution summary from explicit facts."""
    _validate_references(source)
    context_records = _context_records_by_id(source)
    intent = source["calibration_step_intent"]
    record = source["calibration_step_record"]
    return {
        "resolution_policy": copy.deepcopy(source["resolution_policy"]),
        "calibration_step_intent": {
            "step_intent_id": intent["step_intent_id"],
            "label": intent["label"],
            "target": intent["target"],
            "purpose": intent["purpose"],
            "planned_observation": copy.deepcopy(intent["planned_observation"]),
            "moving_context_selectors": [
                _selector_summary(selector) for selector in intent["moving_context_selectors"]
            ],
        },
        "step_start_resolution": {
            "resolution_id": source["step_start_resolution"]["resolution_id"],
            "step_intent_id": source["step_start_resolution"]["step_intent_id"],
            "step_record_id": source["step_start_resolution"]["step_record_id"],
            "resolved_at": source["step_start_resolution"]["resolved_at"],
            "resolved_contexts": [
                _resolved_context_summary(item, context_records)
                for item in source["step_start_resolution"]["resolved_contexts"]
            ],
        },
        "calibration_step_record": {
            "step_record_id": record["step_record_id"],
            "step_intent_id": record["step_intent_id"],
            "label": record["label"],
            "target": record["target"],
            "record_state": record["record_state"],
            "context_policy": "context_optional_for_step_record",
            "actual_context_links": _step_context_links(source),
            "observation_link_refs": copy.deepcopy(record["observation_link_refs"]),
        },
        "optional_context_findings": _optional_context_findings(source),
        "lineage_movement_findings": _lineage_movement_findings(source),
        "attention": _attention(source),
    }
