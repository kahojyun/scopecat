"""Structured summary builder for calibration fit validation dataset curation.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not execute fitting code, read source data, select
ROIs, reject outliers, remeasure, apply parameter writes, schedule work, or
control hardware.
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


def _validate_source(source: dict[str, Any]) -> None:
    _records_by_key(source["fit_incidents"], "incident_id")
    selected_case_ids = {}
    for incident in source["fit_incidents"]:
        recovery = incident["recovery"]
        chosen = recovery["chosen_action"]
        available = recovery["available_actions"]
        if chosen not in available:
            raise ValueError(f"chosen action is not available: {chosen}")
        if incident["dataset_selection"]["selected"]:
            case_id = _case_id(incident["incident_id"])
            if case_id in selected_case_ids:
                raise ValueError(f"duplicate validation_case_id: {case_id}")
            selected_case_ids[case_id] = incident["incident_id"]
        _validate_attempt_history(incident)


def _validate_attempt_history(incident: dict[str, Any]) -> None:
    history = incident.get("fit_attempt_history", [])
    if not history:
        return

    attempts = _records_by_key(history, "attempt_id")
    current_attempt_id = incident["fit_attempt"].get("attempt_id")
    if current_attempt_id and current_attempt_id not in attempts:
        raise ValueError(f"current fit attempt is not in history: {current_attempt_id}")

    selected_attempt_ids = incident["dataset_selection"].get("selected_attempt_ids")
    if not incident["dataset_selection"]["selected"] and selected_attempt_ids:
        raise ValueError("unselected incident cannot declare selected fit attempts")
    if incident["dataset_selection"]["selected"] and not selected_attempt_ids:
        raise ValueError("selected fit attempts cannot be empty")

    seen = set()
    for attempt_id in selected_attempt_ids or []:
        if attempt_id in seen:
            raise ValueError(f"duplicate selected_attempt_id: {attempt_id}")
        seen.add(attempt_id)
        if attempt_id not in attempts:
            raise ValueError(f"selected fit attempt is not in history: {attempt_id}")


def _case_id(incident_id: str) -> str:
    return f"validation-case-{incident_id.removeprefix('incident-')}"


def _fit_attempt(incident: dict[str, Any]) -> dict[str, Any]:
    return incident["fit_attempt"]


def _queue_item(incident: dict[str, Any]) -> dict[str, Any]:
    fit_attempt = _fit_attempt(incident)
    item = {
        "incident_id": incident["incident_id"],
        "order": incident["order"],
        "state": incident["state"],
        "measurement_ref": copy.deepcopy(incident["measurement_ref"]),
        "calibration_target": incident["calibration_target"],
        "fit_family": incident["fit_family"],
        "labels": list(incident["labels"]),
        "fit_attempt_ref": fit_attempt.get("attempt_id"),
        "fit_attempt_status": fit_attempt["status"],
        "recovery_actions": list(incident["recovery"]["available_actions"]),
        "chosen_recovery_action": incident["recovery"]["chosen_action"],
        "selected_for_dataset": incident["dataset_selection"]["selected"],
        "source_authority": incident["authority"],
    }
    if incident.get("fit_attempt_history"):
        item["fit_attempt_history_count"] = len(incident["fit_attempt_history"])
        item["current_fit_attempt_ref"] = fit_attempt.get("attempt_id")
        item["selected_fit_attempt_refs"] = _selected_attempt_ids(incident)
    return item


def _recovery_actions(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for incident in incidents:
        chosen = incident["recovery"]["chosen_action"]
        for action in incident["recovery"]["available_actions"]:
            actions.append(
                {
                    "action_id": f"{incident['incident_id']}:{action}",
                    "incident_id": incident["incident_id"],
                    "action": action,
                    "chosen": action == chosen,
                    "source": "fixture_declared",
                }
            )
    return actions


def _selected_incidents(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [incident for incident in incidents if incident["dataset_selection"]["selected"]]


def _missing_selected_case_fields(incident: dict[str, Any]) -> list[str]:
    missing = []
    measurement_ref = incident.get("measurement_ref", {})
    fit_attempt = incident.get("fit_attempt", {})
    for field in ["record_id"]:
        if not measurement_ref.get(field):
            missing.append(f"measurement_ref.{field}")
    for field in ["attempt_id", "user_code_ref", "fit_config_ref"]:
        if not fit_attempt.get(field):
            missing.append(f"fit_attempt.{field}")
    if incident.get("fit_attempt_history"):
        attempts = {
            attempt["attempt_id"]: attempt
            for attempt in incident.get("fit_attempt_history", [])
            if attempt.get("attempt_id")
        }
        for attempt_id in _selected_attempt_ids(incident):
            attempt = attempts.get(attempt_id, {})
            for field in ["user_code_ref", "fit_config_ref"]:
                if not attempt.get(field):
                    missing.append(f"fit_attempt_history.{attempt_id}.{field}")
    if not incident.get("review_note_ref"):
        missing.append("review_note_ref")
    if not incident.get("expected_replay_behavior"):
        missing.append("expected_replay_behavior")
    return missing


def _selected_attempt_ids(incident: dict[str, Any]) -> list[str]:
    if incident.get("fit_attempt_history") and not incident["dataset_selection"]["selected"]:
        return []
    selected = incident["dataset_selection"].get("selected_attempt_ids")
    if selected is not None:
        return list(selected)
    attempt_id = incident.get("fit_attempt", {}).get("attempt_id")
    return [attempt_id] if attempt_id else []


def _attempts_by_id(incident: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        attempt["attempt_id"]: attempt
        for attempt in incident.get("fit_attempt_history", [])
        if attempt.get("attempt_id")
    }


def _selected_attempt_records(incident: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = _attempts_by_id(incident)
    return [attempts[attempt_id] for attempt_id in _selected_attempt_ids(incident)]


def _primary_fit_attempt(incident: dict[str, Any]) -> dict[str, Any]:
    if incident.get("fit_attempt_history"):
        selected_attempts = _selected_attempt_records(incident)
        if selected_attempts:
            return selected_attempts[-1]
    return _fit_attempt(incident)


def _dataset_attempt_ref(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt_id": attempt["attempt_id"],
        "status": attempt["status"],
        "user_code_ref": attempt.get("user_code_ref"),
        "fit_config_ref": attempt.get("fit_config_ref"),
    }


def _dataset_candidate(incident: dict[str, Any]) -> dict[str, Any]:
    fit_attempt = _primary_fit_attempt(incident)
    measurement_ref = incident.get("measurement_ref", {})
    candidate = {
        "validation_case_id": _case_id(incident["incident_id"]),
        "source_measurement_ref": measurement_ref.get("record_id"),
        "calibration_target": incident["calibration_target"],
        "fit_family": incident["fit_family"],
        "incident_labels": list(incident["labels"]),
        "user_fit_attempt_ref": fit_attempt.get("attempt_id"),
        "user_code_ref": fit_attempt.get("user_code_ref"),
        "fit_config_ref": fit_attempt.get("fit_config_ref"),
        "review_note_ref": incident.get("review_note_ref"),
        "expected_replay_behavior": incident.get("expected_replay_behavior"),
        "selection_reason": incident["dataset_selection"]["reason"],
    }
    if incident.get("fit_attempt_history"):
        candidate["source_fit_attempt_refs"] = _selected_attempt_ids(incident)
        candidate["selected_fit_attempts"] = [
            _dataset_attempt_ref(attempt) for attempt in _selected_attempt_records(incident)
        ]
    return candidate


def _fit_attempt_history(incident: dict[str, Any]) -> dict[str, Any]:
    attempts = []
    for attempt in incident.get("fit_attempt_history", []):
        attempts.append(
            {
                "attempt_id": attempt["attempt_id"],
                "order": attempt["order"],
                "status": attempt["status"],
                "status_reason": attempt["status_reason"],
                "user_code_ref": attempt.get("user_code_ref"),
                "fit_config_ref": attempt.get("fit_config_ref"),
                "config_labels": list(attempt.get("config_labels", [])),
                "input_adjustments": list(attempt.get("input_adjustments", [])),
                "output_ref": attempt.get("output_ref"),
                "declared_diagnostics": copy.deepcopy(attempt.get("declared_diagnostics", {})),
            }
        )
    return {
        "incident_id": incident["incident_id"],
        "current_fit_attempt_ref": incident["fit_attempt"].get("attempt_id"),
        "selected_fit_attempt_refs": _selected_attempt_ids(incident),
        "attempts": attempts,
    }


def _attempt_histories(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _fit_attempt_history(incident)
        for incident in incidents
        if incident.get("fit_attempt_history")
    ]


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    if source["dataset_draft"]["posture"] != LAB_INTERNAL_DATASET_POSTURE:
        findings.append(
            {
                "code": "dataset_posture_not_lab_internal",
                "subject": source["dataset_draft"]["dataset_id"],
                "posture": source["dataset_draft"]["posture"],
                "message": (
                    "Dataset draft posture is outside the validated lab-internal boundary."
                ),
            }
        )
    for incident in _selected_incidents(source["fit_incidents"]):
        missing = _missing_selected_case_fields(incident)
        if missing:
            findings.append(
                {
                    "code": "selected_case_missing_replay_context",
                    "subject": incident["incident_id"],
                    "missing": missing,
                    "message": ("Selected validation case is missing user-owned replay context."),
                }
            )
    return findings


def _dataset_draft(
    source: dict[str, Any],
    candidates: list[dict[str, Any]],
    attention: list[dict[str, Any]],
) -> dict[str, Any]:
    draft = source["dataset_draft"]
    withheld = [
        incident["incident_id"]
        for incident in source["fit_incidents"]
        if not incident["dataset_selection"]["selected"]
    ]
    return {
        "dataset_id": draft["dataset_id"],
        "label": draft["label"],
        "posture": draft["posture"],
        "selected_case_ids": [candidate["validation_case_id"] for candidate in candidates],
        "withheld_incident_ids": withheld,
        "ready_for_lab_internal_validation": (
            bool(candidates) and not attention and draft["posture"] == LAB_INTERNAL_DATASET_POSTURE
        ),
    }


def build_fit_validation_dataset_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free fit validation dataset summary."""

    _validate_source(source)
    incidents = list(source["fit_incidents"])
    candidates = [_dataset_candidate(incident) for incident in _selected_incidents(incidents)]
    attention = _attention(source)
    summary = {
        "summary_id": source["fixture_id"] + ".candidate",
        "queue": [_queue_item(incident) for incident in incidents],
        "recovery_actions": _recovery_actions(incidents),
        "dataset_candidates": candidates,
        "dataset_draft": _dataset_draft(source, candidates, attention),
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
                "no portable/public dataset package",
            ],
        },
    }
    attempt_histories = _attempt_histories(incidents)
    if attempt_histories:
        summary["attempt_histories"] = attempt_histories
    return summary
