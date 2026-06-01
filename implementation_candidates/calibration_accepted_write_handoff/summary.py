"""Structured summary builder for accepted calibration write handoff.

This module is an experimental production-shaped boundary. It prepares accepted
calibration proposed writes as parameter-state route handoff requests only. It
does not create drafts, commit parameter states, write compatibility outputs,
apply hardware writes, perform rollback, read measurement payloads, execute
fitting, schedule work, or define a shared parameter schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "handoff_authority": "explicit_accepted_calibration_write_handoff",
    "source_write_review": "accepted_for_parameter_state_handoff_only",
    "parameter_state_authority": "parameter_state_management_route",
    "handoff_payload": "summary_only",
    "parameter_state_draft_write": "not_performed",
    "parameter_state_commit": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "rollback": "not_defined",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "scheduler": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_REQUEST_STATES = {
    "ready_for_parameter_state_review",
    "blocked_missing_base_entry",
}

_DIFF_KINDS = {
    "changed",
    "added",
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
    policy = source["handoff_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("handoff policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"handoff policy {key} must be {expected}")


def _step_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_step_records"], "step_record_id")


def _base_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_state_base_contexts"], "context_id")


def _accepted_writes_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["accepted_proposed_writes"], "write_id")


def _handoff_requests_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["handoff_requests"], "handoff_id")


def _state_entries_by_path(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(context["entries"], "path")


def _validate_step_records(source: dict[str, Any]) -> None:
    base_contexts = _base_contexts_by_id(source)
    _step_records_by_id(source)
    for record in source["calibration_step_records"]:
        for link in record["actual_context_links"]:
            if link["link_semantics"] != "resolved_snapshot_used_at_step_start":
                raise ValueError("step context links must remain resolved snapshots")
            if link["family"] == "parameter_state" and link["context_id"] not in base_contexts:
                raise ValueError("parameter context link must reference a known base context")
        for ref in record["observation_link_refs"]:
            if ref["payload_handling"] != "reference_only":
                raise ValueError("observation link refs must remain reference-only")


def _validate_base_contexts(source: dict[str, Any]) -> None:
    _base_contexts_by_id(source)
    for context in source["parameter_state_base_contexts"]:
        if context["family"] != "parameter_state":
            raise ValueError("base context must use parameter_state family")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("base context payloads must stay family-owned summaries")
        if not context["state_id"]:
            raise ValueError("base context requires state_id")
        if not context["lineage_id"]:
            raise ValueError("base context requires lineage_id")
        _state_entries_by_path(context)


def _record_has_parameter_context(record: dict[str, Any], context_id: str) -> bool:
    return any(
        link["family"] == "parameter_state" and link["context_id"] == context_id
        for link in record["actual_context_links"]
    )


def _validate_accepted_write(
    write: dict[str, Any],
    step_records: dict[str, dict[str, Any]],
    base_contexts: dict[str, dict[str, Any]],
) -> None:
    if write["review_state"] != "accepted_for_parameter_state_handoff":
        raise ValueError("write review_state must be accepted_for_parameter_state_handoff")
    if write["apply_state"] != "not_applied":
        raise ValueError("accepted handoff writes must remain not_applied")
    if write["payload_handling"] != "summary_only":
        raise ValueError("accepted write payload handling must stay summary-only")
    if write["target_parameter"]["family"] != "parameter_state":
        raise ValueError("accepted write target must be parameter_state")

    step_record_id = write["step_record_id"]
    if step_record_id not in step_records:
        raise ValueError("accepted write references missing step record")

    before = write["before_summary"]
    if before["context_id"] not in base_contexts:
        raise ValueError("before_summary context must reference a known base context")
    base_context = base_contexts[before["context_id"]]
    if before["state_id"] != base_context["state_id"]:
        raise ValueError("before_summary state_id must match base context")
    if not _record_has_parameter_context(step_records[step_record_id], before["context_id"]):
        raise ValueError("before_summary context must be linked by the step record")

    target = write["target_parameter"]
    after = write["after_summary"]
    if target["lineage_id"] != base_context["lineage_id"]:
        raise ValueError("target lineage must match base context lineage")
    if before["parameter_path"] != target["parameter_path"]:
        raise ValueError("before_summary parameter path must match target parameter path")
    if after["lineage_id"] != target["lineage_id"]:
        raise ValueError("after_summary lineage must match target lineage")
    if after["parameter_path"] != target["parameter_path"]:
        raise ValueError("after_summary parameter path must match target parameter path")
    if before["unit"] != after["unit"] or target["unit"] != after["unit"]:
        raise ValueError("before, target, and after units must match")
    if after.get("committed_context_id") is not None:
        raise ValueError("handoff write must not claim a committed context")

    base_entries = _state_entries_by_path(base_context)
    base_entry = base_entries.get(target["parameter_path"])
    if base_entry is None:
        raise ValueError("accepted write target path must exist in base context")
    if base_entry["value"] != before["value"]:
        raise ValueError("before_summary value must match base context entry")
    if base_entry["unit"] != before["unit"]:
        raise ValueError("before_summary unit must match base context entry")


def _validate_accepted_writes(source: dict[str, Any]) -> None:
    step_records = _step_records_by_id(source)
    base_contexts = _base_contexts_by_id(source)
    _accepted_writes_by_id(source)
    for write in source["accepted_proposed_writes"]:
        _validate_accepted_write(write, step_records, base_contexts)


def _validate_handoff_request(
    request: dict[str, Any],
    accepted_writes: dict[str, dict[str, Any]],
) -> None:
    if request["target_route"] != "parameter_state_management":
        raise ValueError("handoff target route must be parameter_state_management")
    if request["request_state"] not in _REQUEST_STATES:
        raise ValueError("unsupported handoff request state")
    if request["payload_handling"] != "summary_only":
        raise ValueError("handoff request payload handling must stay summary-only")

    write_id = request["write_id"]
    if write_id not in accepted_writes:
        raise ValueError("handoff request references missing accepted write")
    write = accepted_writes[write_id]

    draft = request["draft_request"]
    if draft["lineage_id"] != write["target_parameter"]["lineage_id"]:
        raise ValueError("draft request lineage must match accepted write")
    if draft["base_state_id"] != write["before_summary"]["state_id"]:
        raise ValueError("draft request base state must match accepted write")
    if draft["durable_history"]:
        raise ValueError("handoff draft request must not create durable history")

    review = request["reviewable_diff_request"]
    if review["draft_id"] != draft["draft_id"]:
        raise ValueError("reviewable diff request must reference draft request")
    if review["base_state_id"] != draft["base_state_id"]:
        raise ValueError("reviewable diff base state must match draft request")
    if review["creates_durable_history"] != "parameter_state_route_decides":
        raise ValueError("handoff must leave durable history to parameter state route")

    entries = review["diff_entries"]
    if len(entries) != 1:
        raise ValueError("handoff request must carry exactly one diff entry")
    entry = entries[0]
    if entry["kind"] not in _DIFF_KINDS:
        raise ValueError("unsupported handoff diff kind")
    if entry["path"] != write["target_parameter"]["parameter_path"]:
        raise ValueError("handoff diff path must match accepted write")
    if entry["old_value"] != write["before_summary"]["value"]:
        raise ValueError("handoff diff old value must match accepted write")
    if entry["new_value"] != write["after_summary"]["candidate_value"]:
        raise ValueError("handoff diff new value must match accepted write")
    if entry["unit"] != write["target_parameter"]["unit"]:
        raise ValueError("handoff diff unit must match accepted write")


def _validate_handoff_requests(source: dict[str, Any]) -> None:
    accepted_writes = _accepted_writes_by_id(source)
    _handoff_requests_by_id(source)
    seen_write_ids = set()
    for request in source["handoff_requests"]:
        write_id = request["write_id"]
        if write_id in seen_write_ids:
            raise ValueError(f"duplicate handoff write_id: {write_id}")
        seen_write_ids.add(write_id)
        _validate_handoff_request(request, accepted_writes)

    missing_write_ids = set(accepted_writes) - seen_write_ids
    if missing_write_ids:
        raise ValueError("every accepted write must have a handoff request")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_base_contexts(source)
    _validate_step_records(source)
    _validate_accepted_writes(source)
    _validate_handoff_requests(source)


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


def _base_context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "state_id": context["state_id"],
        "lineage_id": context["lineage_id"],
        "label": context["label"],
        "record_status": context["record_status"],
        "payload_handling": context["payload_handling"],
        "entry_count": len(context["entries"]),
    }


def _accepted_write_summary(write: dict[str, Any]) -> dict[str, Any]:
    return {
        "write_id": write["write_id"],
        "step_record_id": write["step_record_id"],
        "target_parameter": copy.deepcopy(write["target_parameter"]),
        "before_summary": copy.deepcopy(write["before_summary"]),
        "after_summary": copy.deepcopy(write["after_summary"]),
        "acceptance": copy.deepcopy(write["acceptance"]),
        "review_state": write["review_state"],
        "apply_state": write["apply_state"],
        "payload_handling": write["payload_handling"],
        "handoff_posture": "accepted_for_parameter_state_review_without_apply",
        "does_not_claim": "parameter_state_commit_or_hardware_apply",
    }


def _handoff_request_summary(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "handoff_id": request["handoff_id"],
        "write_id": request["write_id"],
        "target_route": request["target_route"],
        "request_state": request["request_state"],
        "payload_handling": request["payload_handling"],
        "draft_request": copy.deepcopy(request["draft_request"]),
        "reviewable_diff_request": copy.deepcopy(request["reviewable_diff_request"]),
        "route_input_posture": "parameter_state_management_review_request",
        "does_not_claim": "draft_created_or_committed_state",
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for request in source["handoff_requests"]:
        if request["request_state"] == "ready_for_parameter_state_review":
            continue
        findings.append(
            {
                "handoff_id": request["handoff_id"],
                "write_id": request["write_id"],
                "severity": "review",
                "finding": request["request_state"],
                "basis": "The accepted write cannot yet be shaped as a parameter-state review request.",
                "does_not_claim": "calibration_write_invalid_or_applied",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "accepted_write_is_handoff_only",
            "severity": "info",
            "basis": "Calibration acceptance prepares a parameter-state route request.",
            "does_not_claim": "parameter_state_commit",
        },
        {
            "code": "parameter_state_route_owns_durable_history",
            "severity": "info",
            "basis": "Draft and review ids are projected as requested route inputs only.",
            "does_not_claim": "draft_created_or_review_accepted",
        },
        {
            "code": "apply_state_not_applied",
            "severity": "review",
            "basis": "Accepted handoff writes still carry not_applied apply state.",
            "does_not_claim": "hardware_apply_or_parameter_store_write",
        },
        {
            "code": "compatibility_output_not_produced",
            "severity": "review",
            "basis": "Compatibility output planning remains a later parameter-state route concern.",
            "does_not_claim": "external_parameter_file",
        },
        {
            "code": "rollback_not_defined",
            "severity": "review",
            "basis": "No write is applied or committed by this handoff slice.",
            "does_not_claim": "rollback_contract",
        },
    ]


def build_calibration_accepted_write_handoff_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build an accepted calibration write handoff summary from explicit facts."""
    _validate_references(source)
    return {
        "handoff_policy": copy.deepcopy(source["handoff_policy"]),
        "calibration_step_records": [
            _step_record_summary(record) for record in source["calibration_step_records"]
        ],
        "parameter_state_base_contexts": [
            _base_context_summary(context) for context in source["parameter_state_base_contexts"]
        ],
        "accepted_proposed_writes": [
            _accepted_write_summary(write) for write in source["accepted_proposed_writes"]
        ],
        "handoff_requests": [
            _handoff_request_summary(request) for request in source["handoff_requests"]
        ],
        "review_findings": _review_findings(source),
        "attention": _attention(source),
    }
