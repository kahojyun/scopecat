"""Review-only action recording for calibration continuation surfaces."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_EXPECTED_POLICY = {
    "recording_authority": "declared_calibration_review_action_events",
    "surface_source": "calibration_continuation_review_surface_summary",
    "event_posture": "review_audit_intent_only",
    "action_source": "surface_action_palette_labels",
    "payload_handling": "labels_reasons_and_refs_only",
    "rendering": "not_performed",
    "gui_workflow": "not_defined",
    "notebook_execution": "not_performed",
    "action_execution": "not_performed",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "storage_mutation": "not_performed",
    "shared_action_schema": "not_defined",
}

_FORBIDDEN_KEYS = {
    "command",
    "callback",
    "notebook_cell",
    "gui_event",
    "executable",
    "hardware_session",
    "parameter_write",
    "measurement_payload",
    "fit_payload",
    "storage_write",
    "run_start",
}

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class CalibrationReviewActionRecordingRequest:
    """Typed edge for review-only action events."""

    source: dict[str, Any]

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> CalibrationReviewActionRecordingRequest:
        request = cls(copy.deepcopy(source))
        _validate_references(request.source)
        return request


@dataclass(frozen=True)
class CalibrationReviewActionRecordingResult:
    """Route-local review action recording projection."""

    action_recording_policy: dict[str, Any]
    surface_ref: dict[str, Any]
    recorded_event_count: int
    recorded_events: list[dict[str, Any]]
    event_counts_by_source: dict[str, int]
    recording_classification: str
    attention: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_recording_policy": copy.deepcopy(self.action_recording_policy),
            "surface_ref": copy.deepcopy(self.surface_ref),
            "recorded_event_count": self.recorded_event_count,
            "recorded_events": copy.deepcopy(self.recorded_events),
            "event_counts_by_source": copy.deepcopy(self.event_counts_by_source),
            "recording_classification": self.recording_classification,
            "attention": copy.deepcopy(self.attention),
        }


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _reject_forbidden_keys(value: Any, path: str = "source") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _FORBIDDEN_KEYS:
                raise ValueError(f"review action recording input must not include {key} at {path}")
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["action_recording_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("calibration review action recording policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"calibration review action recording policy {key} must be {expected}")


def _palette_by_key(surface: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    output = {}
    for action in surface["action_palette"]:
        if action["posture"] != "labels_only_not_executed":
            raise ValueError("surface action palette must remain labels-only")
        key = (action["source"], action["target_id"], action["action_label"])
        if key in output:
            raise ValueError(f"duplicate action palette label: {key}")
        output[key] = action
    return output


def _validate_surface(source: dict[str, Any]) -> None:
    surface = source["review_surface_summary"]
    if surface["surface_policy"]["action_execution"] != "not_performed":
        raise ValueError("review surface must not execute actions")
    if surface["surface_policy"]["notebook_execution"] != "not_performed":
        raise ValueError("review surface must not execute notebook cells")
    _palette_by_key(surface)


def _ordered_events(source: dict[str, Any]) -> list[dict[str, Any]]:
    events = sorted(source["action_events"], key=lambda event: event["order"])
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
    return events


def _validate_event(
    event: dict[str, Any], palette: dict[tuple[str, str, str], dict[str, Any]]
) -> None:
    if event["event_type"] != "record_review_action_choice":
        raise ValueError("unsupported review action event type")
    if not _ISO_UTC.match(event["recorded_at"]):
        raise ValueError("review action recorded_at must be UTC second timestamp")
    if event["event_posture"] != "review_audit_intent_only":
        raise ValueError("review action event posture must remain audit intent only")
    if event["execution_state"] != "not_executed":
        raise ValueError("review action event must not execute")
    if not event["actor_ref"]:
        raise ValueError("review action event requires actor_ref")
    if not event["reason"]:
        raise ValueError("review action event requires reason")
    key = (event["surface_action_source"], event["target_id"], event["action_label"])
    if key not in palette:
        raise ValueError("review action event must reference an available surface action label")


def _validate_events(source: dict[str, Any]) -> None:
    palette = _palette_by_key(source["review_surface_summary"])
    _records_by_key(source["action_events"], "event_id")
    for event in _ordered_events(source):
        _validate_event(event, palette)


def _validate_references(source: dict[str, Any]) -> None:
    _reject_forbidden_keys(source)
    _validate_policy(source)
    _validate_surface(source)
    _validate_events(source)


def _recorded_events(source: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for event in _ordered_events(source):
        output.append(
            {
                "event_id": event["event_id"],
                "order": event["order"],
                "recorded_at": event["recorded_at"],
                "actor_ref": event["actor_ref"],
                "source": event["surface_action_source"],
                "target_id": event["target_id"],
                "action_label": event["action_label"],
                "reason": event["reason"],
                "event_posture": event["event_posture"],
                "execution_state": event["execution_state"],
            }
        )
    return output


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        source = event["source"]
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "actions_are_recorded_not_executed",
            "severity": "review",
            "basis": "Recorded events bind user intent to surface labels only.",
            "does_not_claim": "action_execution",
        },
        {
            "code": "surface_labels_are_authority",
            "severity": "info",
            "basis": "Events must reference labels already exposed by the review surface.",
            "does_not_claim": "freeform_command_api",
        },
        {
            "code": "workflow_state_not_mutated",
            "severity": "review",
            "basis": "Recording a user choice does not repair context, write parameters, or start runs.",
            "does_not_claim": "workflow_mutation",
        },
    ]


def record_calibration_review_actions(
    request: CalibrationReviewActionRecordingRequest,
) -> CalibrationReviewActionRecordingResult:
    """Record review action choices without executing the labels."""
    source = request.source
    events = _recorded_events(source)
    surface = source["review_surface_summary"]
    return CalibrationReviewActionRecordingResult(
        action_recording_policy=copy.deepcopy(source["action_recording_policy"]),
        surface_ref={
            "surface_id": surface["surface_request"]["surface_id"],
            "route_id": surface["surface_request"]["route_id"],
            "surface_state": surface["route_header"]["surface_state"],
        },
        recorded_event_count=len(events),
        recorded_events=events,
        event_counts_by_source=_event_counts(events),
        recording_classification="review_action_choices_recorded_without_execution",
        attention=_attention(),
    )


def build_calibration_review_action_recording_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for current fixture and edge callers."""
    request = CalibrationReviewActionRecordingRequest.from_dict(source)
    return record_calibration_review_actions(request).to_dict()
