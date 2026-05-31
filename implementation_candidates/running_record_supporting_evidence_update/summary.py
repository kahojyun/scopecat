"""Review-only summary for adding supporting evidence to a running record.

This module validates declared running-record facts and prior
supporting-evidence reference summaries. It does not import evidence payloads,
observe files, append storage, control runners, stream logs, validate artifact
provenance, decide measurement validity, or define GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "update_authority": "explicit_running_record_supporting_evidence_update",
    "update_posture": "local_review_summary",
    "evidence_source": "supporting_evidence_reference_summary",
    "required_evidence_lifecycle": "during_run",
    "payload_import": "not_performed",
    "file_observation": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "runner_control": "not_performed",
    "log_streaming": "not_performed",
    "artifact_provenance": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_running_record_schema": "not_defined",
}

_RUNNING_STATES = {"recording", "paused", "stalled", "stopping"}
_SUPPORTED_EVIDENCE_KINDS = {"attachment", "artifact", "unspecified"}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["evidence_update_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("running-record evidence update policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"running-record evidence update policy {key} must be {expected}")


def _validate_running_record(source: dict[str, Any]) -> None:
    record = source["running_record"]
    expected_keys = {
        "measurement_id",
        "label",
        "experiment_type",
        "target",
        "lifecycle_state",
        "recording_enabled",
        "progress_state",
        "source_summary",
    }
    if set(record) != expected_keys:
        raise ValueError("running record must match expected shape")
    if not record["measurement_id"]:
        raise ValueError("running record measurement_id is required")
    if record["lifecycle_state"] not in _RUNNING_STATES:
        raise ValueError("running record lifecycle_state is unsupported")
    if type(record["recording_enabled"]) is not bool:
        raise ValueError("running record recording_enabled must be boolean")
    if record["source_summary"] != "declared_running_measurement_summary":
        raise ValueError("running record source_summary must stay declared")


def _validate_supporting_evidence_summary(summary: dict[str, Any]) -> None:
    policy = summary["supporting_evidence_policy"]
    required_policy = {
        "evidence_posture": "supporting_evidence_reference",
        "payload_import": "not_performed",
        "file_observation": "not_performed",
        "storage_mutation": "not_performed",
        "artifact_provenance": "not_required_without_artifact_provenance_slice",
        "measurement_validity": "not_claimed",
    }
    for key, expected in required_policy.items():
        if policy[key] != expected:
            raise ValueError(f"supporting evidence policy {key} must be {expected}")
    evidence = summary["evidence"]
    if evidence["evidence_kind"] not in _SUPPORTED_EVIDENCE_KINDS:
        raise ValueError("supporting evidence evidence_kind is unsupported")
    if evidence["lifecycle_stage"] != "during_run":
        raise ValueError("supporting evidence lifecycle_stage must be during_run")


def _running_links(summary: dict[str, Any], measurement_id: str) -> list[dict[str, Any]]:
    return [
        link
        for link in summary["supporting_links"]
        if link["target_type"] == "running_measurement" and link["target_id"] == measurement_id
    ]


def _validate_evidence_links(source: dict[str, Any]) -> None:
    measurement_id = source["running_record"]["measurement_id"]
    seen = set()
    for summary in source["supporting_evidence_summaries"]:
        _validate_supporting_evidence_summary(summary)
        evidence_id = summary["evidence"]["evidence_id"]
        if evidence_id in seen:
            raise ValueError(f"duplicate evidence_id: {evidence_id}")
        seen.add(evidence_id)
        links = _running_links(summary, measurement_id)
        if not links:
            raise ValueError("supporting evidence must link to the running measurement")
        if any(link["target_state"] != "resolved" for link in links):
            raise ValueError("running measurement evidence link must be resolved")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_running_record(source)
    _validate_evidence_links(source)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(summaries: list[dict[str, Any]]) -> str:
    if any(summary["reference_findings"] for summary in summaries):
        return "running_record_evidence_update_needs_review"
    return "running_record_evidence_update_ready_for_review"


def _evidence_ref(summary: dict[str, Any], measurement_id: str) -> dict[str, Any]:
    evidence = summary["evidence"]
    running_link = _running_links(summary, measurement_id)[0]
    return {
        "evidence_id": evidence["evidence_id"],
        "label": evidence["label"],
        "evidence_kind": evidence["evidence_kind"],
        "content_kind": evidence["content_kind"],
        "purpose": evidence["purpose"],
        "lifecycle_stage": evidence["lifecycle_stage"],
        "running_measurement_link": copy.deepcopy(running_link),
        "declared_reference": copy.deepcopy(evidence["declared_reference"]),
        "classification": summary["classification"],
    }


def _attention(summaries: list[dict[str, Any]]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "during_run_evidence_only",
            "severity": "info",
            "basis": "This update summary only accepts supporting evidence declared as during-run.",
            "does_not_claim": "run_start_context_requirement",
        },
        {
            "code": "evidence_payload_not_imported",
            "severity": "review",
            "basis": "Evidence references are carried from supporting-evidence summaries without importing payloads.",
            "does_not_claim": "evidence_contents_verified",
        },
        {
            "code": "record_write_not_performed",
            "severity": "review",
            "basis": "The update is a local review summary and does not append to running-record storage.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "runner_not_owned",
            "severity": "review",
            "basis": "The update does not control runners, stream logs, or observe runtime files.",
            "does_not_claim": "runner_or_log_streaming_authority",
        },
    ]
    if any(summary["reference_findings"] for summary in summaries):
        attention.append(
            {
                "code": "supporting_evidence_findings_present",
                "severity": "review",
                "basis": "At least one supporting-evidence summary has review findings.",
                "does_not_claim": "measurement_invalid",
            }
        )
    return attention


def build_running_record_supporting_evidence_update_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a review-only running-record supporting-evidence update summary."""
    _validate_references(source)
    summaries = source["supporting_evidence_summaries"]
    evidence_items = [summary["evidence"] for summary in summaries]
    measurement_id = source["running_record"]["measurement_id"]
    findings = [
        copy.deepcopy(finding) for summary in summaries for finding in summary["reference_findings"]
    ]
    return {
        "evidence_update_policy": copy.deepcopy(source["evidence_update_policy"]),
        "running_record": copy.deepcopy(source["running_record"]),
        "evidence_count": len(summaries),
        "evidence_kind_counts": _state_counts(evidence_items, "evidence_kind"),
        "evidence_lifecycle_counts": _state_counts(evidence_items, "lifecycle_stage"),
        "classification": _classification(summaries),
        "evidence_refs": [_evidence_ref(summary, measurement_id) for summary in summaries],
        "evidence_findings": findings,
        "attention": _attention(summaries),
    }
