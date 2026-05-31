"""Structured summary builder for calibration step observation links.

This module is an experimental production-shaped boundary. It deliberately
links calibration step records to measurement-record summaries by reference
only. It does not read measurement payloads, infer preview metadata, execute
calibration code, fit data, schedule work, retry steps, apply parameter writes,
or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "link_authority": "explicit_calibration_step_observation_links",
    "measurement_record_authority": "measurement_records_own_primary_data",
    "measurement_payload_read": "not_performed",
    "measurement_storage_semantics": "not_defined",
    "preview_inference": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "continuation_decision": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "scheduler": "not_defined",
    "shared_relation_graph": "not_defined",
}

_OBSERVATION_STATES = {
    "linked",
    "missing",
    "unavailable",
}

_SUPPORTED_ROLES = {
    "fit_input",
    "review_evidence",
    "remeasurement_candidate",
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
    policy = source["observation_link_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("observation link policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"observation link policy {key} must be {expected}")


def _step_intents_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_step_intents"], "step_intent_id")


def _step_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_step_records"], "step_record_id")


def _measurement_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurement_record_summaries"], "measurement_record_id")


def _validate_step_intents(source: dict[str, Any]) -> None:
    _step_intents_by_id(source)
    for intent in source["calibration_step_intents"]:
        planned = intent["planned_observation"]
        if planned["kind"] != "measurement_request":
            raise ValueError("planned observation kind must be measurement_request")
        if planned["role"] not in _SUPPORTED_ROLES:
            raise ValueError("unsupported planned observation role")
        if planned["measurement_payload_required"]:
            raise ValueError("planned observation must not require measurement payload reads")


def _validate_measurements(source: dict[str, Any]) -> None:
    _measurement_records_by_id(source)
    for measurement in source["measurement_record_summaries"]:
        if measurement["summary_authority"] != "measurement_record_summary":
            raise ValueError("measurement summaries must come from measurement records")
        if measurement["primary_data_owner"] != "measurement_records":
            raise ValueError("primary data owner must remain measurement_records")


def _validate_observation_link(
    step_record: dict[str, Any],
    link: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
) -> None:
    if link["role"] not in _SUPPORTED_ROLES:
        raise ValueError("unsupported observation role")
    if link["observation_state"] not in _OBSERVATION_STATES:
        raise ValueError("unsupported observation state")
    if link["payload_handling"] != "summary_projection_only":
        raise ValueError("observation link payload handling must stay summary projection only")

    measurement_id = link.get("measurement_record_id")
    if link["observation_state"] == "linked":
        if measurement_id not in measurements:
            raise ValueError(
                f"step record {step_record['step_record_id']} references missing measurement"
            )
        return

    if measurement_id is not None:
        raise ValueError("missing observation must not carry measurement_record_id")
    if not link.get("missing_reason"):
        raise ValueError("missing observation requires a missing_reason")


def _validate_step_records(source: dict[str, Any]) -> None:
    intents = _step_intents_by_id(source)
    measurements = _measurement_records_by_id(source)
    _step_records_by_id(source)
    for record in source["calibration_step_records"]:
        if record["step_intent_id"] not in intents:
            raise ValueError("step record references missing intent")
        seen_links = set()
        for link in record["observation_links"]:
            link_id = link["link_id"]
            if link_id in seen_links:
                raise ValueError(f"duplicate link_id: {link_id}")
            seen_links.add(link_id)
            _validate_observation_link(record, link, measurements)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_step_intents(source)
    _validate_measurements(source)
    _validate_step_records(source)


def _intent_summary(intent: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_intent_id": intent["step_intent_id"],
        "label": intent["label"],
        "target": intent["target"],
        "purpose": intent["purpose"],
        "planned_observation": copy.deepcopy(intent["planned_observation"]),
        "intent_posture": "prospective_observation_need",
    }


def _measurement_projection(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_record_id": measurement["measurement_record_id"],
        "label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "target": measurement["target"],
        "availability": measurement["availability"],
        "preview_status": measurement["preview_status"],
        "source_kind": measurement["source_kind"],
        "summary_authority": measurement["summary_authority"],
        "primary_data_owner": measurement["primary_data_owner"],
    }


def _observation_link_summary(
    step_record: dict[str, Any],
    link: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "step_record_id": step_record["step_record_id"],
        "step_intent_id": step_record["step_intent_id"],
        "link_id": link["link_id"],
        "role": link["role"],
        "observation_state": link["observation_state"],
        "measurement_record_id": link.get("measurement_record_id"),
        "payload_handling": link["payload_handling"],
    }
    measurement = measurements.get(link.get("measurement_record_id"))
    if measurement is not None:
        output["measurement_projection"] = _measurement_projection(measurement)
        output["link_semantics"] = "calibration_step_observed_measurement_reference"
    else:
        output["missing_reason"] = link["missing_reason"]
    return output


def _record_summary(
    record: dict[str, Any], measurements: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    linked_count = sum(
        1 for link in record["observation_links"] if link["observation_state"] == "linked"
    )
    missing_count = sum(
        1 for link in record["observation_links"] if link["observation_state"] != "linked"
    )
    return {
        "step_record_id": record["step_record_id"],
        "step_intent_id": record["step_intent_id"],
        "label": record["label"],
        "target": record["target"],
        "record_state": record["record_state"],
        "observation_link_count": len(record["observation_links"]),
        "linked_measurement_count": linked_count,
        "missing_measurement_count": missing_count,
        "record_posture": "retrospective_observation_summary",
        "observation_links": [
            _observation_link_summary(record, link, measurements)
            for link in record["observation_links"]
        ],
    }


def _missing_observation_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for record in source["calibration_step_records"]:
        for link in record["observation_links"]:
            if link["observation_state"] == "linked":
                continue
            findings.append(
                {
                    "step_record_id": record["step_record_id"],
                    "step_intent_id": record["step_intent_id"],
                    "link_id": link["link_id"],
                    "role": link["role"],
                    "severity": "review",
                    "finding": "measurement_observation_missing",
                    "basis": link["missing_reason"],
                    "does_not_claim": "calibration_step_invalid_or_retry_required",
                }
            )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "measurement_records_own_primary_data",
            "severity": "info",
            "basis": "Calibration step observation links copy only measurement-record summary facts.",
            "does_not_claim": "calibration_owns_measurement_payload",
        },
        {
            "code": "fit_execution_not_performed",
            "severity": "review",
            "basis": "Linked measurements are observation evidence only; no fitting is run.",
            "does_not_claim": "fit_result_or_quality_score",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "Calibration step records are assembled from declared links.",
            "does_not_claim": "measurement_or_calibration_execution",
        },
        {
            "code": "write_back_not_performed",
            "severity": "review",
            "basis": "Observation links do not apply or propose parameter writes.",
            "does_not_claim": "parameter_update",
        },
    ]
    if _missing_observation_findings(source):
        attention.append(
            {
                "code": "measurement_observation_missing",
                "severity": "review",
                "basis": "At least one calibration step has no linked measurement observation.",
                "does_not_claim": "automatic_retry_or_step_failure",
            }
        )
    return attention


def build_calibration_step_observation_link_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a calibration step observation-link summary from explicit facts."""
    _validate_references(source)
    measurements = _measurement_records_by_id(source)
    return {
        "observation_link_policy": copy.deepcopy(source["observation_link_policy"]),
        "calibration_step_intents": [
            _intent_summary(intent) for intent in source["calibration_step_intents"]
        ],
        "measurement_record_summaries": [
            _measurement_projection(measurement)
            for measurement in source["measurement_record_summaries"]
        ],
        "calibration_step_records": [
            _record_summary(record, measurements) for record in source["calibration_step_records"]
        ],
        "missing_observation_findings": _missing_observation_findings(source),
        "attention": _attention(source),
    }
