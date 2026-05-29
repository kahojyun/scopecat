"""Composition summary for fit recovery and continuation context.

This module is an experimental production-shaped boundary. It composes
side-effect-free summaries from existing candidates; it does not execute fits,
score results, choose recovery actions, apply writes, schedule steps, replay
attempts, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.calibration_fit_validation_dataset import (
    build_fit_validation_dataset_summary,
)
from implementation_candidates.calibration_work_continuation import (
    build_calibration_continuation_summary,
)


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _step_by_id(continuation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(continuation["steps"], "step_id")


def _queue_by_incident(fit_validation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(fit_validation["queue"], "incident_id")


def _candidate_by_id(fit_validation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(fit_validation["dataset_candidates"], "validation_case_id")


def _action_by_id(fit_validation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(fit_validation["recovery_actions"], "action_id")


def _output_by_id(continuation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(continuation["outputs"], "output_id")


def _expected_validation_case_id(incident_id: str) -> str:
    return f"validation-case-{incident_id.removeprefix('incident-')}"


def _validate_links(
    links: dict[str, Any],
    continuation: dict[str, Any],
    fit_validation: dict[str, Any],
) -> None:
    steps = _step_by_id(continuation)
    queue = _queue_by_incident(fit_validation)
    candidates = _candidate_by_id(fit_validation)
    actions = _action_by_id(fit_validation)

    for field in ["current_step_id", "next_step_id"]:
        step_id = links[field]
        if step_id not in steps:
            raise ValueError(f"composition references missing step: {step_id}")
    current_step = steps[links["current_step_id"]]
    next_step = steps[links["next_step_id"]]
    if current_step["step_id"] == next_step["step_id"]:
        raise ValueError("composition current and next steps must differ")
    if current_step["order"] >= next_step["order"]:
        raise ValueError("composition current step must precede next step")
    if current_step["lifecycle_state"] != "completed":
        raise ValueError("composition current step is not completed")
    intermediate_steps = [
        step
        for step in steps.values()
        if current_step["order"] < step["order"] < next_step["order"]
    ]
    for step in intermediate_steps:
        if step["lifecycle_state"] != "completed":
            raise ValueError("composition intermediate step is not completed")

    incident_id = links["fit_incident_id"]
    if incident_id not in queue:
        raise ValueError(f"composition references missing fit incident: {incident_id}")
    queue_item = queue[incident_id]

    validation_case_id = links["validation_case_id"]
    if validation_case_id not in candidates:
        raise ValueError(f"composition references missing validation case: {validation_case_id}")
    if validation_case_id != _expected_validation_case_id(incident_id):
        raise ValueError("composition validation case belongs to a different incident")
    candidate = candidates[validation_case_id]
    incident_measurement_ref = queue_item["measurement_ref"].get("record_id")
    candidate_measurement_ref = candidate["source_measurement_ref"]
    if candidate_measurement_ref != incident_measurement_ref:
        raise ValueError("composition validation case measurement does not match fit incident")
    if candidate_measurement_ref not in current_step["outputs"]:
        raise ValueError("composition validation case measurement is not an output of current step")
    output = _output_by_id(continuation).get(candidate_measurement_ref)
    if not output or output["kind"] != "measurement_reference":
        raise ValueError("composition validation case measurement is not a measurement output")

    recovery_action_id = links["recovery_action_id"]
    if recovery_action_id not in actions:
        raise ValueError(f"composition references missing recovery action: {recovery_action_id}")
    if actions[recovery_action_id]["incident_id"] != incident_id:
        raise ValueError("composition recovery action belongs to a different incident")
    if not actions[recovery_action_id]["chosen"]:
        raise ValueError("composition recovery action is not the chosen action")

    selected_attempt_ids = links.get("selected_attempt_ids", [])
    candidate_attempt_ids = candidate.get("source_fit_attempt_refs", [])
    if selected_attempt_ids != candidate_attempt_ids:
        raise ValueError("composition selected attempts do not match validation case")
    current_attempt_id = queue_item.get("current_fit_attempt_ref") or queue_item.get(
        "fit_attempt_ref"
    )
    if current_attempt_id and current_attempt_id not in candidate_attempt_ids:
        raise ValueError("composition selected attempts omit current fit attempt")
    if current_attempt_id and candidate["user_fit_attempt_ref"] != current_attempt_id:
        raise ValueError("composition validation case primary attempt is not current")


def _attention(
    links: dict[str, Any],
    continuation: dict[str, Any],
    fit_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    attention = []
    next_step = _step_by_id(continuation)[links["next_step_id"]]
    if next_step["lifecycle_state"] == "blocked":
        attention.append(
            {
                "code": "continuation_still_blocked",
                "subject": next_step["step_id"],
                "message": "Linked downstream step is still blocked after fit recovery.",
            }
        )
    if not fit_validation["dataset_draft"]["ready_for_lab_internal_validation"]:
        attention.append(
            {
                "code": "validation_dataset_not_ready",
                "subject": fit_validation["dataset_draft"]["dataset_id"],
                "child_attention": copy.deepcopy(fit_validation["attention"]),
                "message": "Linked validation dataset draft is not ready.",
            }
        )
    return attention


def _continuation_effect(
    links: dict[str, Any],
    continuation: dict[str, Any],
    attention: list[dict[str, Any]],
) -> dict[str, Any]:
    steps = _step_by_id(continuation)
    current_step = steps[links["current_step_id"]]
    next_step = steps[links["next_step_id"]]
    status = (
        "can_continue" if not attention and next_step["lifecycle_state"] == "pending" else "blocked"
    )
    return {
        "status": status,
        "current_step_id": current_step["step_id"],
        "current_step_lifecycle_state": current_step["lifecycle_state"],
        "next_step_id": next_step["step_id"],
        "next_step_lifecycle_state": next_step["lifecycle_state"],
        "continuation_blocked": status != "can_continue",
    }


def _recovery_summary(
    links: dict[str, Any],
    fit_validation: dict[str, Any],
) -> dict[str, Any]:
    action = _action_by_id(fit_validation)[links["recovery_action_id"]]
    queue_item = _queue_by_incident(fit_validation)[links["fit_incident_id"]]
    return {
        "fit_incident_id": queue_item["incident_id"],
        "fit_family": queue_item["fit_family"],
        "chosen_recovery_action": action["action"],
        "recovery_action_id": action["action_id"],
        "source": action["source"],
    }


def _validation_preservation(
    links: dict[str, Any],
    fit_validation: dict[str, Any],
) -> dict[str, Any]:
    candidate = _candidate_by_id(fit_validation)[links["validation_case_id"]]
    fit_incident = _queue_by_incident(fit_validation)[links["fit_incident_id"]]
    return {
        "dataset_id": fit_validation["dataset_draft"]["dataset_id"],
        "dataset_posture": fit_validation["dataset_draft"]["posture"],
        "ready_for_lab_internal_validation": fit_validation["dataset_draft"][
            "ready_for_lab_internal_validation"
        ],
        "validation_case_id": candidate["validation_case_id"],
        "source_measurement_ref": candidate["source_measurement_ref"],
        "fit_incident_measurement_ref": fit_incident["measurement_ref"].get("record_id"),
        "current_step_output_ref": candidate["source_measurement_ref"],
        "selected_fit_attempt_refs": list(candidate.get("source_fit_attempt_refs", [])),
        "selected_fit_attempts": list(candidate.get("selected_fit_attempts", [])),
    }


def build_fit_continuation_composition_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a side-effect-free composition summary."""

    continuation = build_calibration_continuation_summary(source["continuation_input"])
    fit_validation = build_fit_validation_dataset_summary(source["fit_validation_input"])
    links = source["composition_links"]
    _validate_links(links, continuation, fit_validation)
    attention = _attention(links, continuation, fit_validation)
    return {
        "composition_id": source["fixture_id"] + ".candidate",
        "episode_id": continuation["episode"]["episode_id"],
        "target_group": continuation["episode"]["target_group"],
        "recovery": _recovery_summary(links, fit_validation),
        "continuation_effect": _continuation_effect(links, continuation, attention),
        "validation_preservation": _validation_preservation(links, fit_validation),
        "linked_summary_ids": {
            "continuation": source["continuation_input"]["fixture_id"] + ".candidate",
            "fit_validation": fit_validation["summary_id"],
        },
        "attention": attention,
        "boundary": {
            "summary_posture": "internal_validation_summary",
            "non_claims": [
                "no fit execution",
                "no Scopecat-defined score",
                "no automatic ROI or initial-guess selection",
                "no replay harness",
                "no dataset registry",
                "no GUI workflow",
                "no parameter write-back",
                "no hardware control",
            ],
        },
    }
