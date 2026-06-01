"""Route-level continuity for calibration-derived parameter-state context."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "route_authority": "declared_cross_route_composition",
    "calibration_source": "calibration_observation_and_accepted_write_handoff_summaries",
    "parameter_state_source": "calibration_parameter_state_intake_and_storage_summaries",
    "prepared_run_source": "prepared_run_parameter_state_consumption_summary",
    "measurement_context_source": "explicit_measurement_record_context_links",
    "payload_handling": "reference_and_summary_facts_only",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "calibration_execution": "not_performed",
    "fresh_storage_read": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "compatibility_output": "not_produced",
    "recursive_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "shared_route_schema": "not_defined",
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
    policy = source["route_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("calibration-derived parameter-state route policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"calibration-derived parameter-state route policy {key} must be {expected}"
            )


def _selected_parameter_ref(prepared_run: dict[str, Any]) -> dict[str, Any]:
    refs = [
        ref
        for ref in prepared_run["selected_context_refs"]
        if ref["family"] == "parameter_state" and ref["role"] == "calibrated_values"
    ]
    if len(refs) != 1:
        raise ValueError("prepared run must select exactly one calibrated parameter state")
    ref = refs[0]
    if not ref["required"]:
        raise ValueError("prepared-run parameter-state context must remain required")
    if ref["include_state"] != "selected":
        raise ValueError("prepared-run parameter-state context must be selected")
    return ref


def _measurement_parameter_link(
    measurement_context: dict[str, Any], measurement_id: str
) -> dict[str, Any]:
    refs = [
        ref
        for ref in measurement_context["linked_context_refs"]
        if ref["measurement_record_id"] == measurement_id
        and ref["family"] == "parameter_state"
        and ref["role"] == "calibrated_values"
    ]
    if len(refs) != 1:
        raise ValueError("measurement record must link exactly one calibrated parameter state")
    ref = refs[0]
    if ref["include_state"] != "linked":
        raise ValueError("measurement parameter context link must be linked")
    if ref["required_for_record_validity"]:
        raise ValueError("measurement context must remain optional for record validity")
    return ref


def _validate_calibration_chain(source: dict[str, Any]) -> None:
    observation = source["calibration_observation_summary"]
    handoff = source["accepted_write_handoff_summary"]
    if handoff["step_record_id"] != observation["step_record_id"]:
        raise ValueError("accepted write handoff must match calibration step record")
    if handoff["observation_measurement_record_id"] != observation["measurement_record_id"]:
        raise ValueError("accepted write handoff must preserve observation measurement record")
    if handoff["handoff_state"] != "ready_for_parameter_state_review":
        raise ValueError("accepted write handoff must be ready for parameter-state review")
    if handoff["apply_state"] != "not_applied":
        raise ValueError("accepted write handoff must not imply hardware apply")


def _validate_parameter_state_chain(source: dict[str, Any]) -> None:
    handoff = source["accepted_write_handoff_summary"]
    intake = source["parameter_state_intake_summary"]
    storage = source["stored_parameter_state_summary"]
    state = intake["managed_parameter_state"]
    if intake["source_handoff"]["handoff_id"] != handoff["handoff_id"]:
        raise ValueError("parameter-state intake must consume accepted handoff")
    if state["source_handoff_id"] != handoff["handoff_id"]:
        raise ValueError("managed parameter state must preserve handoff provenance")
    if state["base_state_id"] != handoff["base_state_id"]:
        raise ValueError("managed parameter state must preserve base state identity")
    if state["lineage_id"] != handoff["lineage_id"]:
        raise ValueError("managed parameter state must preserve lineage identity")
    if handoff["parameter_path"] not in state["trusted_entry_paths"]:
        raise ValueError("managed parameter state must include accepted write path")
    if storage["state_id"] != state["state_id"]:
        raise ValueError("stored parameter state must match intake managed state")
    if storage["source_kind"] != "calibration_handoff":
        raise ValueError("stored parameter state must remain calibration-derived")
    if storage["source_handoff_id"] != handoff["handoff_id"]:
        raise ValueError("stored parameter state must preserve handoff id")


def _validate_prepared_run_and_measurement(source: dict[str, Any]) -> None:
    intake = source["parameter_state_intake_summary"]
    storage = source["stored_parameter_state_summary"]
    prepared_run = source["prepared_run_context_summary"]
    consumption = source["prepared_run_parameter_state_consumption_summary"]
    measurement_context = source["measurement_context_link_summary"]

    state_id = intake["managed_parameter_state"]["state_id"]
    selected_ref = _selected_parameter_ref(prepared_run)
    if selected_ref["context_id"] != state_id:
        raise ValueError("prepared run must select the calibration-derived parameter state")
    if consumption["parameter_state"]["state_id"] != state_id:
        raise ValueError("prepared-run consumption must use selected parameter state")
    if consumption["parameter_state"]["source_kind"] != storage["source_kind"]:
        raise ValueError("prepared-run consumption must preserve source kind")
    if consumption["parameter_state"]["storage_reference"]["state_id"] != storage["state_id"]:
        raise ValueError("prepared-run consumption must reference stored parameter state")

    prepared_measurement_id = prepared_run["manual_run_target"]["measurement_id"]
    if consumption["prepared_run_context"]["measurement_id"] != prepared_measurement_id:
        raise ValueError("prepared-run consumption must preserve target measurement id")
    measurement_link = _measurement_parameter_link(measurement_context, prepared_measurement_id)
    if measurement_link["context_id"] != state_id:
        raise ValueError("measurement record must link selected parameter state")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_calibration_chain(source)
    _validate_parameter_state_chain(source)
    _validate_prepared_run_and_measurement(source)


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    prepared_run = source["prepared_run_parameter_state_consumption_summary"]
    measurement_context = source["measurement_context_link_summary"]
    if prepared_run["review_findings"]:
        findings.extend(
            {"source": "prepared_run_parameter_state_consumption", **finding}
            for finding in prepared_run["review_findings"]
        )
    missing_optional = measurement_context.get("optional_context_findings", [])
    findings.extend(
        {"source": "measurement_context_link", **finding} for finding in missing_optional
    )
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "calibration_evidence_preserved_as_provenance",
            "severity": "info",
            "basis": "The later parameter-state snapshot keeps the accepted calibration handoff as provenance.",
            "does_not_claim": "calibration_payload_import_or_fit_execution",
        },
        {
            "code": "selected_snapshot_is_canonical_parameter_context",
            "severity": "review",
            "basis": "The prepared run and later measurement record reference the same managed parameter-state snapshot.",
            "does_not_claim": "compatibility_artifact_authority",
        },
        {
            "code": "measurement_context_remains_optional",
            "severity": "info",
            "basis": "The measurement record can link selected parameter context without making context required for primary-data validity.",
            "does_not_claim": "measurement_invalid_without_context",
        },
        {
            "code": "route_composition_only",
            "severity": "review",
            "basis": "The slice validates declared summary continuity and does not execute child workflows.",
            "does_not_claim": "shared_schema_runner_or_hardware_safety",
        },
    ]


def build_calibration_derived_parameter_state_measurement_context_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a read-only continuity summary for the cross-route trunk."""
    _validate_references(source)
    observation = source["calibration_observation_summary"]
    handoff = source["accepted_write_handoff_summary"]
    state = source["parameter_state_intake_summary"]["managed_parameter_state"]
    storage = source["stored_parameter_state_summary"]
    prepared_run = source["prepared_run_context_summary"]
    measurement_context = source["measurement_context_link_summary"]
    measurement_id = prepared_run["manual_run_target"]["measurement_id"]
    measurement_records = _records_by_key(
        measurement_context["measurement_records"], "measurement_record_id"
    )
    measurement_link = _measurement_parameter_link(measurement_context, measurement_id)
    findings = _review_findings(source)
    return {
        "route_policy": copy.deepcopy(source["route_policy"]),
        "classification": (
            "calibration_derived_parameter_state_selected_for_later_measurement_context"
            if not findings
            else "calibration_derived_parameter_state_context_needs_review"
        ),
        "calibration_source": {
            "step_record_id": observation["step_record_id"],
            "observation_measurement_record_id": observation["measurement_record_id"],
            "observation_link_id": observation["observation_link_id"],
            "accepted_handoff_id": handoff["handoff_id"],
            "accepted_parameter_path": handoff["parameter_path"],
        },
        "parameter_state_transition": {
            "base_state_id": handoff["base_state_id"],
            "managed_state_id": state["state_id"],
            "lineage_id": state["lineage_id"],
            "source_handoff_id": state["source_handoff_id"],
            "stored_state_id": storage["state_id"],
            "source_kind": storage["source_kind"],
            "trusted_entry_count": len(state["trusted_entry_paths"]),
        },
        "prepared_run_context": {
            "prepared_run_context_id": prepared_run["prepared_run_context_id"],
            "measurement_id": measurement_id,
            "selected_parameter_state_id": state["state_id"],
            "logical_targets": list(prepared_run["manual_run_target"]["logical_targets"]),
        },
        "measurement_record_context": {
            "measurement_record_id": measurement_id,
            "measurement_label": measurement_records[measurement_id]["label"],
            "parameter_context_link_id": measurement_link["link_id"],
            "linked_parameter_state_id": measurement_link["context_id"],
            "context_policy": measurement_records[measurement_id]["context_policy"],
        },
        "continuity_checks": [
            "calibration_observation_to_accepted_write_handoff",
            "accepted_handoff_to_parameter_state_intake",
            "parameter_state_intake_to_stored_snapshot",
            "stored_snapshot_to_prepared_run_selection",
            "prepared_run_selection_to_measurement_context_link",
        ],
        "review_findings": findings,
        "attention": _attention(),
    }
