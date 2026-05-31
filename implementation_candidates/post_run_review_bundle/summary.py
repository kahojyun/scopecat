"""Review-only post-run bundle over prior summary facts."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "bundle_authority": "explicit_post_run_review_bundle",
    "bundle_posture": "local_review_summary",
    "input_source": "prior_review_summaries",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_observation": "not_performed",
    "evidence_payload_import": "not_performed",
    "file_observation": "not_performed",
    "artifact_provenance": "not_performed",
    "fit_validation": "not_performed",
    "import_export_package": "not_produced",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_review_schema": "not_defined",
}

_COMPLETION_STATES = {"completed", "aborted", "stopped_with_partial_data"}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["post_run_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("post-run review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"post-run review policy {key} must be {expected}")


def _validate_completed_measurement(source: dict[str, Any]) -> None:
    measurement = source["completed_measurement"]
    expected_keys = {
        "measurement_record_id",
        "source_running_measurement_id",
        "label",
        "experiment_type",
        "target",
        "completion_state",
        "source_summary",
    }
    if set(measurement) != expected_keys:
        raise ValueError("completed measurement must match expected shape")
    if not measurement["measurement_record_id"]:
        raise ValueError("completed measurement_record_id is required")
    if not measurement["source_running_measurement_id"]:
        raise ValueError("source_running_measurement_id is required")
    if measurement["completion_state"] not in _COMPLETION_STATES:
        raise ValueError("completed measurement completion_state is unsupported")
    if measurement["source_summary"] != "declared_completed_measurement_summary":
        raise ValueError("completed measurement source_summary must stay declared")


def _validate_context_link_summary(source: dict[str, Any]) -> None:
    summary = source["context_link_summary"]
    policy = summary["context_link_policy"]
    if policy["context_payload_handling"] != "reference_only":
        raise ValueError("context link payload handling must remain reference_only")
    if policy["primary_data_validity"] != "independent_of_context":
        raise ValueError("context link summary must not claim primary data validity")
    if policy["context_import"] != "not_performed":
        raise ValueError("context import must not be performed")
    measurement_id = source["completed_measurement"]["measurement_record_id"]
    records = [
        record
        for record in summary["measurement_records"]
        if record["measurement_record_id"] == measurement_id
    ]
    if len(records) != 1:
        raise ValueError("context link summary must contain the completed measurement")
    if records[0]["classification"] != "measurement_record_valid_for_review":
        raise ValueError("context link summary classification is unsupported")


def _validate_context_status_summary(source: dict[str, Any]) -> None:
    summary = source["context_status_summary"]
    policy = summary["context_status_policy"]
    if policy["status_scope"] != "local_context_review_only":
        raise ValueError("context status scope must stay local review only")
    for key in (
        "context_import",
        "recursive_relation_traversal",
        "hardware_readiness_check",
        "dependency_sync",
        "code_import_execution",
        "restore",
        "write_back",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"context status policy {key} must be not_performed")
    if policy["measurement_validity"] != "not_claimed":
        raise ValueError("context status must not claim measurement validity")


def _validate_running_evidence_update(source: dict[str, Any]) -> None:
    update = source["running_evidence_update_summary"]
    policy = update["evidence_update_policy"]
    required = {
        "payload_import": "not_performed",
        "file_observation": "not_performed",
        "storage_mutation": "not_performed",
        "record_write": "not_performed",
        "runner_control": "not_performed",
        "log_streaming": "not_performed",
        "artifact_provenance": "not_performed",
        "measurement_validity": "not_claimed",
    }
    for key, expected in required.items():
        if policy[key] != expected:
            raise ValueError(f"running evidence update policy {key} must be {expected}")
    expected_running_id = source["completed_measurement"]["source_running_measurement_id"]
    if update["running_record"]["measurement_id"] != expected_running_id:
        raise ValueError("running evidence update must match source running measurement")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_completed_measurement(source)
    _validate_context_link_summary(source)
    _validate_context_status_summary(source)
    _validate_running_evidence_update(source)


def _linked_context_ids(source: dict[str, Any]) -> set[str]:
    measurement_id = source["completed_measurement"]["measurement_record_id"]
    return {
        ref["context_id"]
        for ref in source["context_link_summary"]["linked_context_refs"]
        if ref["measurement_record_id"] == measurement_id
    }


def _scoped_optional_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    measurement_id = source["completed_measurement"]["measurement_record_id"]
    return [
        finding
        for finding in source["context_link_summary"]["optional_context_findings"]
        if finding["measurement_record_id"] == measurement_id
    ]


def _scoped_context_statuses(source: dict[str, Any]) -> list[dict[str, Any]]:
    linked_context_ids = _linked_context_ids(source)
    return [
        status
        for status in source["context_status_summary"]["context_statuses"]
        if status["context_id"] in linked_context_ids
    ]


def _scoped_context_status_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    linked_context_ids = _linked_context_ids(source)
    return [
        finding
        for finding in source["context_status_summary"]["status_findings"]
        if finding["context_id"] in linked_context_ids
    ]


def _scoped_context_status_classification(source: dict[str, Any]) -> str:
    classifications = {status["classification"] for status in _scoped_context_statuses(source)}
    if "blocked_for_context_review" in classifications:
        return "blocked_for_context_review"
    if "attention_needed_for_context_review" in classifications:
        return "attention_needed_for_context_review"
    return "ready_for_context_review"


def _classification(source: dict[str, Any]) -> str:
    if _scoped_context_status_classification(source) == "blocked_for_context_review":
        return "post_run_review_blocked"
    if (
        _scoped_optional_context_findings(source)
        or _scoped_context_status_findings(source)
        or source["running_evidence_update_summary"]["evidence_findings"]
    ):
        return "post_run_review_needs_attention"
    return "post_run_review_ready"


def _context_section(source: dict[str, Any]) -> dict[str, Any]:
    summary = source["context_link_summary"]
    measurement_id = source["completed_measurement"]["measurement_record_id"]
    refs = [
        ref
        for ref in summary["linked_context_refs"]
        if ref["measurement_record_id"] == measurement_id
    ]
    return {
        "linked_context_count": len(refs),
        "linked_context_refs": copy.deepcopy(refs),
        "optional_context_findings": copy.deepcopy(_scoped_optional_context_findings(source)),
    }


def _status_section(source: dict[str, Any]) -> dict[str, Any]:
    statuses = _scoped_context_statuses(source)
    findings = _scoped_context_status_findings(source)
    return {
        "overall_classification": _scoped_context_status_classification(source),
        "context_count": len(statuses),
        "status_findings": copy.deepcopy(findings),
    }


def _evidence_section(source: dict[str, Any]) -> dict[str, Any]:
    update = source["running_evidence_update_summary"]
    return {
        "evidence_count": update["evidence_count"],
        "evidence_kind_counts": copy.deepcopy(update["evidence_kind_counts"]),
        "evidence_lifecycle_counts": copy.deepcopy(update["evidence_lifecycle_counts"]),
        "evidence_refs": copy.deepcopy(update["evidence_refs"]),
        "evidence_findings": copy.deepcopy(update["evidence_findings"]),
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for finding in _scoped_optional_context_findings(source):
        item = copy.deepcopy(finding)
        item["source_section"] = "context_links"
        findings.append(item)
    for finding in _scoped_context_status_findings(source):
        item = copy.deepcopy(finding)
        item["source_section"] = "context_status"
        findings.append(item)
    for finding in source["running_evidence_update_summary"]["evidence_findings"]:
        item = copy.deepcopy(finding)
        item["source_section"] = "supporting_evidence"
        findings.append(item)
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "post_run_review_only",
            "severity": "info",
            "basis": "The bundle groups prior summaries for local post-run review.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "primary_data_not_observed",
            "severity": "review",
            "basis": "The bundle does not open, parse, or validate primary measurement data.",
            "does_not_claim": "measurement_validity",
        },
        {
            "code": "evidence_not_imported",
            "severity": "review",
            "basis": "Supporting evidence references are carried without importing payloads or observing files.",
            "does_not_claim": "evidence_contents_verified",
        },
        {
            "code": "artifact_provenance_not_validated",
            "severity": "review",
            "basis": "Generated artifact provenance and source links remain separate future work.",
            "does_not_claim": "artifact_provenance_complete",
        },
    ]


def build_post_run_review_bundle_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a local post-run review bundle summary from prior summaries."""
    _validate_references(source)
    findings = _review_findings(source)
    return {
        "post_run_review_policy": copy.deepcopy(source["post_run_review_policy"]),
        "completed_measurement": copy.deepcopy(source["completed_measurement"]),
        "classification": _classification(source),
        "review_sections": {
            "context": _context_section(source),
            "status": _status_section(source),
            "supporting_evidence": _evidence_section(source),
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "attention": _attention(),
    }
