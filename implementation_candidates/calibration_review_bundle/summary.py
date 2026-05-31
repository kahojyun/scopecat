"""Structured summary builder for calibration review bundles.

This module is an experimental production-shaped boundary. It assembles
declared child-summary facts into one read-only review chain. It does not rerun
child validations, read measurement payloads, execute fitting, decide
continuation, create parameter-state intake, commit parameter states, emit
compatibility output, schedule work, roll back writes, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "bundle_authority": "explicit_calibration_review_bundle",
    "child_summary_handling": "declared_summary_inputs",
    "bundle_posture": "read_only_review",
    "child_slice_execution": "not_performed",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "fit_quality_scoring": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_state_intake": "not_performed",
    "parameter_state_commit": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "rollback": "not_defined",
    "scheduler": "not_defined",
    "gui": "not_defined",
}

_CHILD_TYPES = {
    "step_intent_resolution",
    "step_observation_link",
    "step_fit_result_link",
    "step_proposed_write_link",
    "accepted_write_handoff",
}

_REQUIRED_CHILD_TYPES = set(_CHILD_TYPES)


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["review_bundle_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("review bundle policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"review bundle policy {key} must be {expected}")


def _child_summaries_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["child_summaries"], "summary_id")


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


def _handoffs_by_write_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["accepted_handoff_refs"], "write_id")


def _validate_child_summaries(source: dict[str, Any]) -> None:
    _child_summaries_by_id(source)
    child_types = set()
    for summary in source["child_summaries"]:
        child_type = summary["child_type"]
        if child_type not in _CHILD_TYPES:
            raise ValueError(f"unsupported child summary type: {child_type}")
        if summary["input_posture"] != "declared_child_summary":
            raise ValueError("child summaries must be declared child-summary inputs")
        if summary["execution_posture"] != "not_rerun_by_bundle":
            raise ValueError("bundle must not rerun child summary execution")
        child_types.add(child_type)
    missing = _REQUIRED_CHILD_TYPES - child_types
    if missing:
        raise ValueError("review bundle requires every child summary type")


def _validate_review_steps(source: dict[str, Any]) -> None:
    _steps_by_id(source)
    for step in source["review_steps"]:
        if step["context_resolution_state"] != "resolved_snapshot_recorded":
            raise ValueError("review step must carry resolved snapshot context")
        if step["record_posture"] != "retrospective_step_record":
            raise ValueError("review step must remain retrospective")


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
    _handoffs_by_write_id(source)
    for handoff in source["accepted_handoff_refs"]:
        if handoff["step_record_id"] not in steps:
            raise ValueError("handoff references missing step record")
        write = proposed_writes.get(handoff["write_id"])
        if write is None:
            raise ValueError("handoff references missing proposed write")
        if write["step_record_id"] != handoff["step_record_id"]:
            raise ValueError("handoff write belongs to a different step record")
        if write["review_state"] != "accepted_for_parameter_state_handoff":
            raise ValueError("handoff write must be accepted for parameter-state handoff")
        if handoff["handoff_state"] != "ready_for_parameter_state_review":
            raise ValueError("unsupported handoff state")
        if handoff["parameter_state_intake_state"] != "not_started":
            raise ValueError("parameter-state intake must not start in review bundle")
        if handoff["apply_state"] != "not_applied":
            raise ValueError("handoff refs must remain not_applied")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_child_summaries(source)
    _validate_review_steps(source)
    _validate_observation_links(source)
    _validate_fit_results(source)
    _validate_proposed_writes(source)
    _validate_handoffs(source)


def _step_review_status(
    step: dict[str, Any],
    observations: list[dict[str, Any]],
    fit_results: list[dict[str, Any]],
    proposed_writes: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
) -> str:
    if not observations:
        return "needs_observation_evidence"
    if not fit_results:
        return "needs_fit_result_evidence"
    if any(fit_result["review_state"] != "usable_for_review" for fit_result in fit_results):
        return "needs_fit_review"
    if not proposed_writes:
        return "ready_without_write_proposal"
    if any(write["review_state"] == "proposed_pending_review" for write in proposed_writes):
        return "needs_write_review"
    if handoffs:
        return "handoff_ready_without_parameter_state_intake"
    return "write_reviewed_without_handoff"


def _chain_item(
    step: dict[str, Any],
    observations: list[dict[str, Any]],
    fit_results: list[dict[str, Any]],
    proposed_writes: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "step_record_id": step["step_record_id"],
        "step_intent_id": step["step_intent_id"],
        "target": step["target"],
        "context_resolution_state": step["context_resolution_state"],
        "observation_link_ids": [item["observation_link_id"] for item in observations],
        "fit_result_ids": [item["fit_result_id"] for item in fit_results],
        "proposed_write_ids": [item["write_id"] for item in proposed_writes],
        "accepted_handoff_ids": [item["handoff_id"] for item in handoffs],
        "review_status": _step_review_status(
            step, observations, fit_results, proposed_writes, handoffs
        ),
        "bundle_posture": "read_only_review_chain",
    }


def _review_chain(source: dict[str, Any]) -> list[dict[str, Any]]:
    chains = []
    for step in source["review_steps"]:
        step_record_id = step["step_record_id"]
        observations = [
            item for item in source["observation_links"] if item["step_record_id"] == step_record_id
        ]
        fit_results = [
            item for item in source["fit_result_refs"] if item["step_record_id"] == step_record_id
        ]
        proposed_writes = [
            item
            for item in source["proposed_write_refs"]
            if item["step_record_id"] == step_record_id
        ]
        handoffs = [
            item
            for item in source["accepted_handoff_refs"]
            if item["step_record_id"] == step_record_id
        ]
        chains.append(_chain_item(step, observations, fit_results, proposed_writes, handoffs))
    return chains


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for item in _review_chain(source):
        if item["review_status"] == "handoff_ready_without_parameter_state_intake":
            continue
        findings.append(
            {
                "step_record_id": item["step_record_id"],
                "severity": "review",
                "finding": item["review_status"],
                "basis": "The declared child summaries do not yet form a complete review chain.",
                "does_not_claim": "workflow_block_or_automatic_action",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "bundle_is_read_only",
            "severity": "info",
            "basis": "The bundle assembles declared child-summary facts for review.",
            "does_not_claim": "workflow_state_mutation",
        },
        {
            "code": "child_slices_not_rerun",
            "severity": "info",
            "basis": "Child summaries are treated as declared inputs.",
            "does_not_claim": "child_contract_revalidation",
        },
        {
            "code": "measurement_payload_not_read",
            "severity": "review",
            "basis": "Observation and fit inputs are references only.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "Fit results are declared summaries.",
            "does_not_claim": "fit_execution_or_quality_scoring",
        },
        {
            "code": "parameter_state_intake_not_started",
            "severity": "review",
            "basis": "Accepted handoff remains visible, but parameter-state intake is outside this bundle.",
            "does_not_claim": "parameter_state_draft_or_commit",
        },
        {
            "code": "continuation_decision_not_performed",
            "severity": "review",
            "basis": "Review status is not a scheduler, retry, remeasurement, or continuation decision.",
            "does_not_claim": "calibration_workflow_decision",
        },
    ]


def build_calibration_review_bundle_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only calibration review bundle from declared child summaries."""
    _validate_references(source)
    return {
        "review_bundle_policy": copy.deepcopy(source["review_bundle_policy"]),
        "child_summaries": copy.deepcopy(source["child_summaries"]),
        "review_steps": copy.deepcopy(source["review_steps"]),
        "measurement_refs": copy.deepcopy(source["measurement_refs"]),
        "observation_links": copy.deepcopy(source["observation_links"]),
        "fit_result_refs": copy.deepcopy(source["fit_result_refs"]),
        "proposed_write_refs": copy.deepcopy(source["proposed_write_refs"]),
        "accepted_handoff_refs": copy.deepcopy(source["accepted_handoff_refs"]),
        "review_chain": _review_chain(source),
        "review_findings": _review_findings(source),
        "attention": _attention(source),
    }
