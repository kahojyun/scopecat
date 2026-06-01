"""Structured summary builder for optional measurement context links.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not read primary data, inspect context payloads,
recursively traverse relation graphs, import linked context, control hardware,
write parameters, mutate setup bindings, sync environments, import code,
execute code, restore context, or define a universal context schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "link_authority": "explicit_measurement_record_context_links",
    "context_requirement": "optional_for_measurement_record",
    "context_payload_handling": "reference_only",
    "primary_data_validity": "independent_of_context",
    "shared_context_schema": "not_defined",
    "recursive_traversal": "not_performed",
    "context_import": "not_performed",
    "primary_data_observation": "not_performed",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
    "analysis_choice",
    "artifact",
}

_INCLUDE_STATES = {
    "linked",
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
    policy = source["context_link_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("context link policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"context link policy {key} must be {expected}")


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _measurement_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurement_records"], "measurement_record_id")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_context_link(
    measurement_record_id: str,
    link: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    family = link["family"]
    include_state = link["include_state"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported context link family: {family}")
    if include_state not in _INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")
    if link["required_for_record_validity"]:
        raise ValueError("context links must remain optional for measurement record validity")

    context_id = link.get("context_id")
    if include_state == "linked":
        if context_id not in context_records:
            raise ValueError(
                f"measurement record {measurement_record_id} references missing context"
            )
        if context_records[context_id]["family"] != family:
            raise ValueError(
                f"measurement record {measurement_record_id} references context from wrong family"
            )
        return

    if context_id is not None:
        raise ValueError("unlinked optional context must not carry context_id")
    if include_state == "optional_unavailable" and not link.get("missing_reason"):
        raise ValueError("unavailable optional context requires a missing_reason")


def _validate_measurement_records(source: dict[str, Any]) -> None:
    _measurement_records_by_id(source)
    context_records = _context_records_by_id(source)
    for measurement in source["measurement_records"]:
        seen_links = set()
        for link in measurement["context_links"]:
            link_id = link["link_id"]
            if link_id in seen_links:
                raise ValueError(f"duplicate link_id: {link_id}")
            seen_links.add(link_id)
            _validate_context_link(
                measurement["measurement_record_id"],
                link,
                context_records,
            )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    _validate_measurement_records(source)


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


def _linked_context_summary(
    measurement: dict[str, Any],
    link: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "measurement_record_id": measurement["measurement_record_id"],
        "link_id": link["link_id"],
        "family": link["family"],
        "role": link["role"],
        "relation": link["relation"],
        "include_state": link["include_state"],
        "required_for_record_validity": link["required_for_record_validity"],
        "context_id": link.get("context_id"),
    }
    context = context_records.get(link.get("context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
        output["link_semantics"] = "reference_only_context_link"
    else:
        output["missing_reason"] = link.get("missing_reason")
    return output


def _measurement_record_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    linked_count = sum(
        1 for link in measurement["context_links"] if link["include_state"] == "linked"
    )
    missing_optional_count = sum(
        1
        for link in measurement["context_links"]
        if link["include_state"] == "optional_unavailable"
    )
    return {
        "measurement_record_id": measurement["measurement_record_id"],
        "label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "target": measurement["target"],
        "source_kind": measurement["source_kind"],
        "primary_data": copy.deepcopy(measurement["primary_data"]),
        "context_policy": "valid_without_context",
        "context_link_count": len(measurement["context_links"]),
        "linked_context_count": linked_count,
        "missing_optional_context_count": missing_optional_count,
        "classification": "measurement_record_valid_for_review",
    }


def _linked_context_refs(source: dict[str, Any]) -> list[dict[str, Any]]:
    context_records = _context_records_by_id(source)
    refs = []
    for measurement in source["measurement_records"]:
        for link in measurement["context_links"]:
            refs.append(_linked_context_summary(measurement, link, context_records))
    return refs


def _optional_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for measurement in source["measurement_records"]:
        for link in measurement["context_links"]:
            if link["include_state"] != "optional_unavailable":
                continue
            findings.append(
                {
                    "measurement_record_id": measurement["measurement_record_id"],
                    "link_id": link["link_id"],
                    "family": link["family"],
                    "role": link["role"],
                    "severity": "review",
                    "finding": "optional_context_unavailable",
                    "basis": link["missing_reason"],
                    "does_not_claim": "measurement_record_invalid",
                }
            )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "zero_context_measurement_records_allowed",
            "severity": "info",
            "basis": "A measurement record with no context links remains valid for review.",
            "does_not_claim": "context_required_for_primary_data_validity",
        },
        {
            "code": "context_links_are_reference_only",
            "severity": "info",
            "basis": "Linked context records remain family-owned and are not imported into the measurement record.",
            "does_not_claim": "context_payload_import",
        },
        {
            "code": "shared_context_schema_not_defined",
            "severity": "info",
            "basis": "The slice validates link posture, not a universal context payload schema.",
            "does_not_claim": "universal_context_payload_schema",
        },
        {
            "code": "recursive_traversal_not_performed",
            "severity": "review",
            "basis": "Only explicitly declared measurement-record context links are summarized.",
            "does_not_claim": "relation_graph_closure",
        },
    ]
    if _optional_context_findings(source):
        attention.append(
            {
                "code": "optional_context_unavailable",
                "severity": "review",
                "basis": "Missing optional context is surfaced as a review finding.",
                "does_not_claim": "measurement_record_invalid",
            }
        )
    return attention


def build_measurement_context_link_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit measurement context links."""
    _validate_references(source)
    return {
        "context_link_policy": copy.deepcopy(source["context_link_policy"]),
        "context_records": [
            _context_record_summary(context) for context in source["context_records"]
        ],
        "measurement_records": [
            _measurement_record_summary(measurement)
            for measurement in source["measurement_records"]
        ],
        "linked_context_refs": _linked_context_refs(source),
        "optional_context_findings": _optional_context_findings(source),
        "attention": _attention(source),
    }
