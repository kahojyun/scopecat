"""Input contract summary for the calibration continuation route.

This module is an experimental production-shaped boundary. It validates
declared route input facts and projects readiness for a future route shape. It
does not read referenced payloads, execute calibration or fit code, score
results, write parameters, schedule work, replay cases, create dataset
registry entries, render a GUI, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

SUPPORTED_FAMILIES = {
    "calibration_work_continuation_summary",
    "fit_recovery_interaction_summary",
    "fit_recovery_review_state_summary",
    "measurement_preview_refs",
    "parameter_state_ref",
    "prepared_run_context_ref",
    "setup_binding_ref",
    "validation_dataset_draft_ref",
}

SUPPORTED_INCLUDE_STATES = {
    "selected",
    "unavailable",
    "reference_only",
    "optional_not_selected",
}

SUPPORTED_REQUIRED_FOR = {
    "route_render",
    "review_quality",
    "reference_context",
    "optional_context",
}

MINIMUM_ROUTE_INPUTS = {
    "calibration_work_continuation_summary",
    "fit_recovery_interaction_summary",
}

ALLOWED_ROUTE_INPUT_KEYS = {
    "input_id",
    "order",
    "family",
    "role",
    "required_for",
    "include_state",
    "owner",
    "reference",
    "missing_reason",
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
    policy = source["route_input_policy"]
    expected = {
        "route_authority": "input_contract_projection_only",
        "input_source": "declared_fixture_records",
        "payload_handling": "references_only",
        "upstream_productization_required": "not_required",
        "hardware_control": "not_performed",
        "fit_execution": "not_performed",
        "parameter_write_back": "not_performed",
        "public_export": "not_performed",
    }
    if set(policy) != set(expected):
        raise ValueError("route input policy must match the expected policy shape")
    for key, expected_value in expected.items():
        if policy[key] != expected_value:
            raise ValueError(f"route input policy {key} must be {expected_value}")


def _validate_route_input(route_input: dict[str, Any]) -> None:
    extra_keys = set(route_input) - ALLOWED_ROUTE_INPUT_KEYS
    if extra_keys:
        raise ValueError(f"unsupported route input field: {sorted(extra_keys)[0]}")
    family = route_input["family"]
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(f"unsupported route input family: {family}")
    include_state = route_input["include_state"]
    if include_state not in SUPPORTED_INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")
    required_for = route_input["required_for"]
    if required_for not in SUPPORTED_REQUIRED_FOR:
        raise ValueError(f"unsupported required_for: {required_for}")
    reference = route_input.get("reference")
    if include_state in {"selected", "reference_only"} and not reference:
        raise ValueError("selected or reference-only route input requires reference")
    if include_state in {"unavailable", "optional_not_selected"} and reference is not None:
        raise ValueError("unavailable or optional route input must not carry reference")
    if include_state == "unavailable" and not route_input.get("missing_reason"):
        raise ValueError("unavailable route input requires missing_reason")
    if required_for == "route_render" and family not in MINIMUM_ROUTE_INPUTS:
        raise ValueError("route_render input must be a minimum route input family")
    if required_for == "route_render" and include_state == "reference_only":
        raise ValueError("route_render input cannot be reference_only")
    if family in MINIMUM_ROUTE_INPUTS and required_for != "route_render":
        raise ValueError("minimum route input family must be required for route_render")
    if required_for == "reference_context" and include_state not in {
        "reference_only",
        "unavailable",
    }:
        raise ValueError("reference_context input must be reference_only or unavailable")
    if include_state == "optional_not_selected" and required_for != "optional_context":
        raise ValueError("optional_not_selected input must be optional_context")


def _validate_current_step_alignment(source: dict[str, Any], route_input: dict[str, Any]) -> None:
    if route_input["family"] != "calibration_work_continuation_summary":
        return
    if route_input["include_state"] != "selected":
        return
    reference = route_input["reference"]
    current_step = source["route_context"]["current_step_id"]
    if reference.get("current_step_id") != current_step:
        raise ValueError("route context current_step_id does not match continuation reference")
    step_ids = reference.get("step_ids", [])
    if current_step not in step_ids:
        raise ValueError("continuation reference does not include route current_step_id")


def _validate_source(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _records_by_key(source["route_inputs"], "input_id")
    seen_roles = set()
    families = set()
    for route_input in source["route_inputs"]:
        role_key = (route_input["family"], route_input["role"])
        if role_key in seen_roles:
            raise ValueError("duplicate route input family role")
        seen_roles.add(role_key)
        families.add(route_input["family"])
        _validate_route_input(route_input)
        _validate_current_step_alignment(source, route_input)
    missing_minimum = MINIMUM_ROUTE_INPUTS - families
    if missing_minimum:
        raise ValueError(f"missing minimum route input: {sorted(missing_minimum)[0]}")


def _input_state(route_input: dict[str, Any]) -> str:
    include_state = route_input["include_state"]
    required_for = route_input["required_for"]
    if include_state == "selected":
        return "available"
    if include_state == "reference_only":
        return "reference_only"
    if include_state == "optional_not_selected":
        return "optional_not_selected"
    if required_for == "route_render":
        return "missing_route_render_input"
    if required_for == "review_quality":
        return "missing_supporting_input"
    return "reference_unavailable"


def _input_summary(route_input: dict[str, Any]) -> dict[str, Any]:
    output = {
        "input_id": route_input["input_id"],
        "family": route_input["family"],
        "role": route_input["role"],
        "required_for": route_input["required_for"],
        "include_state": route_input["include_state"],
        "state": _input_state(route_input),
        "owner": route_input["owner"],
    }
    if "reference" in route_input:
        output["reference"] = copy.deepcopy(route_input["reference"])
    if "missing_reason" in route_input:
        output["missing_reason"] = route_input["missing_reason"]
    return output


def _missing_context(route_inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for route_input in route_inputs:
        if route_input["include_state"] != "unavailable":
            continue
        if route_input["required_for"] not in {"route_render", "review_quality"}:
            continue
        findings.append(
            {
                "code": "route_input_unavailable",
                "input_id": route_input["input_id"],
                "family": route_input["family"],
                "required_for": route_input["required_for"],
                "severity": "blocking"
                if route_input["required_for"] == "route_render"
                else "review",
                "message": route_input["missing_reason"],
                "does_not_claim": "upstream_productization_required",
            }
        )
    return findings


def _attention(
    route_inputs: list[dict[str, Any]], missing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    findings = copy.deepcopy(missing)
    for route_input in route_inputs:
        if route_input["include_state"] == "reference_only":
            findings.append(
                {
                    "code": "route_input_reference_only",
                    "input_id": route_input["input_id"],
                    "family": route_input["family"],
                    "severity": "info",
                    "message": "Route carries this input as an owned-by-other-slice reference.",
                    "does_not_claim": "reference_payload_observed",
                }
            )
        if route_input["include_state"] == "optional_not_selected":
            findings.append(
                {
                    "code": "optional_route_input_not_selected",
                    "input_id": route_input["input_id"],
                    "family": route_input["family"],
                    "severity": "info",
                    "message": route_input.get(
                        "missing_reason", "Optional route input is not selected."
                    ),
                    "does_not_claim": "route_blocked",
                }
            )
        if (
            route_input["include_state"] == "unavailable"
            and route_input["required_for"] == "reference_context"
        ):
            findings.append(
                {
                    "code": "route_reference_unavailable",
                    "input_id": route_input["input_id"],
                    "family": route_input["family"],
                    "severity": "info",
                    "message": route_input["missing_reason"],
                    "does_not_claim": "route_blocked",
                }
            )
    return findings


def _route_readiness(
    route_inputs: list[dict[str, Any]], missing: list[dict[str, Any]]
) -> dict[str, Any]:
    minimum = [
        route_input for route_input in route_inputs if route_input["family"] in MINIMUM_ROUTE_INPUTS
    ]
    unavailable_minimum = [
        route_input["input_id"]
        for route_input in minimum
        if route_input["include_state"] != "selected"
    ]
    supporting_missing = [
        finding["input_id"] for finding in missing if finding["required_for"] == "review_quality"
    ]
    if unavailable_minimum:
        state = "minimum_contract_missing"
    elif supporting_missing:
        state = "minimum_contract_satisfied_with_attention"
    else:
        state = "minimum_contract_satisfied"
    return {
        "state": state,
        "minimum_route_available": not unavailable_minimum,
        "unavailable_minimum_input_ids": unavailable_minimum,
        "missing_supporting_input_ids": supporting_missing,
    }


def build_calibration_continuation_route_input_contract_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a side-effect-free calibration route input contract summary."""

    _validate_source(source)
    route_inputs = sorted(source["route_inputs"], key=lambda item: item["order"])
    missing = _missing_context(route_inputs)
    return {
        "summary_id": source["fixture_id"] + ".candidate",
        "route_context": copy.deepcopy(source["route_context"]),
        "input_contract": [_input_summary(route_input) for route_input in route_inputs],
        "route_readiness": _route_readiness(route_inputs, missing),
        "missing_context": missing,
        "attention": _attention(route_inputs, missing),
        "boundary": {
            "summary_posture": "internal_validation_summary",
            "non_claims": [
                "no GUI implementation",
                "no notebook integration",
                "no calibration execution",
                "no fit execution",
                "no fit model selection",
                "no Scopecat-defined score",
                "no measurement payload read",
                "no reference resolution",
                "no automatic ROI or initial-guess selection",
                "no automatic outlier rejection",
                "no automatic remeasurement, retry, retune, or optimization",
                "no parameter write-back",
                "no local executor or notebook execution",
                "no runner design",
                "no remote execution",
                "no replay harness",
                "no dataset registry",
                "no portable/public dataset package",
                "no handoff artifact",
                "no lab-sharing bundle",
                "no hardware control",
            ],
        },
    }
