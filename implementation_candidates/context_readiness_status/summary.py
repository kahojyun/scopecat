"""Structured summary builder for context readiness/status facts.

This module validates explicit family-owned context status facts. It does not
inspect context payloads, traverse relation graphs, check hardware readiness,
sync dependencies, import or execute code, restore context, write back changes,
decide measurement validity, or decide run blocking.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "status_authority": "explicit_context_status_summary",
    "input_source": "declared_context_status_facts",
    "status_scope": "local_context_review_only",
    "context_payload_handling": "family_owned_summary_only",
    "context_import": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "hardware_readiness_check": "not_performed",
    "dependency_sync": "not_performed",
    "code_import_execution": "not_performed",
    "restore": "not_performed",
    "write_back": "not_performed",
    "setup_truth": "not_claimed",
    "measurement_validity": "not_claimed",
    "run_blocking_decision": "not_claimed",
    "runnable_readiness": "not_claimed",
    "shared_status_schema": "not_defined",
    "gui_workflow": "not_defined",
}

_AUTHORITY = "explicit_context_status_summary"
_SUPPORTED_CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "declared_environment",
    "measurement_intent",
    "supporting_evidence",
    "running_measurement",
    "calibration_continuation",
}
_DIMENSION_STATES = {
    "availability": {"available", "unavailable", "redacted"},
    "trust": {"trusted", "unverified", "not_trusted", "not_applicable"},
    "freshness": {"current", "stale", "unknown", "not_applicable"},
    "validity": {"valid", "invalid", "unverified", "not_applicable"},
    "progress": {"complete", "running", "blocked", "not_applicable"},
    "completeness": {"complete", "partial", "missing", "not_applicable"},
}
_SEVERITIES = {"info", "review", "block"}
_DOES_NOT_CLAIM = {
    "run_blocking_decision",
    "runnable_readiness",
    "measurement_validity",
    "setup_truth",
    "hardware_readiness",
    "context_payload_truth",
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
    policy = source["context_status_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("context status policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"context status policy {key} must be {expected}")


def _validate_status_fact(context_id: str, fact: dict[str, Any]) -> None:
    expected_keys = {
        "fact_id",
        "dimension",
        "state",
        "severity",
        "basis",
        "authority",
        "required_for_current_review",
        "does_not_claim",
    }
    if set(fact) != expected_keys:
        raise ValueError("context status fact must match expected shape")
    dimension = fact["dimension"]
    if dimension not in _DIMENSION_STATES:
        raise ValueError(f"unsupported status dimension: {dimension}")
    if fact["state"] not in _DIMENSION_STATES[dimension]:
        raise ValueError(f"unsupported status state for {dimension}: {fact['state']}")
    if fact["severity"] not in _SEVERITIES:
        raise ValueError("context status fact severity is unsupported")
    if fact["authority"] != _AUTHORITY:
        raise ValueError("context status fact authority must stay explicit")
    if fact["does_not_claim"] not in _DOES_NOT_CLAIM:
        raise ValueError("context status fact does_not_claim is unsupported")
    if not fact["basis"]:
        raise ValueError("context status fact basis is required")
    if fact["required_for_current_review"] and fact["severity"] != "block":
        raise ValueError(
            f"context {context_id} required current-review fact must block context review"
        )


def _validate_context_record(context: dict[str, Any]) -> None:
    expected_keys = {
        "context_id",
        "family",
        "label",
        "record_status",
        "authority",
        "payload_handling",
        "declared_summary",
        "status_facts",
    }
    if set(context) != expected_keys:
        raise ValueError("context record must match expected shape")
    if context["family"] not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported context family: {context['family']}")
    if context["payload_handling"] != "family_owned_summary_only":
        raise ValueError("context payload handling must remain family-owned")

    seen_facts = set()
    for fact in context["status_facts"]:
        fact_id = fact["fact_id"]
        if fact_id in seen_facts:
            raise ValueError(f"duplicate fact_id: {fact_id}")
        seen_facts.add(fact_id)
        _validate_status_fact(context["context_id"], fact)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _records_by_key(source["context_records"], "context_id")
    for context in source["context_records"]:
        _validate_context_record(context)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _context_classification(context: dict[str, Any]) -> str:
    severities = {fact["severity"] for fact in context["status_facts"]}
    if "block" in severities:
        return "blocked_for_context_review"
    if "review" in severities:
        return "attention_needed_for_context_review"
    return "ready_for_context_review"


def _overall_classification(contexts: list[dict[str, Any]]) -> str:
    classifications = {_context_classification(context) for context in contexts}
    if "blocked_for_context_review" in classifications:
        return "blocked_for_context_review"
    if "attention_needed_for_context_review" in classifications:
        return "attention_needed_for_context_review"
    return "ready_for_context_review"


def _context_status_summary(context: dict[str, Any]) -> dict[str, Any]:
    facts = context["status_facts"]
    return {
        "context_id": context["context_id"],
        "family": context["family"],
        "label": context["label"],
        "record_status": context["record_status"],
        "authority": context["authority"],
        "payload_handling": context["payload_handling"],
        "declared_summary": copy.deepcopy(context["declared_summary"]),
        "status_fact_count": len(facts),
        "severity_counts": _state_counts(facts, "severity"),
        "dimension_counts": _state_counts(facts, "dimension"),
        "classification": _context_classification(context),
    }


def _status_findings(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for context in contexts:
        for fact in context["status_facts"]:
            if fact["severity"] == "info":
                continue
            findings.append(
                {
                    "context_id": context["context_id"],
                    "family": context["family"],
                    "fact_id": fact["fact_id"],
                    "dimension": fact["dimension"],
                    "state": fact["state"],
                    "severity": fact["severity"],
                    "finding": f"context_{fact['dimension']}_{fact['state']}",
                    "basis": fact["basis"],
                    "required_for_current_review": fact["required_for_current_review"],
                    "does_not_claim": fact["does_not_claim"],
                }
            )
    return findings


def _attention(contexts: list[dict[str, Any]]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "context_status_is_local_review_only",
            "severity": "info",
            "basis": "Context status summarizes declared facts for local review.",
            "does_not_claim": "run_blocking_decision",
        },
        {
            "code": "context_payloads_not_imported",
            "severity": "info",
            "basis": "Context payloads remain family-owned and are not inspected.",
            "does_not_claim": "context_payload_truth",
        },
        {
            "code": "runnable_readiness_not_claimed",
            "severity": "review",
            "basis": "No hardware checks, dependency sync, code import, or execution are performed.",
            "does_not_claim": "runnable_readiness",
        },
    ]
    if any(
        _context_classification(context) == "blocked_for_context_review" for context in contexts
    ):
        attention.append(
            {
                "code": "context_review_block_present",
                "severity": "review",
                "basis": "At least one context fact blocks local context review.",
                "does_not_claim": "automatic_run_blocking",
            }
        )
    if any(
        _context_classification(context) == "attention_needed_for_context_review"
        for context in contexts
    ):
        attention.append(
            {
                "code": "context_attention_present",
                "severity": "review",
                "basis": "At least one context fact needs review attention.",
                "does_not_claim": "measurement_validity",
            }
        )
    return attention


def build_context_readiness_status_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit context readiness/status facts."""
    _validate_references(source)
    contexts = source["context_records"]
    return {
        "context_status_policy": copy.deepcopy(source["context_status_policy"]),
        "context_count": len(contexts),
        "family_counts": _state_counts(contexts, "family"),
        "overall_classification": _overall_classification(contexts),
        "context_statuses": [_context_status_summary(context) for context in contexts],
        "status_findings": _status_findings(contexts),
        "attention": _attention(contexts),
    }
