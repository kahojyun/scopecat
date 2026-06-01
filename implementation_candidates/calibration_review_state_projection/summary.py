"""Structured summary builder for calibration review-state projections.

This module is an experimental production-shaped boundary. It projects
declared review bundle, missing-evidence, and timeline facts into read-only
per-step review state. It does not render a GUI, execute actions, retry
measurements, rerun fitting, decide continuation, start parameter-state intake,
emit compatibility output, schedule work, roll back writes, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "projection_authority": "explicit_calibration_review_state_projection",
    "source_summary_handling": "declared_review_summaries",
    "projection_posture": "read_only_review_state",
    "available_actions": "labels_only",
    "gui": "not_defined",
    "action_execution": "not_performed",
    "child_slice_execution": "not_performed",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "fit_quality_scoring": "not_performed",
    "retry_decision": "not_performed",
    "remeasurement_decision": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_state_intake": "not_performed",
    "parameter_state_commit": "not_performed",
    "hardware_control": "not_performed",
    "scheduler": "not_defined",
}

_EVIDENCE_STATES = {
    "complete_until_parameter_state_intake",
    "missing_observation_evidence",
    "missing_fit_result_evidence",
    "fit_result_needs_review",
    "proposed_write_needs_review",
    "accepted_write_handoff_missing",
    "write_proposal_not_present",
    "write_rejected_no_handoff_needed",
}

_TIMELINE_STATES = {
    "timeline_order_review_ready",
    "timeline_order_needs_review",
    "timeline_timestamps_need_review",
    "timeline_events_incomplete",
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
    policy = source["review_state_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("review state policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"review state policy {key} must be {expected}")


def _steps_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["review_steps"], "step_record_id")


def _chains_by_step(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["review_bundle_chains"], "step_record_id")


def _completeness_by_step(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["evidence_completeness"], "step_record_id")


def _timeline_by_step(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["timeline_traces"], "step_record_id")


def _validate_steps(source: dict[str, Any]) -> None:
    _steps_by_id(source)
    for step in source["review_steps"]:
        if step["record_posture"] != "retrospective_step_record":
            raise ValueError("review steps must remain retrospective")


def _validate_summary_coverage(source: dict[str, Any]) -> None:
    step_ids = set(_steps_by_id(source))
    for label, records in [
        ("review bundle chains", _chains_by_step(source)),
        ("evidence completeness", _completeness_by_step(source)),
        ("timeline traces", _timeline_by_step(source)),
    ]:
        if set(records) != step_ids:
            raise ValueError(f"{label} must cover every review step")


def _validate_bundle_chain(source: dict[str, Any]) -> None:
    for chain in source["review_bundle_chains"]:
        if chain["bundle_posture"] != "read_only_review_chain":
            raise ValueError("review bundle chains must remain read-only")
        if chain["parameter_state_intake_state"] != "not_started":
            raise ValueError("parameter-state intake must not start in review state projection")


def _validate_evidence_completeness(source: dict[str, Any]) -> None:
    for item in source["evidence_completeness"]:
        if item["review_state"] not in _EVIDENCE_STATES:
            raise ValueError("unsupported evidence review state")
        if item["parameter_state_intake_state"] != "not_started":
            raise ValueError("parameter-state intake must not start in evidence completeness")


def _validate_timeline_traces(source: dict[str, Any]) -> None:
    for trace in source["timeline_traces"]:
        if trace["timeline_status"] not in _TIMELINE_STATES:
            raise ValueError("unsupported timeline status")
        if trace["trace_posture"] != "read_only_temporal_review":
            raise ValueError("timeline traces must remain read-only")


def _validate_findings(source: dict[str, Any]) -> None:
    steps = _steps_by_id(source)
    _records_by_key(source["review_findings"], "finding_id")
    for finding in source["review_findings"]:
        if finding["step_record_id"] not in steps:
            raise ValueError("review finding references missing step record")
        if finding["finding_posture"] != "review_only":
            raise ValueError("review findings must remain review-only")
        if finding["does_not_claim"] != "workflow_action_or_state_mutation":
            raise ValueError("review finding must not claim workflow action")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_steps(source)
    _validate_summary_coverage(source)
    _validate_bundle_chain(source)
    _validate_evidence_completeness(source)
    _validate_timeline_traces(source)
    _validate_findings(source)


def _timeline_review_state(timeline_status: str) -> str | None:
    if timeline_status == "timeline_order_review_ready":
        return None
    if timeline_status == "timeline_order_needs_review":
        return "needs_timeline_order_review"
    if timeline_status == "timeline_timestamps_need_review":
        return "needs_timeline_timestamp_review"
    return "needs_timeline_event_review"


def _evidence_review_state(evidence_state: str) -> str:
    if evidence_state == "complete_until_parameter_state_intake":
        return "handoff_ready_for_parameter_state_thread"
    if evidence_state == "missing_observation_evidence":
        return "needs_observation_evidence"
    if evidence_state == "missing_fit_result_evidence":
        return "needs_fit_result_evidence"
    if evidence_state == "fit_result_needs_review":
        return "needs_fit_review"
    if evidence_state == "proposed_write_needs_review":
        return "needs_write_review"
    if evidence_state == "accepted_write_handoff_missing":
        return "needs_handoff_review"
    if evidence_state == "write_rejected_no_handoff_needed":
        return "write_rejected_review_complete"
    return "ready_without_write_proposal"


def _overall_review_state(completeness: dict[str, Any], timeline: dict[str, Any]) -> str:
    timeline_state = _timeline_review_state(timeline["timeline_status"])
    if timeline_state is not None:
        return timeline_state
    return _evidence_review_state(completeness["review_state"])


def _available_action_labels(review_state: str) -> list[str]:
    actions_by_state = {
        "handoff_ready_for_parameter_state_thread": [
            "inspect_handoff",
            "wait_for_parameter_state_thread",
        ],
        "needs_observation_evidence": [
            "inspect_step_context",
            "find_or_link_observation",
        ],
        "needs_fit_result_evidence": [
            "inspect_observation",
            "find_or_link_fit_result",
        ],
        "needs_fit_review": [
            "inspect_fit_result",
            "record_fit_review_outcome",
        ],
        "needs_write_review": [
            "inspect_proposed_write",
            "record_write_review_outcome",
        ],
        "needs_handoff_review": [
            "inspect_accepted_write",
            "prepare_handoff_review",
        ],
        "needs_timeline_order_review": [
            "inspect_timeline",
            "review_event_order",
        ],
        "needs_timeline_timestamp_review": [
            "inspect_timeline",
            "record_missing_timestamp",
        ],
        "needs_timeline_event_review": [
            "inspect_timeline",
            "find_or_record_missing_event",
        ],
        "write_rejected_review_complete": [
            "inspect_rejected_write",
        ],
        "ready_without_write_proposal": [
            "inspect_fit_result",
            "decide_whether_write_needed",
        ],
    }
    return actions_by_state[review_state]


def _findings_for_step(source: dict[str, Any], step_record_id: str) -> list[dict[str, Any]]:
    return [
        {
            "finding_id": finding["finding_id"],
            "finding": finding["finding"],
            "source_summary": finding["source_summary"],
            "severity": finding["severity"],
        }
        for finding in source["review_findings"]
        if finding["step_record_id"] == step_record_id
    ]


def _review_card(
    source: dict[str, Any],
    step: dict[str, Any],
    chain: dict[str, Any],
    completeness: dict[str, Any],
    timeline: dict[str, Any],
) -> dict[str, Any]:
    review_state = _overall_review_state(completeness, timeline)
    return {
        "step_record_id": step["step_record_id"],
        "step_intent_id": step["step_intent_id"],
        "target": step["target"],
        "review_state": review_state,
        "state_source": "timeline" if review_state.startswith("needs_timeline_") else "evidence",
        "bundle_review_status": chain["review_status"],
        "evidence_review_state": completeness["review_state"],
        "timeline_status": timeline["timeline_status"],
        "available_review_actions": _available_action_labels(review_state),
        "action_posture": "labels_only_not_executed",
        "finding_refs": _findings_for_step(source, step["step_record_id"]),
    }


def _review_cards(source: dict[str, Any]) -> list[dict[str, Any]]:
    chains = _chains_by_step(source)
    completeness = _completeness_by_step(source)
    timeline = _timeline_by_step(source)
    return [
        _review_card(
            source,
            step,
            chains[step["step_record_id"]],
            completeness[step["step_record_id"]],
            timeline[step["step_record_id"]],
        )
        for step in source["review_steps"]
    ]


def _state_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        state = card["review_state"]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "projection_is_read_only",
            "severity": "info",
            "basis": "Review cards are projections from declared summaries.",
            "does_not_claim": "workflow_state_mutation",
        },
        {
            "code": "available_actions_are_labels_only",
            "severity": "review",
            "basis": "Available review actions are labels for a reviewer, not executable commands.",
            "does_not_claim": "action_execution",
        },
        {
            "code": "gui_not_defined",
            "severity": "review",
            "basis": "The projection is notebook/CLI-shaped data, not a GUI component model.",
            "does_not_claim": "gui_contract",
        },
        {
            "code": "continuation_decision_not_performed",
            "severity": "review",
            "basis": "Review state does not decide retry, remeasurement, skip, or continuation.",
            "does_not_claim": "calibration_workflow_decision",
        },
        {
            "code": "parameter_state_intake_not_started",
            "severity": "review",
            "basis": "Handoff-ready steps wait for the parameter-state thread.",
            "does_not_claim": "parameter_state_draft_or_commit",
        },
    ]


def build_calibration_review_state_projection_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build read-only per-step calibration review-state cards."""
    _validate_references(source)
    cards = _review_cards(source)
    return {
        "review_state_policy": copy.deepcopy(source["review_state_policy"]),
        "review_steps": copy.deepcopy(source["review_steps"]),
        "review_cards": cards,
        "state_counts": _state_counts(cards),
        "review_findings": copy.deepcopy(source["review_findings"]),
        "attention": _attention(source),
    }
