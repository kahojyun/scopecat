"""Prepared-run context inclusion semantics.

This module validates selected-vs-required context semantics without defining
a universal context schema or a template language. Selected context references
are recorded when they have IDs; `required` only determines how missing or
unavailable context is surfaced for review.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "semantics_authority": "declared_context_inclusion_policy",
    "context_source": "declared_context_records",
    "selected_context_recording": "record_when_context_id_is_provided",
    "required_semantics": "absence_severity_only",
    "optional_context_recording": "record_when_selected",
    "template_language": "not_defined",
    "migration_requirement": "not_imposed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "run_blocking": "not_decided",
    "shared_context_schema": "not_defined",
    "gui_workflow": "not_defined",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "measurement_intent",
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "editable_workspace_observation",
    "declared_environment",
}

_ALLOWED_INCLUDE_STATES = {
    "selected",
    "unavailable",
    "optional_not_selected",
}

_REQUIREMENT_SOURCES = {
    "opportunistic_context_recording",
    "declared_template_input",
    "manual_preparation_policy",
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


def _prepared_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["prepared_contexts"], "prepared_context_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["context_inclusion_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("context inclusion policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"context inclusion policy {key} must be {expected}")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        if context["family"] not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {context['family']}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_context_ref(
    prepared_context_id: str,
    context_ref: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    family = context_ref["family"]
    include_state = context_ref["include_state"]
    requirement_source = context_ref["requirement_source"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported selected context family: {family}")
    if include_state not in _ALLOWED_INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")
    if requirement_source not in _REQUIREMENT_SOURCES:
        raise ValueError(f"unsupported requirement_source: {requirement_source}")
    if context_ref["required"] and requirement_source == "opportunistic_context_recording":
        raise ValueError("opportunistic context recording must not make context required")

    context_id = context_ref.get("context_id")
    if include_state == "selected":
        if "missing_reason" in context_ref:
            raise ValueError("selected context must not carry missing_reason")
        if context_id not in context_records:
            raise ValueError(
                f"prepared context {prepared_context_id} references missing selected context"
            )
        if context_records[context_id]["family"] != family:
            raise ValueError(
                f"prepared context {prepared_context_id} references context from wrong family"
            )
        return

    if context_id is not None:
        raise ValueError("non-selected context must not carry context_id")
    if include_state == "optional_not_selected" and context_ref["required"]:
        raise ValueError("optional_not_selected context must not be required")
    if include_state == "unavailable" and not context_ref.get("missing_reason"):
        raise ValueError("unavailable context needs missing_reason")
    if include_state == "optional_not_selected" and context_ref.get("missing_reason"):
        raise ValueError("optional_not_selected context must not carry missing_reason")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    context_records = _context_records_by_id(source)
    _prepared_contexts_by_id(source)
    for prepared_context in source["prepared_contexts"]:
        seen_roles = set()
        for context_ref in prepared_context["context_refs"]:
            role_key = (context_ref["family"], context_ref["role"])
            if role_key in seen_roles:
                raise ValueError("prepared context contains duplicate family role")
            seen_roles.add(role_key)
            _validate_context_ref(
                prepared_context["prepared_context_id"],
                context_ref,
                context_records,
            )


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


def _context_ref_summary(
    prepared_context_id: str,
    context_ref: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "prepared_context_id": prepared_context_id,
        "family": context_ref["family"],
        "role": context_ref["role"],
        "include_state": context_ref["include_state"],
        "context_id": context_ref.get("context_id"),
        "required": context_ref["required"],
        "requirement_source": context_ref["requirement_source"],
        "recording_state": "recorded"
        if context_ref["include_state"] == "selected"
        else "not_recorded",
        "absence_severity": "review"
        if context_ref["required"] and context_ref["include_state"] != "selected"
        else "informational",
    }
    context = context_records.get(context_ref.get("context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["missing_reason"] = context_ref.get("missing_reason")
    return output


def _prepared_context_summary(prepared_context: dict[str, Any]) -> dict[str, Any]:
    selected_refs = [
        item for item in prepared_context["context_refs"] if item["include_state"] == "selected"
    ]
    optional_recorded = [item for item in selected_refs if not item["required"]]
    required_absent = [
        item
        for item in prepared_context["context_refs"]
        if item["required"] and item["include_state"] != "selected"
    ]
    optional_absent = [
        item
        for item in prepared_context["context_refs"]
        if not item["required"] and item["include_state"] != "selected"
    ]
    return {
        "prepared_context_id": prepared_context["prepared_context_id"],
        "label": prepared_context["label"],
        "context_ref_count": len(prepared_context["context_refs"]),
        "selected_context_count": len(selected_refs),
        "recorded_optional_context_count": len(optional_recorded),
        "required_absent_context_count": len(required_absent),
        "optional_absent_context_count": len(optional_absent),
        "semantics_claim": prepared_context["semantics_claim"],
    }


def _required_absence_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for prepared_context in source["prepared_contexts"]:
        for context_ref in prepared_context["context_refs"]:
            if context_ref["include_state"] == "selected" or not context_ref["required"]:
                continue
            findings.append(
                {
                    "prepared_context_id": prepared_context["prepared_context_id"],
                    "family": context_ref["family"],
                    "role": context_ref["role"],
                    "requirement_source": context_ref["requirement_source"],
                    "severity": "review",
                    "finding": "required_context_unavailable",
                    "basis": context_ref["missing_reason"],
                    "does_not_claim": "automatic_run_blocking_or_template_design",
                }
            )
    return findings


def _optional_absence_notes(source: dict[str, Any]) -> list[dict[str, Any]]:
    notes = []
    for prepared_context in source["prepared_contexts"]:
        for context_ref in prepared_context["context_refs"]:
            if context_ref["include_state"] == "selected" or context_ref["required"]:
                continue
            notes.append(
                {
                    "prepared_context_id": prepared_context["prepared_context_id"],
                    "family": context_ref["family"],
                    "role": context_ref["role"],
                    "include_state": context_ref["include_state"],
                    "requirement_source": context_ref["requirement_source"],
                    "severity": "info",
                    "note": "optional_context_absent",
                    "basis": context_ref.get("missing_reason"),
                    "does_not_claim": "missing_required_input",
                }
            )
    return notes


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "selected_contexts_are_recorded",
            "severity": "info",
            "basis": "Selected context refs with IDs are recorded regardless of required=false.",
            "does_not_claim": "required_input_contract",
        },
        {
            "code": "required_controls_absence_severity",
            "severity": "review",
            "basis": "Required contexts matter when missing or unavailable, not when selected.",
            "does_not_claim": "global_context_family_requirement",
        },
        {
            "code": "opportunistic_recording_supported",
            "severity": "info",
            "basis": "Users can record available context without migrating every old experiment surface.",
            "does_not_claim": "migration_requirement",
        },
        {
            "code": "template_language_not_defined",
            "severity": "review",
            "basis": "Requirement source is recorded but no reusable experiment-template language is accepted.",
            "does_not_claim": "template_schema_or_runner_contract",
        },
    ]


def build_context_inclusion_semantics_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build context inclusion semantics summary from explicit fixture input."""
    _validate_references(source)
    context_records = _context_records_by_id(source)
    return {
        "context_inclusion_policy": copy.deepcopy(source["context_inclusion_policy"]),
        "context_records": [
            _context_record_summary(context) for context in source["context_records"]
        ],
        "prepared_contexts": [
            _prepared_context_summary(prepared_context)
            for prepared_context in source["prepared_contexts"]
        ],
        "context_refs": [
            _context_ref_summary(
                prepared_context["prepared_context_id"],
                context_ref,
                context_records,
            )
            for prepared_context in source["prepared_contexts"]
            for context_ref in prepared_context["context_refs"]
        ],
        "required_absence_findings": _required_absence_findings(source),
        "optional_absence_notes": _optional_absence_notes(source),
        "attention": _attention(),
    }
