"""Structured summary builder for a named run-start input set.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not control hardware, write parameters, mutate setup
bindings, sync environments, import code, execute code, restore context, read
source payloads, or define a universal context schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "input_set_authority": "preparation_summary_only",
    "context_source": "declared_fixture_records",
    "shared_context_schema": "not_defined",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "selection_completeness_only",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
    "measurement_intent",
}

_ALLOWED_INCLUDE_STATES = {
    "selected",
    "unavailable",
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


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _input_sets_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["run_start_input_sets"], "input_set_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["run_start_input_policy"]
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"run-start input policy {key} must be {expected}")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_selected_context(
    input_set_id: str,
    selected_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    family = selected_context["family"]
    include_state = selected_context["include_state"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported selected context family: {family}")
    if include_state not in _ALLOWED_INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")

    context_id = selected_context.get("context_id")
    if include_state == "selected":
        if context_id not in context_records:
            raise ValueError(
                f"run-start input set {input_set_id} references missing selected context"
            )
        if context_records[context_id]["family"] != family:
            raise ValueError(
                f"run-start input set {input_set_id} references context from wrong family"
            )
        return

    if selected_context["required"] and not selected_context.get("missing_reason"):
        raise ValueError(
            f"run-start input set {input_set_id} required unavailable context needs a reason"
        )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    context_records = _context_records_by_id(source)
    _input_sets_by_id(source)

    for input_set in source["run_start_input_sets"]:
        seen_roles = set()
        for selected_context in input_set["selected_contexts"]:
            role_key = (selected_context["family"], selected_context["role"])
            if role_key in seen_roles:
                raise ValueError("run-start input set contains duplicate family role")
            seen_roles.add(role_key)
            _validate_selected_context(input_set["input_set_id"], selected_context, context_records)


def _context_record_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "family": context["family"],
        "label": context["label"],
        "record_status": context["record_status"],
        "authority": context["authority"],
        "payload_handling": context["payload_handling"],
        "declared_summary": copy.deepcopy(context["declared_summary"]),
    }


def _selected_context_summary(
    input_set_id: str,
    selected_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "input_set_id": input_set_id,
        "family": selected_context["family"],
        "role": selected_context["role"],
        "required": selected_context["required"],
        "include_state": selected_context["include_state"],
        "context_id": selected_context.get("context_id"),
    }
    context = context_records.get(selected_context.get("context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["missing_reason"] = selected_context.get("missing_reason")
    return output


def _missing_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for input_set in source["run_start_input_sets"]:
        for selected_context in input_set["selected_contexts"]:
            if selected_context["include_state"] == "selected":
                continue
            if not selected_context["required"]:
                continue
            findings.append(
                {
                    "input_set_id": input_set["input_set_id"],
                    "family": selected_context["family"],
                    "role": selected_context["role"],
                    "severity": "review",
                    "finding": "required_context_unavailable",
                    "basis": selected_context["missing_reason"],
                    "does_not_claim": "run_is_blocked_or_unsafe",
                }
            )
    return findings


def _input_set_summary(input_set: dict[str, Any]) -> dict[str, Any]:
    required_count = sum(1 for item in input_set["selected_contexts"] if item["required"])
    selected_count = sum(
        1 for item in input_set["selected_contexts"] if item["include_state"] == "selected"
    )
    unavailable_required_count = sum(
        1
        for item in input_set["selected_contexts"]
        if item["required"] and item["include_state"] != "selected"
    )
    return {
        "input_set_id": input_set["input_set_id"],
        "label": input_set["label"],
        "run_start_target": copy.deepcopy(input_set["run_start_target"]),
        "context_ref_count": len(input_set["selected_contexts"]),
        "required_context_count": required_count,
        "selected_context_count": selected_count,
        "unavailable_required_context_count": unavailable_required_count,
        "preparation_claim": input_set["preparation_claim"],
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    attention = []
    if any(
        selected_context["include_state"] != "selected" and selected_context["required"]
        for input_set in source["run_start_input_sets"]
        for selected_context in input_set["selected_contexts"]
    ):
        attention.append(
            {
                "code": "required_context_unavailable",
                "severity": "review",
                "basis": "At least one required run-start context record is unavailable.",
                "does_not_claim": "automatic_run_blocking",
            }
        )

    policy = source["run_start_input_policy"]
    if policy["shared_context_schema"] == "not_defined":
        attention.append(
            {
                "code": "shared_context_schema_not_defined",
                "severity": "info",
                "basis": "The input set groups family-owned context records by reference.",
                "does_not_claim": "universal_context_payload_schema",
            }
        )
    if policy["hardware_control"] == "not_performed":
        attention.append(
            {
                "code": "hardware_control_not_granted",
                "severity": "review",
                "basis": "Run-start input selection does not configure instruments.",
                "does_not_claim": "hardware_state_applied",
            }
        )
    if policy["environment_sync"] == "not_performed":
        attention.append(
            {
                "code": "environment_sync_not_performed",
                "severity": "review",
                "basis": "Declared environment context is a selected record, not a synced runtime.",
                "does_not_claim": "runnable_environment",
            }
        )
    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Selected code context is not imported, loaded, or executed.",
                "does_not_claim": "execution_permission",
            }
        )
    return attention


def build_named_run_start_input_set_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured run-start input set summary from explicit fixture input."""
    _validate_references(source)
    context_records = _context_records_by_id(source)
    return {
        "run_start_input_policy": copy.deepcopy(source["run_start_input_policy"]),
        "context_records": [
            _context_record_summary(context) for context in source["context_records"]
        ],
        "run_start_input_sets": [
            _input_set_summary(input_set) for input_set in source["run_start_input_sets"]
        ],
        "selected_context_refs": [
            _selected_context_summary(input_set["input_set_id"], selected_context, context_records)
            for input_set in source["run_start_input_sets"]
            for selected_context in input_set["selected_contexts"]
        ],
        "missing_context_findings": _missing_context_findings(source),
        "attention": _attention(source),
    }
