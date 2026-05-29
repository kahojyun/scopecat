"""Structured summary builder for calibration fit recovery workflow.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not execute fitting code, read source data, choose
ROI or initial guesses, remeasure, apply parameter writes, schedule work,
replay cases, create dataset registry entries, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

LAB_INTERNAL_DATASET_POSTURE = "lab_internal_validation_dataset_draft"


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _attempts_by_id(incident: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(incident.get("fit_attempt_history", []), "attempt_id")


def _selected_attempt_ids(incident: dict[str, Any]) -> list[str]:
    return list(incident["dataset_selection"].get("selected_attempt_ids", []))


def _validate_source(source: dict[str, Any]) -> None:
    _records_by_key(source["fit_recovery_incidents"], "incident_id")
    for incident in source["fit_recovery_incidents"]:
        recovery = incident["recovery"]
        chosen = recovery["chosen_action"]
        if chosen not in recovery["available_actions"]:
            raise ValueError(f"chosen action is not available: {chosen}")
        _validate_action_compatibility(incident)
        _validate_attempt_history(incident)
        _validate_dataset_selection(incident)


def _current_attempt_status(incident: dict[str, Any]) -> str:
    return incident["fit_attempt"]["status"]


def _is_accepted_attempt_status(status: str) -> bool:
    return status in {"completed_after_user_adjustment", "accepted_after_review"}


def _validate_action_compatibility(incident: dict[str, Any]) -> None:
    classification = incident["signal_assessment"]["classification"]
    chosen = incident["recovery"]["chosen_action"]
    if classification == "no_clear_signal" and chosen != "adjust_parameters_remeasure":
        raise ValueError("no-signal recovery must choose remeasurement")
    if chosen == "accept_after_refit":
        if classification != "visible_signal":
            raise ValueError("accepted refit recovery requires visible signal")
        if not _is_accepted_attempt_status(_current_attempt_status(incident)):
            raise ValueError("accepted refit recovery requires accepted current attempt")


def _validate_attempt_history(incident: dict[str, Any]) -> None:
    history = incident.get("fit_attempt_history", [])
    if not history:
        return
    attempts = _attempts_by_id(incident)
    current_attempt_id = incident["fit_attempt"].get("attempt_id")
    if current_attempt_id and current_attempt_id not in attempts:
        raise ValueError(f"current fit attempt is not in history: {current_attempt_id}")
    seen = set()
    for attempt_id in _selected_attempt_ids(incident):
        if attempt_id in seen:
            raise ValueError(f"duplicate selected_attempt_id: {attempt_id}")
        seen.add(attempt_id)
        if attempt_id not in attempts:
            raise ValueError(f"selected fit attempt is not in history: {attempt_id}")


def _validate_dataset_selection(incident: dict[str, Any]) -> None:
    selection = incident["dataset_selection"]
    selected_attempt_ids = _selected_attempt_ids(incident)
    if selection["selected"] and not incident.get("fit_attempt_history"):
        raise ValueError("selected validation case must declare fit attempt history")
    if selection["selected"] and not selected_attempt_ids:
        raise ValueError("selected fit attempts cannot be empty")
    if not selection["selected"] and selected_attempt_ids:
        raise ValueError("unselected incident cannot declare selected fit attempts")
    current_attempt_id = incident["fit_attempt"].get("attempt_id")
    if (
        selection["selected"]
        and incident["recovery"]["chosen_action"] == "accept_after_refit"
        and current_attempt_id
        and current_attempt_id not in selected_attempt_ids
    ):
        raise ValueError("selected attempts omit current accepted fit attempt")
    if selection["selected"] and incident["recovery"]["chosen_action"] == "accept_after_refit":
        selected_attempts = [
            _attempts_by_id(incident)[attempt_id] for attempt_id in selected_attempt_ids
        ]
        prior_failed_attempts = [
            attempt
            for attempt in selected_attempts
            if attempt["attempt_id"] != current_attempt_id and "failed" in attempt["status"]
        ]
        if not prior_failed_attempts:
            raise ValueError("selected attempts omit failed prior fit attempt")


def _recovery_family(action: str) -> str:
    if action == "adjust_parameters_remeasure":
        return "remeasure"
    if action in {"adjust_roi_refit", "adjust_initial_guess_refit"}:
        return "refit"
    if action in {"accept_after_refit", "accept_after_review"}:
        return "accept"
    if action == "add_to_validation_dataset":
        return "dataset_curation"
    if action == "skip_target":
        return "skip"
    return "user_review"


def _immediate_recovery_item(incident: dict[str, Any]) -> dict[str, Any]:
    chosen_action = incident["recovery"]["chosen_action"]
    return {
        "incident_id": incident["incident_id"],
        "order": incident["order"],
        "signal_classification": incident["signal_assessment"]["classification"],
        "chosen_action": chosen_action,
        "action_family": _recovery_family(chosen_action),
        "action_source": incident["recovery"]["authority"],
        "available_actions": list(incident["recovery"]["available_actions"]),
        "measurement_ref": copy.deepcopy(incident["measurement_ref"]),
    }


def _continuation_status(incident: dict[str, Any]) -> str:
    classification = incident["signal_assessment"]["classification"]
    chosen_action = incident["recovery"]["chosen_action"]
    if classification == "no_clear_signal" and chosen_action == "adjust_parameters_remeasure":
        return "requires_remeasurement"
    if chosen_action == "accept_after_refit" and _is_accepted_attempt_status(
        _current_attempt_status(incident)
    ):
        return "can_continue"
    if chosen_action in {"adjust_roi_refit", "adjust_initial_guess_refit"}:
        return "requires_refit"
    if chosen_action == "skip_target":
        return "skipped"
    return "requires_user_review"


def _continuation_item(incident: dict[str, Any]) -> dict[str, Any]:
    status = _continuation_status(incident)
    return {
        "incident_id": incident["incident_id"],
        "current_step_id": incident["continuation"]["current_step_id"],
        "next_step_id": incident["continuation"].get("next_step_id"),
        "status": status,
        "can_continue": status == "can_continue",
        "blocking_reason": None
        if status == "can_continue"
        else incident["continuation"]["blocked_reason"],
        "source": incident["continuation"]["authority"],
    }


def _selected_attempt_records(incident: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = _attempts_by_id(incident)
    return [
        {
            "attempt_id": attempt["attempt_id"],
            "status": attempt["status"],
            "user_code_ref": attempt.get("user_code_ref"),
            "fit_config_ref": attempt.get("fit_config_ref"),
        }
        for attempt in (attempts[attempt_id] for attempt_id in _selected_attempt_ids(incident))
    ]


def _dataset_offer(incident: dict[str, Any]) -> dict[str, Any]:
    selection = incident["dataset_selection"]
    state = "selected_for_lab_validation" if selection["selected"] else "withheld"
    if (
        not selection["selected"]
        and incident["signal_assessment"]["classification"] == "no_clear_signal"
    ):
        state = "withheld_for_remeasurement"
    output = {
        "incident_id": incident["incident_id"],
        "state": state,
        "selected": selection["selected"],
        "reason": selection["reason"],
        "source_measurement_ref": incident["measurement_ref"].get("record_id"),
        "selected_fit_attempt_refs": _selected_attempt_ids(incident),
        "selected_fit_attempts": _selected_attempt_records(incident),
    }
    if selection["selected"]:
        output["validation_case_id"] = (
            f"validation-case-{incident['incident_id'].removeprefix('incident-')}"
        )
        output["expected_replay_behavior"] = incident.get("expected_replay_behavior")
    return output


def _missing_selected_context(incident: dict[str, Any]) -> list[str]:
    missing = []
    if not incident.get("measurement_ref", {}).get("record_id"):
        missing.append("measurement_ref.record_id")
    if not incident.get("fit_attempt", {}).get("attempt_id"):
        missing.append("fit_attempt.attempt_id")
    if not incident.get("fit_attempt", {}).get("user_code_ref"):
        missing.append("fit_attempt.user_code_ref")
    if not incident.get("fit_attempt", {}).get("fit_config_ref"):
        missing.append("fit_attempt.fit_config_ref")
    if incident.get("fit_attempt_history"):
        attempts = _attempts_by_id(incident)
        for attempt_id in _selected_attempt_ids(incident):
            attempt = attempts.get(attempt_id, {})
            if not attempt.get("user_code_ref"):
                missing.append(f"fit_attempt_history.{attempt_id}.user_code_ref")
            if not attempt.get("fit_config_ref"):
                missing.append(f"fit_attempt_history.{attempt_id}.fit_config_ref")
    if not incident.get("review_note_ref"):
        missing.append("review_note_ref")
    if not incident.get("expected_replay_behavior"):
        missing.append("expected_replay_behavior")
    return missing


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    dataset = source["dataset_draft"]
    if dataset["posture"] != LAB_INTERNAL_DATASET_POSTURE:
        findings.append(
            {
                "code": "dataset_posture_not_lab_internal",
                "subject": dataset["dataset_id"],
                "posture": dataset["posture"],
                "message": "Dataset draft posture is outside the validated lab-internal boundary.",
            }
        )
    for incident in source["fit_recovery_incidents"]:
        if (
            incident["dataset_selection"]["selected"]
            and incident["signal_assessment"]["classification"] == "no_clear_signal"
        ):
            findings.append(
                {
                    "code": "no_signal_case_selected_for_validation",
                    "subject": incident["incident_id"],
                    "message": "No-signal recovery case should be withheld until remeasurement is reviewed.",
                }
            )
        if incident["dataset_selection"]["selected"]:
            missing = _missing_selected_context(incident)
            if missing:
                findings.append(
                    {
                        "code": "selected_case_missing_replay_context",
                        "subject": incident["incident_id"],
                        "missing": missing,
                        "message": "Selected validation case is missing user-owned replay context.",
                    }
                )
    return findings


def _dataset_draft(
    source: dict[str, Any],
    offers: list[dict[str, Any]],
    attention: list[dict[str, Any]],
) -> dict[str, Any]:
    dataset = source["dataset_draft"]
    selected_offers = [offer for offer in offers if offer["selected"]]
    return {
        "dataset_id": dataset["dataset_id"],
        "label": dataset["label"],
        "posture": dataset["posture"],
        "selected_case_ids": [
            offer["validation_case_id"]
            for offer in selected_offers
            if "validation_case_id" in offer
        ],
        "withheld_incident_ids": [
            offer["incident_id"] for offer in offers if offer["state"].startswith("withheld")
        ],
        "ready_for_lab_internal_validation": (
            bool(selected_offers)
            and not attention
            and dataset["posture"] == LAB_INTERNAL_DATASET_POSTURE
        ),
    }


def build_fit_recovery_workflow_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free fit recovery workflow summary."""

    _validate_source(source)
    incidents = sorted(source["fit_recovery_incidents"], key=lambda incident: incident["order"])
    recovery = [_immediate_recovery_item(incident) for incident in incidents]
    continuation = [_continuation_item(incident) for incident in incidents]
    offers = [_dataset_offer(incident) for incident in incidents]
    attention = _attention(source)
    return {
        "summary_id": source["fixture_id"] + ".candidate",
        "workflow_context": copy.deepcopy(source["workflow_context"]),
        "immediate_recovery": recovery,
        "continuation_readiness": continuation,
        "dataset_selection_offers": offers,
        "dataset_draft": _dataset_draft(source, offers, attention),
        "attention": attention,
        "boundary": {
            "summary_posture": "internal_validation_summary",
            "non_claims": [
                "no fit execution",
                "no Scopecat-defined score",
                "no automatic ROI or initial-guess selection",
                "no remeasurement or hardware control",
                "no parameter write-back",
                "no replay harness",
                "no dataset registry",
                "no GUI workflow",
            ],
        },
    }
