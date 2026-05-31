"""Structured summary builder for calibration missing-evidence findings.

This module is an experimental production-shaped boundary. It turns declared
calibration review facts into per-step evidence-completeness findings. It does
not rerun child slices, read measurement payloads, execute fitting, score fit
quality, decide retry, decide continuation, start parameter-state intake, emit
compatibility output, schedule work, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "finding_authority": "explicit_calibration_missing_evidence_findings",
    "source_bundle_handling": "declared_review_bundle_facts",
    "finding_posture": "review_only",
    "child_slice_execution": "not_performed",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "fit_quality_scoring": "not_performed",
    "retry_decision": "not_performed",
    "remeasurement_decision": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_state_intake": "not_performed",
    "parameter_state_commit": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "scheduler": "not_defined",
    "gui": "not_defined",
}

_FIT_STATES_REQUIRING_REVIEW = {
    "declared_failed",
    "declared_review_needed",
}

_SUPPORTED_WRITE_REVIEW_STATES = {
    "proposed_pending_review",
    "accepted_for_parameter_state_handoff",
    "rejected",
}

_SUPPORTED_HANDOFF_STATES = {
    "ready_for_parameter_state_review",
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
    policy = source["missing_evidence_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("missing evidence policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"missing evidence policy {key} must be {expected}")


def _steps_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["review_steps"], "step_record_id")


def _observations_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["observation_links"], "observation_link_id")


def _measurements_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurement_refs"], "measurement_record_id")


def _fit_results_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["fit_result_refs"], "fit_result_id")


def _proposed_writes_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["proposed_write_refs"], "write_id")


def _handoffs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["accepted_handoff_refs"], "handoff_id")


def _validate_review_steps(source: dict[str, Any]) -> None:
    _steps_by_id(source)
    for step in source["review_steps"]:
        if step["record_posture"] != "retrospective_step_record":
            raise ValueError("review steps must remain retrospective")
        if step["context_resolution_state"] not in {
            "resolved_snapshot_recorded",
            "optional_context_missing",
        }:
            raise ValueError("unsupported context resolution state")


def _validate_measurements(source: dict[str, Any]) -> None:
    _measurements_by_id(source)
    for measurement in source["measurement_refs"]:
        if measurement["payload_owner"] != "measurement_records":
            raise ValueError("measurement payload owner must remain measurement_records")


def _validate_observation_links(source: dict[str, Any]) -> None:
    steps = _steps_by_id(source)
    measurements = _measurements_by_id(source)
    _observations_by_id(source)
    for link in source["observation_links"]:
        if link["step_record_id"] not in steps:
            raise ValueError("observation link references missing step record")
        if link["measurement_record_id"] not in measurements:
            raise ValueError("observation link references missing measurement")
        if link["payload_handling"] != "reference_only":
            raise ValueError("observation links must remain reference-only")


def _validate_fit_results(source: dict[str, Any]) -> None:
    steps = _steps_by_id(source)
    observations = _observations_by_id(source)
    measurements = _measurements_by_id(source)
    _fit_results_by_id(source)
    for fit_result in source["fit_result_refs"]:
        step_record_id = fit_result["step_record_id"]
        if step_record_id not in steps:
            raise ValueError("fit result references missing step record")
        if fit_result["payload_handling"] != "summary_only":
            raise ValueError("fit result payload handling must stay summary-only")
        if fit_result["execution_posture"] != "declared_external_summary":
            raise ValueError("fit result must remain a declared external summary")
        for input_ref in fit_result["input_refs"]:
            observation = observations.get(input_ref["observation_link_id"])
            if observation is None:
                raise ValueError("fit result input references missing observation link")
            if observation["step_record_id"] != step_record_id:
                raise ValueError("fit result input belongs to a different step record")
            measurement_id = input_ref["measurement_record_id"]
            if measurement_id not in measurements:
                raise ValueError("fit result input references missing measurement")
            if observation["measurement_record_id"] != measurement_id:
                raise ValueError("fit result input measurement must match observation link")


def _validate_proposed_writes(source: dict[str, Any]) -> None:
    steps = _steps_by_id(source)
    observations = _observations_by_id(source)
    fit_results = _fit_results_by_id(source)
    _proposed_writes_by_id(source)
    for write in source["proposed_write_refs"]:
        step_record_id = write["step_record_id"]
        if step_record_id not in steps:
            raise ValueError("proposed write references missing step record")
        if write["review_state"] not in _SUPPORTED_WRITE_REVIEW_STATES:
            raise ValueError("unsupported proposed write review state")
        if write["apply_state"] != "not_applied":
            raise ValueError("proposed writes must remain not_applied")
        if write["payload_handling"] != "summary_only":
            raise ValueError("proposed write payload handling must stay summary-only")
        for observation_link_id in write["evidence"]["observation_link_ids"]:
            observation = observations.get(observation_link_id)
            if observation is None:
                raise ValueError("proposed write evidence references missing observation link")
            if observation["step_record_id"] != step_record_id:
                raise ValueError("proposed write observation evidence belongs to another step")
        for fit_result_id in write["evidence"]["fit_result_ids"]:
            fit_result = fit_results.get(fit_result_id)
            if fit_result is None:
                raise ValueError("proposed write evidence references missing fit result")
            if fit_result["step_record_id"] != step_record_id:
                raise ValueError("proposed write fit evidence belongs to another step")


def _validate_handoffs(source: dict[str, Any]) -> None:
    steps = _steps_by_id(source)
    proposed_writes = _proposed_writes_by_id(source)
    _handoffs_by_id(source)
    seen_write_ids = set()
    for handoff in source["accepted_handoff_refs"]:
        if handoff["step_record_id"] not in steps:
            raise ValueError("handoff references missing step record")
        if handoff["handoff_state"] not in _SUPPORTED_HANDOFF_STATES:
            raise ValueError("unsupported handoff state")
        if handoff["parameter_state_intake_state"] != "not_started":
            raise ValueError("parameter-state intake must not start in missing evidence findings")
        if handoff["apply_state"] != "not_applied":
            raise ValueError("handoff refs must remain not_applied")
        write_id = handoff["write_id"]
        if write_id in seen_write_ids:
            raise ValueError(f"duplicate handoff write_id: {write_id}")
        seen_write_ids.add(write_id)
        write = proposed_writes.get(write_id)
        if write is None:
            raise ValueError("handoff references missing proposed write")
        if write["step_record_id"] != handoff["step_record_id"]:
            raise ValueError("handoff write belongs to a different step record")
        if write["review_state"] != "accepted_for_parameter_state_handoff":
            raise ValueError("handoff write must be accepted for parameter-state handoff")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_review_steps(source)
    _validate_measurements(source)
    _validate_observation_links(source)
    _validate_fit_results(source)
    _validate_proposed_writes(source)
    _validate_handoffs(source)


def _items_for_step(records: list[dict[str, Any]], step_record_id: str) -> list[dict[str, Any]]:
    return [record for record in records if record["step_record_id"] == step_record_id]


def _review_state_for_step(
    observations: list[dict[str, Any]],
    fit_results: list[dict[str, Any]],
    proposed_writes: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
) -> str:
    if not observations:
        return "missing_observation_evidence"
    if not fit_results:
        return "missing_fit_result_evidence"
    if any(fit_result["fit_state"] in _FIT_STATES_REQUIRING_REVIEW for fit_result in fit_results):
        return "fit_result_needs_review"
    if any(fit_result["review_state"] != "usable_for_review" for fit_result in fit_results):
        return "fit_result_needs_review"
    if not proposed_writes:
        return "write_proposal_not_present"
    if any(write["review_state"] == "proposed_pending_review" for write in proposed_writes):
        return "proposed_write_needs_review"
    if any(
        write["review_state"] == "accepted_for_parameter_state_handoff" for write in proposed_writes
    ):
        if not handoffs:
            return "accepted_write_handoff_missing"
        return "complete_until_parameter_state_intake"
    return "write_rejected_no_handoff_needed"


def _completeness_item(source: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    step_record_id = step["step_record_id"]
    observations = _items_for_step(source["observation_links"], step_record_id)
    fit_results = _items_for_step(source["fit_result_refs"], step_record_id)
    proposed_writes = _items_for_step(source["proposed_write_refs"], step_record_id)
    handoffs = _items_for_step(source["accepted_handoff_refs"], step_record_id)
    review_state = _review_state_for_step(observations, fit_results, proposed_writes, handoffs)
    return {
        "step_record_id": step_record_id,
        "step_intent_id": step["step_intent_id"],
        "target": step["target"],
        "observation_count": len(observations),
        "fit_result_count": len(fit_results),
        "proposed_write_count": len(proposed_writes),
        "accepted_handoff_count": len(handoffs),
        "has_observation_evidence": bool(observations),
        "has_usable_fit_result": any(
            fit_result["fit_state"] == "declared_success"
            and fit_result["review_state"] == "usable_for_review"
            for fit_result in fit_results
        ),
        "has_pending_write_review": any(
            write["review_state"] == "proposed_pending_review" for write in proposed_writes
        ),
        "has_accepted_write_handoff": bool(handoffs),
        "review_state": review_state,
        "finding_required": review_state != "complete_until_parameter_state_intake",
    }


def _evidence_completeness(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [_completeness_item(source, step) for step in source["review_steps"]]


def _finding_for_item(item: dict[str, Any]) -> dict[str, str] | None:
    if not item["finding_required"]:
        return None
    return {
        "step_record_id": item["step_record_id"],
        "step_intent_id": item["step_intent_id"],
        "severity": "review",
        "finding": item["review_state"],
        "basis": "Declared calibration review facts are incomplete or require review.",
        "does_not_claim": "retry_remeasurement_continuation_or_write_back_decision",
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for item in _evidence_completeness(source):
        finding = _finding_for_item(item)
        if finding is not None:
            findings.append(finding)
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "findings_are_review_only",
            "severity": "info",
            "basis": "Missing evidence produces review findings only.",
            "does_not_claim": "workflow_block_or_automatic_action",
        },
        {
            "code": "measurement_payload_not_read",
            "severity": "review",
            "basis": "Observation links and measurement refs are inspected as references only.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "Fit-result states are declared facts and are not recomputed.",
            "does_not_claim": "fit_execution_or_quality_scoring",
        },
        {
            "code": "retry_remeasurement_not_decided",
            "severity": "review",
            "basis": "Missing observation or failed fit findings do not schedule a retry or remeasurement.",
            "does_not_claim": "retry_or_remeasurement_decision",
        },
        {
            "code": "continuation_decision_not_performed",
            "severity": "review",
            "basis": "Evidence completeness is not a continuation gate.",
            "does_not_claim": "calibration_continuation_decision",
        },
        {
            "code": "parameter_state_intake_not_started",
            "severity": "review",
            "basis": "Accepted handoff status remains visible, but intake belongs to the parameter-state route.",
            "does_not_claim": "parameter_state_draft_or_commit",
        },
    ]


def build_calibration_missing_evidence_findings_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build review-only missing-evidence findings from declared review facts."""
    _validate_references(source)
    return {
        "missing_evidence_policy": copy.deepcopy(source["missing_evidence_policy"]),
        "review_steps": copy.deepcopy(source["review_steps"]),
        "measurement_refs": copy.deepcopy(source["measurement_refs"]),
        "observation_links": copy.deepcopy(source["observation_links"]),
        "fit_result_refs": copy.deepcopy(source["fit_result_refs"]),
        "proposed_write_refs": copy.deepcopy(source["proposed_write_refs"]),
        "accepted_handoff_refs": copy.deepcopy(source["accepted_handoff_refs"]),
        "evidence_completeness": _evidence_completeness(source),
        "review_findings": _review_findings(source),
        "attention": _attention(source),
    }
