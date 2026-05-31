"""Structured summary builder for measurement intent resolution.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read primary data, inspect context payloads,
control hardware, write parameters, mutate setup bindings, sync environments,
import code, execute code, restore context, or define a universal context
schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "resolution_authority": "explicit_run_start_resolution",
    "intent_reference_semantics": "moving_selectors_allowed",
    "measurement_record_context": "optional_resolved_links",
    "shared_context_schema": "not_defined",
    "primary_data_observation": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "record_validity": "context_optional",
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
    return _records_by_key(source["measurement_intent"]["moving_context_selectors"], "selector_id")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_selectors(source: dict[str, Any]) -> None:
    _selectors_by_id(source)
    for selector in source["measurement_intent"]["moving_context_selectors"]:
        family = selector["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported selector family: {family}")
        if selector["reference_semantics"] != "moving_reference":
            raise ValueError("intent selectors must be moving references")
        if selector["required_for_measurement_record"]:
            raise ValueError(
                "context selectors must remain optional for measurement record validity"
            )


def _validate_resolution(source: dict[str, Any]) -> None:
    measurement_record_id = source["measurement_record"]["measurement_record_id"]
    receipt = source["run_start_resolution"]
    if receipt["measurement_record_id"] != measurement_record_id:
        raise ValueError("resolution measurement_record_id must match measurement record")

    context_records = _context_records_by_id(source)
    selectors = _selectors_by_id(source)
    resolution_items = _records_by_key(receipt["resolved_contexts"], "selector_id")
    if set(resolution_items) != set(selectors):
        raise ValueError("resolution receipt must cover every intent selector")

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


def _validate_lineage_state(source: dict[str, Any]) -> None:
    context_records = _context_records_by_id(source)
    seen_lineages = set()
    for lineage in source["post_run_lineage_state"]:
        lineage_id = lineage["lineage_id"]
        if lineage_id in seen_lineages:
            raise ValueError(f"duplicate lineage_id: {lineage_id}")
        seen_lineages.add(lineage_id)
        current_context_id = lineage["current_context_id"]
        if current_context_id not in context_records:
            raise ValueError("post-run lineage current context must be known")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    _validate_selectors(source)
    _validate_resolution(source)
    _validate_lineage_state(source)


def _selector_summary(selector: dict[str, Any]) -> dict[str, Any]:
    return {
        "selector_id": selector["selector_id"],
        "family": selector["family"],
        "role": selector["role"],
        "selector_kind": selector["selector_kind"],
        "reference_semantics": selector["reference_semantics"],
        "required_for_measurement_record": selector["required_for_measurement_record"],
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
        "used_in_measurement_record": item["used_in_measurement_record"],
    }
    context = context_records.get(item.get("resolved_context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["finding"] = item["finding"]
    return output


def _record_context_links(source: dict[str, Any]) -> list[dict[str, Any]]:
    context_records = _context_records_by_id(source)
    links = []
    for item in source["run_start_resolution"]["resolved_contexts"]:
        if item["resolution_state"] != "resolved" or not item["used_in_measurement_record"]:
            continue
        context = context_records[item["resolved_context_id"]]
        links.append(
            {
                "measurement_record_id": source["measurement_record"]["measurement_record_id"],
                "family": item["family"],
                "role": item["role"],
                "context_id": item["resolved_context_id"],
                "context_label": context["label"],
                "record_status": context["record_status"],
                "link_semantics": "resolved_snapshot_used_at_run_start",
            }
        )
    return links


def _optional_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for item in source["run_start_resolution"]["resolved_contexts"]:
        if item["resolution_state"] == "resolved":
            continue
        findings.append(
            {
                "measurement_record_id": source["measurement_record"]["measurement_record_id"],
                "selector_id": item["selector_id"],
                "family": item["family"],
                "role": item["role"],
                "severity": "review",
                "finding": item["finding"],
                "basis": item["basis"],
                "does_not_claim": "measurement_record_invalid",
            }
        )
    return findings


def _lineage_movement_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    context_records = _context_records_by_id(source)
    lineage_by_id = {lineage["lineage_id"]: lineage for lineage in source["post_run_lineage_state"]}
    findings = []
    for item in source["run_start_resolution"]["resolved_contexts"]:
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
                "measurement_record_id": source["measurement_record"]["measurement_record_id"],
                "selector_id": item["selector_id"],
                "lineage_id": lineage_id,
                "resolved_context_id": item["resolved_context_id"],
                "post_run_current_context_id": current_context_id,
                "severity": "info",
                "finding": "lineage_moved_after_run_start",
                "does_not_change": "measurement_record_resolved_context_link",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "intent_selectors_are_moving_references",
            "severity": "info",
            "basis": "Measurement intent can name selector rules rather than final context snapshots.",
            "does_not_claim": "intent_is_the_recorded_context",
        },
        {
            "code": "record_context_links_are_resolved_snapshots",
            "severity": "info",
            "basis": "Measurement record context links are copied from the explicit run-start resolution receipt.",
            "does_not_claim": "live_lineage_reference",
        },
        {
            "code": "context_optional_for_measurement_record",
            "severity": "review",
            "basis": "Unresolved optional context produces review findings without invalidating the measurement record.",
            "does_not_claim": "context_required_for_primary_data_validity",
        },
        {
            "code": "shared_context_schema_not_defined",
            "severity": "info",
            "basis": "Resolved records remain family-owned context records.",
            "does_not_claim": "universal_context_payload_schema",
        },
    ]
    if _lineage_movement_findings(source):
        attention.append(
            {
                "code": "lineage_moved_after_run_start",
                "severity": "info",
                "basis": "A post-run lineage current pointer differs from the resolved snapshot used by the measurement record.",
                "does_not_claim": "record_context_rewritten",
            }
        )
    return attention


def build_measurement_intent_resolution_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit intent-resolution fixture input."""
    _validate_references(source)
    context_records = _context_records_by_id(source)
    return {
        "resolution_policy": copy.deepcopy(source["resolution_policy"]),
        "measurement_intent": {
            "intent_id": source["measurement_intent"]["intent_id"],
            "label": source["measurement_intent"]["label"],
            "experiment_type": source["measurement_intent"]["experiment_type"],
            "logical_targets": list(source["measurement_intent"]["logical_targets"]),
            "moving_context_selectors": [
                _selector_summary(selector)
                for selector in source["measurement_intent"]["moving_context_selectors"]
            ],
        },
        "run_start_resolution": {
            "resolution_id": source["run_start_resolution"]["resolution_id"],
            "intent_id": source["run_start_resolution"]["intent_id"],
            "measurement_record_id": source["run_start_resolution"]["measurement_record_id"],
            "resolved_at": source["run_start_resolution"]["resolved_at"],
            "resolved_contexts": [
                _resolved_context_summary(item, context_records)
                for item in source["run_start_resolution"]["resolved_contexts"]
            ],
        },
        "measurement_record": {
            "measurement_record_id": source["measurement_record"]["measurement_record_id"],
            "label": source["measurement_record"]["label"],
            "experiment_type": source["measurement_record"]["experiment_type"],
            "target": source["measurement_record"]["target"],
            "source_kind": source["measurement_record"]["source_kind"],
            "primary_data": copy.deepcopy(source["measurement_record"]["primary_data"]),
            "context_policy": "context_optional_for_record_validity",
            "actual_context_links": _record_context_links(source),
        },
        "optional_context_findings": _optional_context_findings(source),
        "lineage_movement_findings": _lineage_movement_findings(source),
        "attention": _attention(source),
    }
