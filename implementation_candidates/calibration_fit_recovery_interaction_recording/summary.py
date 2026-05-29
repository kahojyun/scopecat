"""Interaction recording for calibration fit recovery.

This module is an experimental production-shaped boundary. It applies explicit
fixture-declared user interaction events to a fit recovery workflow input, then
delegates to the existing side-effect-free workflow and review-state builders.
It does not render a GUI, execute fitting code, score results, choose recovery
actions, replay cases, create dataset registry entries, apply writes, or
control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.calibration_fit_recovery_review_state import (
    build_fit_recovery_review_state_summary,
)
from implementation_candidates.calibration_fit_recovery_workflow import (
    build_fit_recovery_workflow_summary,
)

EVENT_TYPES = {
    "classify_signal",
    "choose_recovery_action",
    "record_review_context",
    "select_validation_case",
    "select_review_incident",
}
SIGNAL_CLASSIFICATIONS = {
    "ambiguous_signal",
    "no_clear_signal",
    "visible_signal",
}
REVIEW_SURFACE_KIND = "local_review_state"


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _ordered_events(source: dict[str, Any]) -> list[dict[str, Any]]:
    events = sorted(source["interaction_events"], key=lambda event: event["order"])
    seen_orders = set()
    seen_ids = set()
    for event in events:
        event_id = event["event_id"]
        if event_id in seen_ids:
            raise ValueError(f"duplicate event_id: {event_id}")
        seen_ids.add(event_id)
        order = event["order"]
        if order in seen_orders:
            raise ValueError(f"duplicate event order: {order}")
        seen_orders.add(order)
        event_type = event["event_type"]
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported interaction event type: {event_type}")
    return events


def _incident_for_event(
    incidents: dict[str, dict[str, Any]],
    event: dict[str, Any],
) -> dict[str, Any]:
    incident_id = event.get("incident_id")
    if not incident_id:
        raise ValueError(f"interaction event missing incident_id: {event['event_id']}")
    if incident_id not in incidents:
        raise ValueError(f"interaction event references missing incident: {incident_id}")
    return incidents[incident_id]


def _append_label(incident: dict[str, Any], label: str) -> None:
    labels = incident.setdefault("labels", [])
    if label not in labels:
        labels.append(label)


def _apply_classify_signal(incident: dict[str, Any], event: dict[str, Any]) -> None:
    classification = event["classification"]
    if classification not in SIGNAL_CLASSIFICATIONS:
        raise ValueError(f"unsupported signal classification: {classification}")
    incident["signal_assessment"] = {
        "classification": classification,
        "evidence": list(event.get("evidence", [])),
        "source": event["authority"],
    }
    _append_label(incident, classification)


def _apply_recovery_action(incident: dict[str, Any], event: dict[str, Any]) -> None:
    action = event["action"]
    if action not in incident["recovery"]["available_actions"]:
        raise ValueError(f"interaction action is not available: {action}")
    incident["recovery"]["chosen_action"] = action
    incident["recovery"]["authority"] = event["authority"]


def _apply_review_context(incident: dict[str, Any], event: dict[str, Any]) -> None:
    if "review_note_ref" in event:
        incident["review_note_ref"] = event["review_note_ref"]
    if "expected_replay_behavior" in event:
        incident["expected_replay_behavior"] = event["expected_replay_behavior"]


def _apply_dataset_selection(incident: dict[str, Any], event: dict[str, Any]) -> None:
    selected = event["selected"]
    if selected and incident["signal_assessment"]["classification"] == "no_clear_signal":
        raise ValueError("no-signal interaction cannot select validation case")
    selection = {
        "selected": selected,
        "reason": event["reason"],
    }
    if selected:
        selection["selected_attempt_ids"] = list(event.get("selected_attempt_ids", []))
        _append_label(incident, "selected_for_validation_dataset")
    incident["dataset_selection"] = selection


def _apply_event(
    workflow_input: dict[str, Any],
    review_surface: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    incidents = _records_by_key(workflow_input["fit_recovery_incidents"], "incident_id")
    event_type = event["event_type"]
    incident_id = event.get("incident_id")
    if event_type == "select_review_incident":
        if incident_id not in incidents:
            raise ValueError(f"interaction event references missing incident: {incident_id}")
        review_surface["selected_incident_id"] = incident_id
    else:
        incident = _incident_for_event(incidents, event)
        if event_type == "classify_signal":
            _apply_classify_signal(incident, event)
        elif event_type == "choose_recovery_action":
            _apply_recovery_action(incident, event)
        elif event_type == "record_review_context":
            _apply_review_context(incident, event)
        elif event_type == "select_validation_case":
            _apply_dataset_selection(incident, event)
        else:
            raise ValueError(f"unsupported interaction event type: {event_type}")
    return {
        "event_id": event["event_id"],
        "order": event["order"],
        "event_type": event_type,
        "incident_id": incident_id,
        "authority": event["authority"],
    }


def _validate_source(source: dict[str, Any]) -> None:
    surface = source["review_surface"]
    if surface.get("surface_kind") != REVIEW_SURFACE_KIND:
        raise ValueError(f"unsupported review surface kind: {surface.get('surface_kind')}")
    _records_by_key(source["workflow_input_before"]["fit_recovery_incidents"], "incident_id")
    _ordered_events(source)


def _validate_final_interaction_state(workflow_input: dict[str, Any]) -> None:
    for incident in workflow_input["fit_recovery_incidents"]:
        classification = incident["signal_assessment"]["classification"]
        if classification not in SIGNAL_CLASSIFICATIONS:
            raise ValueError(f"unsupported signal classification: {classification}")
        if classification == "no_clear_signal" and incident["dataset_selection"]["selected"]:
            raise ValueError("no-signal final state cannot select validation case")


def _by_incident(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return _records_by_key(records, "incident_id")


def _interaction_outcomes(
    workflow: dict[str, Any],
    review: dict[str, Any],
) -> list[dict[str, Any]]:
    recovery = _by_incident(workflow["immediate_recovery"])
    continuation = _by_incident(workflow["continuation_readiness"])
    offers = _by_incident(workflow["dataset_selection_offers"])
    cards = _by_incident(review["incident_cards"])
    controls = _by_incident(review["dataset_selection_controls"])
    outcomes = []
    for incident_id, item in sorted(recovery.items(), key=lambda pair: pair[1]["order"]):
        outcomes.append(
            {
                "incident_id": incident_id,
                "signal_classification": item["signal_classification"],
                "chosen_action": item["chosen_action"],
                "continuation_status": continuation[incident_id]["status"],
                "can_continue": continuation[incident_id]["can_continue"],
                "dataset_offer_state": offers[incident_id]["state"],
                "dataset_control_enabled": controls[incident_id]["enabled"],
                "dataset_control_selected": controls[incident_id]["selected"],
                "review_card_severity": cards[incident_id]["severity"],
            }
        )
    return outcomes


def _recorded_review_context(workflow_input: dict[str, Any]) -> list[dict[str, Any]]:
    context = []
    incidents = sorted(
        workflow_input["fit_recovery_incidents"],
        key=lambda incident: incident["order"],
    )
    for incident in incidents:
        review_note_ref = incident.get("review_note_ref")
        expected_replay_behavior = incident.get("expected_replay_behavior")
        if review_note_ref or expected_replay_behavior:
            context.append(
                {
                    "incident_id": incident["incident_id"],
                    "review_note_ref": review_note_ref,
                    "expected_replay_behavior_recorded": bool(expected_replay_behavior),
                }
            )
    return context


def build_fit_recovery_interaction_recording_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a side-effect-free interaction recording summary."""

    _validate_source(source)
    workflow_input = copy.deepcopy(source["workflow_input_before"])
    review_surface = copy.deepcopy(source["review_surface"])
    applied_events = [
        _apply_event(workflow_input, review_surface, event) for event in _ordered_events(source)
    ]
    _validate_final_interaction_state(workflow_input)
    workflow = build_fit_recovery_workflow_summary(workflow_input)
    review_input = {
        "fixture_id": f"{source['fixture_id']}.review-state",
        "fixture_status": source["fixture_status"],
        "user_job": source["user_job"],
        "review_surface": review_surface,
        "recovery_workflow_input": workflow_input,
    }
    review = build_fit_recovery_review_state_summary(review_input)
    return {
        "summary_id": source["fixture_id"] + ".candidate",
        "recording_context": copy.deepcopy(source["recording_context"]),
        "applied_events": applied_events,
        "projected_workflow_summary_id": workflow["summary_id"],
        "projected_review_state_summary_id": review["summary_id"],
        "selected_review_incident_id": review["surface_context"].get("selected_incident_id"),
        "recorded_review_context": _recorded_review_context(workflow_input),
        "interaction_outcomes": _interaction_outcomes(workflow, review),
        "missing_context": copy.deepcopy(review["missing_context"]),
        "attention": copy.deepcopy(review["attention"]),
        "boundary": {
            "summary_posture": "internal_validation_summary",
            "non_claims": [
                "no GUI implementation",
                "no notebook integration",
                "no fit execution",
                "no fit model selection",
                "no Scopecat-defined score",
                "no automatic ROI or initial-guess selection",
                "no automatic remeasurement, retry, retune, or optimization",
                "no remeasurement or hardware control",
                "no parameter write-back",
                "no local executor or notebook execution",
                "no runner design",
                "no remote execution",
                "no replay harness",
                "no dataset registry",
                "no portable/public dataset package",
                "no handoff artifact",
                "no lab-sharing bundle",
            ],
        },
    }
