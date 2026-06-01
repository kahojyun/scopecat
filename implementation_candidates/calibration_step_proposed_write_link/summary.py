"""Structured summary builder for calibration step proposed-write links.

This module is an experimental production-shaped boundary. It deliberately
links calibration step records to reviewable proposed parameter writes only.
It does not read measurement payloads, execute fitting, apply writes, emit
compatibility output, roll back parameter state, schedule work, or control
hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "proposal_authority": "explicit_calibration_step_proposed_writes",
    "step_record_context": "reference_only_resolved_snapshots",
    "proposed_write_state": "review_only",
    "parameter_state_lineage_reference": "summary_only",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_store_write": "not_performed",
    "hardware_control": "not_performed",
    "rollback": "not_defined",
    "external_compatibility_output": "not_produced",
    "scheduler": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_REVIEW_STATES = {
    "proposed_pending_review",
    "accepted_for_external_apply",
    "rejected",
}

_PROPOSAL_KINDS = {
    "scalar_parameter_update",
    "parameter_state_entry_update",
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
    policy = source["write_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("write review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"write review policy {key} must be {expected}")


def _step_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_step_records"], "step_record_id")


def _parameter_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_state_contexts"], "context_id")


def _proposed_writes_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["proposed_writes"], "write_id")


def _validate_step_records(source: dict[str, Any]) -> None:
    parameter_contexts = _parameter_contexts_by_id(source)
    _step_records_by_id(source)
    for record in source["calibration_step_records"]:
        for link in record["actual_context_links"]:
            if link["link_semantics"] != "resolved_snapshot_used_at_step_start":
                raise ValueError("step context links must remain resolved snapshots")
            if link["family"] != "parameter_state":
                continue
            if link["context_id"] not in parameter_contexts:
                raise ValueError("parameter context link must reference a known context")
        for ref in record["observation_link_refs"]:
            if ref["payload_handling"] != "reference_only":
                raise ValueError("observation link refs must remain reference-only")


def _validate_parameter_contexts(source: dict[str, Any]) -> None:
    _parameter_contexts_by_id(source)
    for context in source["parameter_state_contexts"]:
        if context["family"] != "parameter_state":
            raise ValueError("parameter contexts must use the parameter_state family")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("parameter context payloads must stay family-owned summaries")
        if not context["declared_summary"].get("lineage_id"):
            raise ValueError("parameter context summary requires lineage_id")


def _record_has_parameter_link(
    step_record: dict[str, Any],
    context_id: str,
) -> bool:
    return any(
        link["family"] == "parameter_state" and link["context_id"] == context_id
        for link in step_record["actual_context_links"]
    )


def _validate_proposed_write(
    write: dict[str, Any],
    step_records: dict[str, dict[str, Any]],
    parameter_contexts: dict[str, dict[str, Any]],
) -> None:
    if write["proposal_kind"] not in _PROPOSAL_KINDS:
        raise ValueError("unsupported proposed write kind")
    if write["review_state"] not in _REVIEW_STATES:
        raise ValueError("unsupported review state")
    if write["apply_state"] != "not_applied":
        raise ValueError("proposed writes must remain not_applied")
    if write["payload_handling"] != "summary_only":
        raise ValueError("proposed write payload handling must stay summary-only")

    step_record_id = write["step_record_id"]
    if step_record_id not in step_records:
        raise ValueError("proposed write references missing step record")

    target = write["target_parameter"]
    if target["family"] != "parameter_state":
        raise ValueError("proposed write target must be parameter_state")
    if not target["parameter_path"]:
        raise ValueError("proposed write target requires parameter_path")

    before = write["before_summary"]
    if before["context_id"] not in parameter_contexts:
        raise ValueError("before_summary context must reference a known parameter context")
    before_context = parameter_contexts[before["context_id"]]
    before_lineage = before_context["declared_summary"]["lineage_id"]
    if target["lineage_id"] != before_lineage:
        raise ValueError("target lineage must match before context lineage")
    if not _record_has_parameter_link(step_records[step_record_id], before["context_id"]):
        raise ValueError("before_summary context must be linked by the step record")
    if before["parameter_path"] != target["parameter_path"]:
        raise ValueError("before_summary parameter path must match target parameter path")

    after = write["after_summary"]
    if after["lineage_id"] != target["lineage_id"]:
        raise ValueError("after_summary lineage must match target lineage")
    if after["parameter_path"] != target["parameter_path"]:
        raise ValueError("after_summary parameter path must match target parameter path")
    if after.get("committed_context_id") is not None:
        raise ValueError("after_summary must not claim a committed context")


def _validate_proposed_writes(source: dict[str, Any]) -> None:
    step_records = _step_records_by_id(source)
    parameter_contexts = _parameter_contexts_by_id(source)
    _proposed_writes_by_id(source)
    for write in source["proposed_writes"]:
        _validate_proposed_write(write, step_records, parameter_contexts)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_parameter_contexts(source)
    _validate_step_records(source)
    _validate_proposed_writes(source)


def _parameter_context_projection(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "label": context["label"],
        "record_status": context["record_status"],
        "authority": context["authority"],
        "lineage_id": context["declared_summary"]["lineage_id"],
        "trusted_entry_count": context["declared_summary"]["trusted_entry_count"],
        "payload_handling": context["payload_handling"],
    }


def _step_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_record_id": record["step_record_id"],
        "step_intent_id": record["step_intent_id"],
        "label": record["label"],
        "target": record["target"],
        "record_state": record["record_state"],
        "actual_context_links": copy.deepcopy(record["actual_context_links"]),
        "observation_link_refs": copy.deepcopy(record["observation_link_refs"]),
        "record_posture": "retrospective_step_record",
    }


def _proposal_review_posture(write: dict[str, Any]) -> str:
    if write["review_state"] == "accepted_for_external_apply":
        return "accepted_but_not_applied_by_this_slice"
    if write["review_state"] == "rejected":
        return "rejected_without_apply"
    return "pending_review_without_apply"


def _proposed_write_summary(
    write: dict[str, Any],
    parameter_contexts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    before_context = parameter_contexts[write["before_summary"]["context_id"]]
    return {
        "write_id": write["write_id"],
        "step_record_id": write["step_record_id"],
        "proposal_kind": write["proposal_kind"],
        "target_parameter": copy.deepcopy(write["target_parameter"]),
        "basis": copy.deepcopy(write["basis"]),
        "before_summary": {
            "context_id": write["before_summary"]["context_id"],
            "context_label": before_context["label"],
            "lineage_id": before_context["declared_summary"]["lineage_id"],
            "parameter_path": write["before_summary"]["parameter_path"],
            "value_summary": write["before_summary"]["value_summary"],
        },
        "after_summary": copy.deepcopy(write["after_summary"]),
        "review_state": write["review_state"],
        "apply_state": write["apply_state"],
        "payload_handling": write["payload_handling"],
        "proposal_posture": _proposal_review_posture(write),
        "does_not_claim": "parameter_store_write_or_hardware_apply",
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for write in source["proposed_writes"]:
        if write["review_state"] == "proposed_pending_review":
            findings.append(
                {
                    "write_id": write["write_id"],
                    "step_record_id": write["step_record_id"],
                    "severity": "review",
                    "finding": "proposed_write_needs_review",
                    "basis": "The proposed parameter change is linked to a step record but has not been accepted or rejected.",
                    "does_not_claim": "blocked_continuation_or_write_back",
                }
            )
        elif write["review_state"] == "accepted_for_external_apply":
            findings.append(
                {
                    "write_id": write["write_id"],
                    "step_record_id": write["step_record_id"],
                    "severity": "info",
                    "finding": "write_accepted_for_external_apply_only",
                    "basis": "Review accepted the proposal, but this slice still records no apply result.",
                    "does_not_claim": "parameter_store_write",
                }
            )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "proposed_writes_are_review_only",
            "severity": "info",
            "basis": "Step records can link candidate parameter changes for human review.",
            "does_not_claim": "automatic_parameter_update",
        },
        {
            "code": "apply_state_not_applied",
            "severity": "review",
            "basis": "Every proposed write must remain not_applied in this candidate.",
            "does_not_claim": "parameter_store_write_or_hardware_apply",
        },
        {
            "code": "parameter_lineage_is_summary_only",
            "severity": "info",
            "basis": "Lineage and parameter path are copied as summary facts from explicit fixture records.",
            "does_not_claim": "shared_parameter_schema_or_store_authority",
        },
        {
            "code": "measurement_payload_not_read",
            "severity": "review",
            "basis": "Observation links may explain proposal basis but are not opened or interpreted.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "The proposed write may reference declared fit evidence, but this candidate runs no fit.",
            "does_not_claim": "fit_result_or_quality_score",
        },
        {
            "code": "compatibility_output_not_produced",
            "severity": "review",
            "basis": "No external parameter file or compatibility output is emitted.",
            "does_not_claim": "external_json_or_parameter_store_output",
        },
        {
            "code": "rollback_not_defined",
            "severity": "review",
            "basis": "No write is applied, so rollback semantics are not defined here.",
            "does_not_claim": "rollback_contract",
        },
    ]


def build_calibration_step_proposed_write_link_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a review-only proposed-write summary from explicit facts."""
    _validate_references(source)
    parameter_contexts = _parameter_contexts_by_id(source)
    return {
        "write_review_policy": copy.deepcopy(source["write_review_policy"]),
        "calibration_step_records": [
            _step_record_summary(record) for record in source["calibration_step_records"]
        ],
        "parameter_state_contexts": [
            _parameter_context_projection(context) for context in source["parameter_state_contexts"]
        ],
        "proposed_writes": [
            _proposed_write_summary(write, parameter_contexts)
            for write in source["proposed_writes"]
        ],
        "review_findings": _review_findings(source),
        "attention": _attention(source),
    }
