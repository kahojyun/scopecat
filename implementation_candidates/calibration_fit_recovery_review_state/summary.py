"""Review-state projection for calibration fit recovery workflow.

This module is an experimental production-shaped boundary. It composes an
existing side-effect-free recovery workflow summary into state a future local
review surface could consume. It does not render a GUI, execute fitting code,
score results, choose recovery actions, replay cases, create dataset registry
entries, apply writes, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.calibration_fit_recovery_workflow import (
    build_fit_recovery_workflow_summary,
)

REVIEW_SURFACE_KIND = "local_review_state"
BLOCKING_CONTINUATION_STATUSES = {
    "requires_remeasurement",
    "requires_refit",
    "requires_user_review",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _incidents_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["fit_recovery_incidents"], "incident_id")


def _workflow_by_id(
    workflow: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return (
        _records_by_key(workflow["immediate_recovery"], "incident_id"),
        _records_by_key(workflow["continuation_readiness"], "incident_id"),
        _records_by_key(workflow["dataset_selection_offers"], "incident_id"),
    )


def _validate_review_state_input(source: dict[str, Any], workflow: dict[str, Any]) -> None:
    surface = source["review_surface"]
    if surface.get("surface_kind") != REVIEW_SURFACE_KIND:
        raise ValueError(f"unsupported review surface kind: {surface.get('surface_kind')}")
    incidents = _incidents_by_id(source["recovery_workflow_input"])
    recovery, continuation, offers = _workflow_by_id(workflow)
    for incident_id, incident in incidents.items():
        if incident_id not in recovery:
            raise ValueError(f"review state missing recovery item: {incident_id}")
        if incident_id not in continuation:
            raise ValueError(f"review state missing continuation item: {incident_id}")
        if incident_id not in offers:
            raise ValueError(f"review state missing dataset offer: {incident_id}")
        chosen = incident["recovery"]["chosen_action"]
        if recovery[incident_id]["chosen_action"] != chosen:
            raise ValueError("review state recovery action does not match workflow input")
        if offers[incident_id]["selected"] != incident["dataset_selection"]["selected"]:
            raise ValueError("review state dataset selection does not match workflow input")
    selected_control = surface.get("selected_incident_id")
    if selected_control is not None and selected_control not in incidents:
        raise ValueError(f"review surface selects missing incident: {selected_control}")


def _has_no_clear_signal(incident: dict[str, Any]) -> bool:
    return incident["signal_assessment"]["classification"] == "no_clear_signal"


def _review_dataset_projection(incident: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    if _has_no_clear_signal(incident):
        return {
            "selected": False,
            "state": "withheld_for_remeasurement",
            "enabled": False,
            "disabled_reason": "No clear signal should be remeasured before dataset selection.",
            "selected_fit_attempt_refs": [],
            "validation_case_id": None,
            "reason": offer["reason"],
        }
    return {
        "selected": offer["selected"],
        "state": offer["state"],
        "enabled": True,
        "disabled_reason": None,
        "selected_fit_attempt_refs": list(offer["selected_fit_attempt_refs"]),
        "validation_case_id": offer.get("validation_case_id"),
        "reason": offer["reason"],
    }


def _severity(continuation: dict[str, Any], dataset: dict[str, Any]) -> str:
    if continuation["status"] == "requires_remeasurement":
        return "blocking"
    if continuation["status"] in {"requires_refit", "requires_user_review"}:
        return "needs_review"
    if dataset["selected"]:
        return "ready_with_dataset_case"
    if continuation["can_continue"]:
        return "ready"
    return "informational"


def _card_title(incident: dict[str, Any]) -> str:
    classification = incident["signal_assessment"]["classification"]
    if classification == "no_clear_signal":
        return "No clear signal"
    if classification == "visible_signal":
        return "Visible signal fit recovery"
    return "Fit recovery review"


def _incident_card(
    incident: dict[str, Any],
    recovery: dict[str, Any],
    continuation: dict[str, Any],
    offer: dict[str, Any],
) -> dict[str, Any]:
    dataset = _review_dataset_projection(incident, offer)
    return {
        "incident_id": incident["incident_id"],
        "order": incident["order"],
        "title": _card_title(incident),
        "signal_classification": recovery["signal_classification"],
        "state": incident["state"],
        "severity": _severity(continuation, dataset),
        "measurement_ref": copy.deepcopy(recovery["measurement_ref"]),
        "chosen_recovery_action": recovery["chosen_action"],
        "continuation_status": continuation["status"],
        "dataset_selection_state": dataset["state"],
        "badges": list(incident.get("labels", [])),
    }


def _action_label(action: str) -> str:
    labels = {
        "adjust_parameters_remeasure": "Adjust parameters and remeasure",
        "adjust_roi_refit": "Adjust ROI and refit",
        "adjust_initial_guess_refit": "Adjust initial guess and refit",
        "accept_after_refit": "Accept adjusted refit",
        "add_to_validation_dataset": "Add to validation dataset",
        "skip_target": "Skip target",
    }
    return labels.get(action, action.replace("_", " ").title())


def _primary_action(
    incident: dict[str, Any],
    recovery: dict[str, Any],
    continuation: dict[str, Any],
    offer: dict[str, Any],
) -> dict[str, Any]:
    action = recovery["chosen_action"]
    dataset = _review_dataset_projection(incident, offer)
    return {
        "action_id": f"{incident['incident_id']}:{action}",
        "incident_id": incident["incident_id"],
        "action": action,
        "label": _action_label(action),
        "enabled": True,
        "selected": True,
        "source": recovery["action_source"],
        "continuation_effect": continuation["status"],
        "dataset_effect": dataset["state"],
    }


def _dataset_control(incident: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    dataset = _review_dataset_projection(incident, offer)
    return {
        "control_id": f"{incident['incident_id']}:dataset-selection",
        "incident_id": incident["incident_id"],
        "selected": dataset["selected"],
        "state": dataset["state"],
        "enabled": dataset["enabled"],
        "disabled_reason": dataset["disabled_reason"],
        "selected_fit_attempt_refs": dataset["selected_fit_attempt_refs"],
        "validation_case_id": dataset["validation_case_id"],
        "reason": dataset["reason"],
    }


def _continuation_banner(workflow: dict[str, Any]) -> dict[str, Any]:
    readiness = workflow["continuation_readiness"]
    blocking = [item for item in readiness if item["status"] in BLOCKING_CONTINUATION_STATUSES]
    ready = [item for item in readiness if item["can_continue"]]
    if blocking:
        state = "blocked"
        message = "Some fit recovery incidents still need user action before continuation."
    elif ready:
        state = "can_continue"
        message = "All linked fit recovery incidents can continue."
    else:
        state = "no_continuation_target"
        message = "No linked continuation target is ready or blocked."
    return {
        "state": state,
        "message": message,
        "blocked_incident_ids": [item["incident_id"] for item in blocking],
        "ready_incident_ids": [item["incident_id"] for item in ready],
    }


def _missing_context(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(item)
        for item in workflow["attention"]
        if item["code"] == "selected_case_missing_replay_context"
    ]


def build_fit_recovery_review_state_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free fit recovery review state summary."""

    workflow = build_fit_recovery_workflow_summary(source["recovery_workflow_input"])
    _validate_review_state_input(source, workflow)
    incidents = sorted(
        source["recovery_workflow_input"]["fit_recovery_incidents"],
        key=lambda incident: incident["order"],
    )
    recovery, continuation, offers = _workflow_by_id(workflow)
    cards = [
        _incident_card(
            incident,
            recovery[incident["incident_id"]],
            continuation[incident["incident_id"]],
            offers[incident["incident_id"]],
        )
        for incident in incidents
    ]
    actions = [
        _primary_action(
            incident,
            recovery[incident["incident_id"]],
            continuation[incident["incident_id"]],
            offers[incident["incident_id"]],
        )
        for incident in incidents
    ]
    dataset_controls = [
        _dataset_control(incident, offers[incident["incident_id"]]) for incident in incidents
    ]
    return {
        "summary_id": source["fixture_id"] + ".candidate",
        "surface_context": copy.deepcopy(source["review_surface"]),
        "workflow_summary_id": workflow["summary_id"],
        "incident_cards": cards,
        "primary_actions": actions,
        "dataset_selection_controls": dataset_controls,
        "continuation_banner": _continuation_banner(workflow),
        "missing_context": _missing_context(workflow),
        "attention": copy.deepcopy(workflow["attention"]),
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
                "no replay harness",
                "no dataset registry",
                "no portable/public dataset package",
            ],
        },
    }
