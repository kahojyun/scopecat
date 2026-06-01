"""Structured summary builder for calibration step timeline traces.

This module is an experimental production-shaped boundary. It assembles
declared calibration events into per-step timeline traces and checks timestamp
ordering. It does not schedule work, execute calibration code, run fitting,
read measurement payloads, decide continuation, start parameter-state intake,
emit compatibility output, roll back writes, or control hardware.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

_EXPECTED_POLICY = {
    "trace_authority": "explicit_calibration_step_timeline_trace",
    "event_source": "declared_event_facts",
    "timeline_posture": "read_only_review",
    "moving_reference_handling": "intent_events_only",
    "resolved_snapshot_handling": "step_record_context_events",
    "scheduler": "not_defined",
    "executor": "not_defined",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "fit_quality_scoring": "not_performed",
    "retry_decision": "not_performed",
    "remeasurement_decision": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_state_intake": "not_performed",
    "parameter_state_commit": "not_performed",
    "hardware_control": "not_performed",
    "rollback": "not_defined",
}

_EVENT_ORDER = {
    "intent_created": 10,
    "context_resolved": 20,
    "observation_linked": 30,
    "fit_result_declared": 40,
    "write_proposed": 50,
    "write_reviewed": 60,
    "accepted_handoff_ready": 70,
}

_SUPPORTED_EVENT_KINDS = set(_EVENT_ORDER)

_REFERENCE_SEMANTICS_BY_EVENT_KIND = {
    "intent_created": "moving_selectors_allowed",
    "context_resolved": "resolved_snapshot",
    "observation_linked": "reference_only_observation",
    "fit_result_declared": "declared_summary",
    "write_proposed": "review_only_proposal",
    "write_reviewed": "review_only_acceptance",
    "accepted_handoff_ready": "handoff_only_no_intake",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _parse_timestamp(value: str | None, subject: str) -> datetime | None:
    if value is None:
        return None
    if not value.endswith("Z"):
        raise ValueError(f"{subject} timestamp must be UTC Z")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{subject} timestamp is malformed") from exc


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["timeline_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("timeline policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"timeline policy {key} must be {expected}")


def _steps_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_steps"], "step_record_id")


def _measurement_refs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurement_refs"], "measurement_record_id")


def _fit_results_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["fit_result_refs"], "fit_result_id")


def _proposed_writes_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["proposed_write_refs"], "write_id")


def _handoffs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["accepted_handoff_refs"], "handoff_id")


def _events_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["timeline_events"], "event_id")


def _validate_steps(source: dict[str, Any]) -> None:
    _steps_by_id(source)
    for step in source["calibration_steps"]:
        if step["record_posture"] != "retrospective_step_record":
            raise ValueError("calibration steps must remain retrospective")
        expected = step["expected_event_kinds"]
        if len(expected) != len(set(expected)):
            raise ValueError("expected event kinds must be unique")
        for event_kind in expected:
            if event_kind not in _SUPPORTED_EVENT_KINDS:
                raise ValueError(f"unsupported expected event kind: {event_kind}")


def _validate_entities(source: dict[str, Any]) -> None:
    _measurement_refs_by_id(source)
    _fit_results_by_id(source)
    _proposed_writes_by_id(source)
    _handoffs_by_id(source)
    for measurement in source["measurement_refs"]:
        if measurement["payload_owner"] != "measurement_records":
            raise ValueError("measurement payload owner must remain measurement_records")
    for fit_result in source["fit_result_refs"]:
        if fit_result["execution_posture"] != "declared_external_summary":
            raise ValueError("fit results must remain declared external summaries")
    for write in source["proposed_write_refs"]:
        if write["apply_state"] != "not_applied":
            raise ValueError("proposed writes must remain not_applied")
    for handoff in source["accepted_handoff_refs"]:
        if handoff["parameter_state_intake_state"] != "not_started":
            raise ValueError("parameter-state intake must not start in timeline trace")
        if handoff["apply_state"] != "not_applied":
            raise ValueError("handoff refs must remain not_applied")


def _validate_event_references(
    event: dict[str, Any],
    source: dict[str, Any],
) -> None:
    steps = _steps_by_id(source)
    measurements = _measurement_refs_by_id(source)
    fit_results = _fit_results_by_id(source)
    proposed_writes = _proposed_writes_by_id(source)
    handoffs = _handoffs_by_id(source)

    step_record_id = event["step_record_id"]
    if step_record_id not in steps:
        raise ValueError("timeline event references missing step record")
    refs = event["refs"]
    event_kind = event["event_kind"]

    if event_kind == "intent_created":
        if refs["step_intent_id"] != steps[step_record_id]["step_intent_id"]:
            raise ValueError("intent event must reference step intent")
        if refs["reference_semantics"] != "moving_selectors_allowed":
            raise ValueError("intent event must carry moving selector semantics")
    elif event_kind == "context_resolved":
        if refs["context_resolution_state"] != "resolved_snapshot_recorded":
            raise ValueError("context resolution event must record resolved snapshot")
    elif event_kind == "observation_linked":
        if refs["measurement_record_id"] not in measurements:
            raise ValueError("observation event references missing measurement")
        if refs["payload_handling"] != "reference_only":
            raise ValueError("observation event must remain reference-only")
    elif event_kind == "fit_result_declared":
        fit_result = fit_results.get(refs["fit_result_id"])
        if fit_result is None:
            raise ValueError("fit event references missing fit result")
        if fit_result["step_record_id"] != step_record_id:
            raise ValueError("fit event references fit result from another step")
    elif event_kind in {"write_proposed", "write_reviewed"}:
        write = proposed_writes.get(refs["write_id"])
        if write is None:
            raise ValueError("write event references missing proposed write")
        if write["step_record_id"] != step_record_id:
            raise ValueError("write event references proposed write from another step")
        if event_kind == "write_reviewed" and refs["review_state"] != write["review_state"]:
            raise ValueError("write review event state must match proposed write")
    elif event_kind == "accepted_handoff_ready":
        handoff = handoffs.get(refs["handoff_id"])
        if handoff is None:
            raise ValueError("handoff event references missing handoff")
        if handoff["step_record_id"] != step_record_id:
            raise ValueError("handoff event references handoff from another step")


def _validate_events(source: dict[str, Any]) -> None:
    _events_by_id(source)
    for event in source["timeline_events"]:
        event_kind = event["event_kind"]
        if event_kind not in _SUPPORTED_EVENT_KINDS:
            raise ValueError(f"unsupported event kind: {event_kind}")
        if event["event_source"] != "declared_event_fact":
            raise ValueError("timeline events must be declared event facts")
        if event["action_posture"] != "recorded_not_executed":
            raise ValueError("timeline events must remain recorded-not-executed")
        _parse_timestamp(event["occurred_at"], event["event_id"])
        _validate_event_references(event, source)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_steps(source)
    _validate_entities(source)
    _validate_events(source)


def _events_for_step(source: dict[str, Any], step_record_id: str) -> list[dict[str, Any]]:
    return [
        event for event in source["timeline_events"] if event["step_record_id"] == step_record_id
    ]


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "event_kind": event["event_kind"],
        "occurred_at": event["occurred_at"],
        "sequence": event["sequence"],
        "reference_semantics": _REFERENCE_SEMANTICS_BY_EVENT_KIND[event["event_kind"]],
        "event_source": event["event_source"],
        "action_posture": event["action_posture"],
        "refs": copy.deepcopy(event["refs"]),
    }


def _sorted_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda item: item["sequence"])


def _missing_event_findings(
    step: dict[str, Any], events: list[dict[str, Any]]
) -> list[dict[str, str]]:
    present = {event["event_kind"] for event in events}
    findings = []
    for event_kind in step["expected_event_kinds"]:
        if event_kind not in present:
            findings.append(
                {
                    "step_record_id": step["step_record_id"],
                    "severity": "review",
                    "finding": "timeline_expected_event_missing",
                    "event_kind": event_kind,
                    "basis": "The step declares this event kind as expected but no event was provided.",
                    "does_not_claim": "scheduler_or_executor_action",
                }
            )
    return findings


def _missing_timestamp_findings(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    for event in events:
        if event["occurred_at"] is not None:
            continue
        findings.append(
            {
                "step_record_id": event["step_record_id"],
                "severity": "review",
                "finding": "timeline_event_timestamp_missing",
                "event_id": event["event_id"],
                "event_kind": event["event_kind"],
                "basis": "Declared event has no timestamp.",
                "does_not_claim": "event_invalid_or_action_required",
            }
        )
    return findings


def _out_of_order_findings(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    timed_events = [
        (event, _parse_timestamp(event["occurred_at"], event["event_id"]))
        for event in _sorted_events(events)
        if event["occurred_at"] is not None
    ]
    for index, (event, event_time) in enumerate(timed_events):
        for prior, prior_time in timed_events[:index]:
            if _EVENT_ORDER[event["event_kind"]] <= _EVENT_ORDER[prior["event_kind"]]:
                continue
            if event_time is None or prior_time is None or event_time >= prior_time:
                continue
            findings.append(
                {
                    "step_record_id": event["step_record_id"],
                    "severity": "review",
                    "finding": "timeline_event_out_of_order",
                    "event_id": event["event_id"],
                    "event_kind": event["event_kind"],
                    "prior_event_id": prior["event_id"],
                    "prior_event_kind": prior["event_kind"],
                    "basis": "A later semantic event has an earlier timestamp than a prerequisite event.",
                    "does_not_claim": "scheduler_or_executor_correction",
                }
            )
    return findings


def _step_findings(step: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    findings.extend(_missing_event_findings(step, events))
    findings.extend(_missing_timestamp_findings(events))
    findings.extend(_out_of_order_findings(events))
    return findings


def _timeline_status(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "timeline_order_review_ready"
    if any(finding["finding"] == "timeline_event_out_of_order" for finding in findings):
        return "timeline_order_needs_review"
    if any(finding["finding"] == "timeline_event_timestamp_missing" for finding in findings):
        return "timeline_timestamps_need_review"
    return "timeline_events_incomplete"


def _step_trace(source: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    events = _events_for_step(source, step["step_record_id"])
    findings = _step_findings(step, events)
    return {
        "step_record_id": step["step_record_id"],
        "step_intent_id": step["step_intent_id"],
        "target": step["target"],
        "expected_event_kinds": list(step["expected_event_kinds"]),
        "event_count": len(events),
        "events": [_event_summary(event) for event in _sorted_events(events)],
        "timeline_status": _timeline_status(findings),
        "trace_posture": "read_only_temporal_review",
    }


def _step_traces(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [_step_trace(source, step) for step in source["calibration_steps"]]


def _timeline_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for step in source["calibration_steps"]:
        findings.extend(_step_findings(step, _events_for_step(source, step["step_record_id"])))
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "timeline_is_declared_review_data",
            "severity": "info",
            "basis": "Events are declared facts and are not scheduled or executed by this slice.",
            "does_not_claim": "scheduler_or_executor",
        },
        {
            "code": "moving_references_stop_at_intent",
            "severity": "info",
            "basis": "Intent-created events may mention moving selectors; context-resolved events record snapshots.",
            "does_not_claim": "live_context_reference_on_step_record",
        },
        {
            "code": "measurement_payload_not_read",
            "severity": "review",
            "basis": "Observation events reference measurement records only.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "Fit-result events reference declared fit summaries only.",
            "does_not_claim": "fit_execution_or_quality_scoring",
        },
        {
            "code": "continuation_decision_not_performed",
            "severity": "review",
            "basis": "Timeline findings do not decide retry, remeasurement, or continuation.",
            "does_not_claim": "calibration_workflow_decision",
        },
        {
            "code": "parameter_state_intake_not_started",
            "severity": "review",
            "basis": "Accepted handoff events remain visible but do not start parameter-state intake.",
            "does_not_claim": "parameter_state_draft_or_commit",
        },
    ]


def build_calibration_step_timeline_trace_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build read-only calibration step timeline traces from declared events."""
    _validate_references(source)
    return {
        "timeline_policy": copy.deepcopy(source["timeline_policy"]),
        "calibration_steps": copy.deepcopy(source["calibration_steps"]),
        "measurement_refs": copy.deepcopy(source["measurement_refs"]),
        "fit_result_refs": copy.deepcopy(source["fit_result_refs"]),
        "proposed_write_refs": copy.deepcopy(source["proposed_write_refs"]),
        "accepted_handoff_refs": copy.deepcopy(source["accepted_handoff_refs"]),
        "step_traces": _step_traces(source),
        "timeline_findings": _timeline_findings(source),
        "attention": _attention(source),
    }
