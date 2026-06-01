"""Structured summary builder for calibration step fit-result links.

This module is an experimental production-shaped boundary. It links calibration
step records to declared fit-result summaries by reference only. It does not
read measurement payloads, execute fitting, score fit quality, select models,
decide continuation, propose or apply writes, emit compatibility output,
schedule work, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "fit_result_authority": "declared_external_fit_result_summaries",
    "step_observation_inputs": "reference_only",
    "measurement_record_authority": "measurement_records_own_primary_data",
    "fit_payload_handling": "summary_only",
    "measurement_payload_read": "not_performed",
    "fit_execution": "not_performed",
    "fit_quality_scoring": "not_performed",
    "model_selection": "not_performed",
    "calibration_execution": "not_performed",
    "continuation_decision": "not_performed",
    "proposed_write_decision": "not_performed",
    "parameter_store_write": "not_performed",
    "hardware_control": "not_performed",
    "external_compatibility_output": "not_produced",
    "scheduler": "not_defined",
    "shared_relation_graph": "not_defined",
}

_FIT_STATES = {
    "declared_success",
    "declared_failed",
    "declared_review_needed",
}

_FIT_REVIEW_STATES = {
    "usable_for_review",
    "needs_human_review",
    "rejected",
}

_PROPOSED_WRITE_REFERENCE_STATES = {
    "referenced_as_declared_evidence",
    "not_referenced",
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
    policy = source["fit_result_link_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("fit result link policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"fit result link policy {key} must be {expected}")


def _step_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["calibration_step_records"], "step_record_id")


def _measurements_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurement_record_summaries"], "measurement_record_id")


def _fit_results_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["fit_result_summaries"], "fit_result_id")


def _observation_links_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    links = {}
    for record in source["calibration_step_records"]:
        for link in record["observation_links"]:
            link_id = link["link_id"]
            if link_id in links:
                raise ValueError(f"duplicate link_id: {link_id}")
            links[link_id] = {
                "step_record_id": record["step_record_id"],
                "step_intent_id": record["step_intent_id"],
                "link": link,
            }
    return links


def _validate_measurements(source: dict[str, Any]) -> None:
    _measurements_by_id(source)
    for measurement in source["measurement_record_summaries"]:
        if measurement["summary_authority"] != "measurement_record_summary":
            raise ValueError("measurement summaries must come from measurement records")
        if measurement["primary_data_owner"] != "measurement_records":
            raise ValueError("primary data owner must remain measurement_records")


def _validate_step_records(source: dict[str, Any]) -> None:
    measurements = _measurements_by_id(source)
    _step_records_by_id(source)
    _observation_links_by_id(source)
    for record in source["calibration_step_records"]:
        for link in record["observation_links"]:
            if link["payload_handling"] != "summary_projection_only":
                raise ValueError("observation links must remain summary projection only")
            if link["observation_state"] != "linked":
                continue
            measurement_id = link.get("measurement_record_id")
            if measurement_id not in measurements:
                raise ValueError("linked observation must reference a known measurement")


def _validate_fit_result(
    fit_result: dict[str, Any],
    step_records: dict[str, dict[str, Any]],
    measurements: dict[str, dict[str, Any]],
    observation_links: dict[str, dict[str, Any]],
) -> None:
    step_record_id = fit_result["step_record_id"]
    if step_record_id not in step_records:
        raise ValueError("fit result references missing step record")
    if fit_result["fit_state"] not in _FIT_STATES:
        raise ValueError("unsupported fit state")
    if fit_result["review_state"] not in _FIT_REVIEW_STATES:
        raise ValueError("unsupported fit review state")
    if fit_result["payload_handling"] != "summary_only":
        raise ValueError("fit result payload handling must stay summary-only")
    if fit_result["execution_posture"] != "externally_produced_declared_summary":
        raise ValueError("fit result execution posture must stay externally produced")
    if fit_result["result_authority"] != "declared_fit_result_summary":
        raise ValueError("fit result authority must remain declared summary")

    for input_ref in fit_result["input_refs"]:
        link_id = input_ref["observation_link_id"]
        if link_id not in observation_links:
            raise ValueError("fit input references missing observation link")
        link_record = observation_links[link_id]
        if link_record["step_record_id"] != step_record_id:
            raise ValueError("fit input observation link belongs to a different step record")
        link = link_record["link"]
        if link["observation_state"] != "linked":
            raise ValueError("fit input observation link must be linked")
        measurement_id = input_ref["measurement_record_id"]
        if measurement_id not in measurements:
            raise ValueError("fit input references missing measurement record")
        if link["measurement_record_id"] != measurement_id:
            raise ValueError("fit input measurement must match observation link measurement")
        if input_ref["payload_handling"] != "reference_only":
            raise ValueError("fit input refs must remain reference-only")

    for estimate in fit_result["parameter_estimates"]:
        if not estimate["parameter_path"]:
            raise ValueError("parameter estimate requires parameter_path")
        if estimate["estimate_posture"] != "declared_summary_only":
            raise ValueError("parameter estimates must remain declared summaries")
        if estimate.get("accepted_for_write") is True:
            raise ValueError("fit result must not accept estimates for write")


def _validate_fit_results(source: dict[str, Any]) -> None:
    step_records = _step_records_by_id(source)
    measurements = _measurements_by_id(source)
    observation_links = _observation_links_by_id(source)
    _fit_results_by_id(source)
    for fit_result in source["fit_result_summaries"]:
        _validate_fit_result(fit_result, step_records, measurements, observation_links)


def _validate_proposed_write_refs(source: dict[str, Any]) -> None:
    step_records = _step_records_by_id(source)
    fit_results = _fit_results_by_id(source)
    _records_by_key(source["proposed_write_evidence_refs"], "write_id")
    for write_ref in source["proposed_write_evidence_refs"]:
        if write_ref["step_record_id"] not in step_records:
            raise ValueError("proposed write evidence references missing step record")
        if write_ref["reference_state"] not in _PROPOSED_WRITE_REFERENCE_STATES:
            raise ValueError("unsupported proposed write reference state")
        if write_ref["apply_state"] != "not_applied":
            raise ValueError("proposed write evidence refs must remain not_applied")
        for fit_result_id in write_ref["fit_result_refs"]:
            if fit_result_id not in fit_results:
                raise ValueError("proposed write references missing fit result")
            if fit_results[fit_result_id]["step_record_id"] != write_ref["step_record_id"]:
                raise ValueError("proposed write fit result belongs to a different step record")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_measurements(source)
    _validate_step_records(source)
    _validate_fit_results(source)
    _validate_proposed_write_refs(source)


def _measurement_projection(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_record_id": measurement["measurement_record_id"],
        "label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "target": measurement["target"],
        "availability": measurement["availability"],
        "preview_status": measurement["preview_status"],
        "summary_authority": measurement["summary_authority"],
        "primary_data_owner": measurement["primary_data_owner"],
    }


def _step_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_record_id": record["step_record_id"],
        "step_intent_id": record["step_intent_id"],
        "label": record["label"],
        "target": record["target"],
        "record_state": record["record_state"],
        "observation_links": copy.deepcopy(record["observation_links"]),
        "record_posture": "retrospective_observation_summary",
    }


def _input_projection(
    input_ref: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    measurement = measurements[input_ref["measurement_record_id"]]
    return {
        "observation_link_id": input_ref["observation_link_id"],
        "measurement_record_id": input_ref["measurement_record_id"],
        "measurement_label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "payload_handling": input_ref["payload_handling"],
        "input_posture": "declared_fit_input_reference",
    }


def _fit_result_posture(fit_result: dict[str, Any]) -> str:
    if fit_result["fit_state"] == "declared_success":
        return "declared_success_available_for_review"
    if fit_result["fit_state"] == "declared_failed":
        return "declared_failure_needs_review"
    return "declared_fit_needs_review"


def _fit_result_summary(
    fit_result: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "fit_result_id": fit_result["fit_result_id"],
        "step_record_id": fit_result["step_record_id"],
        "fit_family": fit_result["fit_family"],
        "fit_state": fit_result["fit_state"],
        "review_state": fit_result["review_state"],
        "result_authority": fit_result["result_authority"],
        "execution_posture": fit_result["execution_posture"],
        "payload_handling": fit_result["payload_handling"],
        "model_ref": fit_result["model_ref"],
        "fit_config_ref": fit_result["fit_config_ref"],
        "code_ref": fit_result["code_ref"],
        "input_refs": [
            _input_projection(input_ref, measurements) for input_ref in fit_result["input_refs"]
        ],
        "parameter_estimates": copy.deepcopy(fit_result["parameter_estimates"]),
        "declared_diagnostics": copy.deepcopy(fit_result["declared_diagnostics"]),
        "fit_result_posture": _fit_result_posture(fit_result),
        "does_not_claim": "fit_execution_or_write_acceptance",
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for fit_result in source["fit_result_summaries"]:
        if (
            fit_result["fit_state"] == "declared_success"
            and fit_result["review_state"] == "usable_for_review"
        ):
            continue
        findings.append(
            {
                "fit_result_id": fit_result["fit_result_id"],
                "step_record_id": fit_result["step_record_id"],
                "severity": "review",
                "finding": "fit_result_needs_review",
                "basis": f"{fit_result['fit_state']} with review state {fit_result['review_state']}",
                "does_not_claim": "automatic_refit_remeasurement_or_write_block",
            }
        )
    return findings


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "fit_results_are_declared_summaries",
            "severity": "info",
            "basis": "Fit-result links copy declared external summary facts only.",
            "does_not_claim": "fit_execution",
        },
        {
            "code": "fit_inputs_are_reference_only",
            "severity": "info",
            "basis": "Fit inputs point at observation links and measurement-record summaries without opening primary data.",
            "does_not_claim": "measurement_payload_read",
        },
        {
            "code": "fit_quality_scoring_not_performed",
            "severity": "review",
            "basis": "Declared diagnostics are surfaced but not interpreted as a scoring policy.",
            "does_not_claim": "scientific_validity_or_quality_score",
        },
        {
            "code": "proposed_write_decision_not_performed",
            "severity": "review",
            "basis": "Fit results may be cited by proposed writes, but this slice does not create or accept writes.",
            "does_not_claim": "write_proposal_acceptance",
        },
        {
            "code": "continuation_decision_not_performed",
            "severity": "review",
            "basis": "Fit review state does not decide retry, skip, remeasurement, or continuation.",
            "does_not_claim": "calibration_workflow_decision",
        },
        {
            "code": "parameter_store_write_not_performed",
            "severity": "review",
            "basis": "Parameter estimates are declared summaries and are never written by this slice.",
            "does_not_claim": "parameter_update_or_hardware_apply",
        },
    ]


def build_calibration_step_fit_result_link_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a calibration step fit-result reference summary from explicit facts."""
    _validate_references(source)
    measurements = _measurements_by_id(source)
    return {
        "fit_result_link_policy": copy.deepcopy(source["fit_result_link_policy"]),
        "calibration_step_records": [
            _step_record_summary(record) for record in source["calibration_step_records"]
        ],
        "measurement_record_summaries": [
            _measurement_projection(measurement)
            for measurement in source["measurement_record_summaries"]
        ],
        "fit_result_summaries": [
            _fit_result_summary(fit_result, measurements)
            for fit_result in source["fit_result_summaries"]
        ],
        "proposed_write_evidence_refs": copy.deepcopy(source["proposed_write_evidence_refs"]),
        "review_findings": _review_findings(source),
        "attention": _attention(source),
    }
