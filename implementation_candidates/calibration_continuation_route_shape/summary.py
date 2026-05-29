"""Static route-shape projection for calibration continuation.

This module is an experimental production-shaped boundary. It projects an
already-built route input contract plus fixture-declared route cards into a
static route shape a later product prototype could render. It does not render a
GUI, execute calibration or fit code, read referenced payloads, select ROIs,
generate initial guesses, replay cases, create dataset registry entries, write
parameters, schedule work, or control hardware.
"""

from __future__ import annotations

import copy
from typing import Any

SUPPORTED_ROUTE_SHAPE_KINDS = {"calibration_continuation"}
SUPPORTED_CARD_STATES = {"requires_remeasurement", "can_continue"}
SUPPORTED_DATASET_PROMPT_STATES = {
    "not_offered_remeasure_first",
    "offered_lab_internal_validation_case",
}
SUPPORTED_ROUTE_READINESS_STATES = {
    "minimum_contract_satisfied",
    "minimum_contract_satisfied_with_attention",
}
ALLOWED_CARD_KEYS = {
    "incident_id",
    "order",
    "title",
    "signal_classification",
    "route_state",
    "can_continue",
    "primary_user_action",
    "dataset_prompt",
}
ALLOWED_PRIMARY_ACTION_KEYS = {"action", "label", "source"}
ALLOWED_DATASET_PROMPT_KEYS = {
    "state",
    "enabled",
    "label",
    "selected",
    "case_ref",
    "reason",
}
ROUTE_STATE_RULES = {
    "requires_remeasurement": {
        "signal_classification": "no_clear_signal",
        "primary_action": "adjust_parameters_and_remeasure",
        "dataset_prompt_state": "not_offered_remeasure_first",
        "can_continue": False,
        "dataset_enabled": False,
        "dataset_selected": False,
        "case_ref_required": False,
    },
    "can_continue": {
        "signal_classification": "visible_signal",
        "primary_action": "continue_after_user_refit",
        "dataset_prompt_state": "offered_lab_internal_validation_case",
        "can_continue": True,
        "dataset_enabled": True,
        "dataset_selected": True,
        "case_ref_required": True,
    },
}
FORBIDDEN_PAYLOAD_KEYS = {
    "gui_component",
    "notebook_execution",
    "runner_log",
    "fit_results",
    "measurement_payload",
    "reference_payloads",
    "parameter_write",
    "hardware_session",
    "dataset_package",
    "lab_sharing_bundle",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _reject_forbidden_payloads(value: Any, path: str = "source") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(f"route shape input must not include {key} at {path}")
            _reject_forbidden_payloads(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_payloads(child, f"{path}[{index}]")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["route_shape_policy"]
    expected = {
        "route_authority": "static_route_shape_projection",
        "input_source": "route_input_contract_summary",
        "route_cards": "fixture_declared",
        "payload_handling": "references_and_display_facts_only",
        "gui_rendering": "not_performed",
        "fit_execution": "not_performed",
        "parameter_write_back": "not_performed",
        "public_export": "not_performed",
    }
    if set(policy) != set(expected):
        raise ValueError("route shape policy must match the expected policy shape")
    for key, expected_value in expected.items():
        if policy[key] != expected_value:
            raise ValueError(f"route shape policy {key} must be {expected_value}")


def _contract_inputs(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(contract["input_contract"], "input_id")


def _family_inputs(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(contract["input_contract"], "family")


def _fit_interaction_reference(contract: dict[str, Any]) -> dict[str, Any]:
    fit_input = _family_inputs(contract)["fit_recovery_interaction_summary"]
    if fit_input["include_state"] != "selected":
        raise ValueError("route shape requires selected fit recovery interaction summary")
    return fit_input["reference"]


def _validate_current_step_alignment(contract: dict[str, Any]) -> None:
    current_step = contract["route_context"]["current_step_id"]
    continuation = _family_inputs(contract)["calibration_work_continuation_summary"]
    reference = continuation["reference"]
    if reference.get("current_step_id") != current_step:
        raise ValueError("route shape current_step_id does not match continuation reference")
    if current_step not in reference.get("step_ids", []):
        raise ValueError("route shape continuation reference omits current_step_id")


def _validate_contract(contract: dict[str, Any]) -> None:
    boundary = contract["boundary"]
    if boundary.get("summary_posture") != "internal_validation_summary":
        raise ValueError("route shape requires internal route input contract summary")
    readiness = contract["route_readiness"]
    if readiness["state"] not in SUPPORTED_ROUTE_READINESS_STATES:
        raise ValueError(f"unsupported route readiness state: {readiness['state']}")
    if not readiness["minimum_route_available"]:
        raise ValueError("route shape requires available minimum route contract")
    if readiness["unavailable_minimum_input_ids"]:
        raise ValueError("route shape cannot render with unavailable minimum inputs")
    missing_supporting = readiness["missing_supporting_input_ids"]
    if readiness["state"] == "minimum_contract_satisfied" and missing_supporting:
        raise ValueError("route readiness state conflicts with missing supporting inputs")
    if readiness["state"] == "minimum_contract_satisfied_with_attention" and not (
        missing_supporting or contract["attention"]
    ):
        raise ValueError("route readiness attention state requires attention context")
    families = _family_inputs(contract)
    for family in [
        "calibration_work_continuation_summary",
        "fit_recovery_interaction_summary",
    ]:
        if families[family]["state"] != "available":
            raise ValueError(f"minimum route input is not available: {family}")
    _validate_current_step_alignment(contract)


def _incident_outcomes(fit_interaction_reference: dict[str, Any]) -> dict[str, str]:
    outcomes = fit_interaction_reference.get("incident_outcomes")
    if not outcomes:
        raise ValueError("fit interaction reference requires incident_outcomes")
    return {item["incident_id"]: item["route_state"] for item in outcomes}


def _reject_extra_keys(record: dict[str, Any], allowed: set[str], label: str) -> None:
    extra_keys = set(record) - allowed
    if extra_keys:
        raise ValueError(f"unsupported {label} field: {sorted(extra_keys)[0]}")


def _validate_card(card: dict[str, Any], incident_outcomes: dict[str, str]) -> None:
    _reject_extra_keys(card, ALLOWED_CARD_KEYS, "route card")
    route_state = card["route_state"]
    if route_state not in SUPPORTED_CARD_STATES:
        raise ValueError(f"unsupported route card state: {route_state}")
    incident_id = card["incident_id"]
    if incident_id not in incident_outcomes:
        raise ValueError(f"route card incident is not declared by fit interaction: {incident_id}")
    if incident_outcomes[incident_id] != route_state:
        raise ValueError("route card state must be declared by fit interaction outcomes")
    rule = ROUTE_STATE_RULES[route_state]
    if card["signal_classification"] != rule["signal_classification"]:
        raise ValueError("route card signal classification conflicts with route state")
    if card["can_continue"] is not rule["can_continue"]:
        raise ValueError("route card continuation flag conflicts with route state")
    primary_action = card["primary_user_action"]
    _reject_extra_keys(primary_action, ALLOWED_PRIMARY_ACTION_KEYS, "primary action")
    if primary_action["action"] != rule["primary_action"]:
        raise ValueError("route card primary action conflicts with route state")
    dataset_prompt = card["dataset_prompt"]
    _reject_extra_keys(dataset_prompt, ALLOWED_DATASET_PROMPT_KEYS, "dataset prompt")
    if dataset_prompt["state"] not in SUPPORTED_DATASET_PROMPT_STATES:
        raise ValueError(f"unsupported dataset prompt state: {dataset_prompt['state']}")
    if dataset_prompt["state"] != rule["dataset_prompt_state"]:
        raise ValueError("dataset prompt state conflicts with route state")
    if dataset_prompt["enabled"] is not rule["dataset_enabled"]:
        raise ValueError("dataset prompt enabled flag conflicts with route state")
    if dataset_prompt["selected"] is not rule["dataset_selected"]:
        raise ValueError("dataset prompt selected flag conflicts with route state")
    case_ref = dataset_prompt["case_ref"]
    if rule["case_ref_required"] and not case_ref:
        raise ValueError("dataset prompt requires lab-internal case reference")
    if not rule["case_ref_required"] and case_ref is not None:
        raise ValueError("remeasurement card cannot carry dataset case reference")


def _validate_source(source: dict[str, Any]) -> None:
    _reject_forbidden_payloads(source)
    _validate_policy(source)
    route_shape = source["route_shape"]
    if route_shape["shape_kind"] not in SUPPORTED_ROUTE_SHAPE_KINDS:
        raise ValueError(f"unsupported route shape kind: {route_shape['shape_kind']}")
    contract = source["route_input_contract_summary"]
    _validate_contract(contract)
    selected_incident = _fit_interaction_reference(contract)["selected_review_incident_id"]
    if route_shape["selected_incident_id"] != selected_incident:
        raise ValueError("route shape selected incident must match fit interaction reference")
    cards = _records_by_key(route_shape["cards"], "incident_id")
    if selected_incident not in cards:
        raise ValueError("route shape selected incident is not declared as a card")
    incident_outcomes = _incident_outcomes(_fit_interaction_reference(contract))
    for card in route_shape["cards"]:
        _validate_card(card, incident_outcomes)


def _shell_state(contract: dict[str, Any]) -> str:
    if contract["route_readiness"]["missing_supporting_input_ids"]:
        return "renderable_with_attention"
    if contract["attention"]:
        return "renderable_with_reference_attention"
    return "renderable"


def _route_card(card: dict[str, Any], selected_incident_id: str) -> dict[str, Any]:
    return {
        "incident_id": card["incident_id"],
        "order": card["order"],
        "title": card["title"],
        "signal_classification": card["signal_classification"],
        "route_state": card["route_state"],
        "selected": card["incident_id"] == selected_incident_id,
        "can_continue": card["can_continue"],
        "primary_user_action": {
            "action": card["primary_user_action"]["action"],
            "label": card["primary_user_action"]["label"],
            "source": card["primary_user_action"]["source"],
        },
        "dataset_prompt": {
            "state": card["dataset_prompt"]["state"],
            "enabled": card["dataset_prompt"]["enabled"],
            "label": card["dataset_prompt"]["label"],
            "selected": card["dataset_prompt"]["selected"],
            "case_ref": card["dataset_prompt"]["case_ref"],
            "reason": card["dataset_prompt"]["reason"],
        },
    }


def _context_panel(contract: dict[str, Any]) -> dict[str, Any]:
    contract_inputs = contract["input_contract"]
    return {
        "missing_support": [
            {
                "input_id": item["input_id"],
                "family": item["family"],
                "severity": item["severity"],
                "message": item["message"],
            }
            for item in contract["missing_context"]
        ],
        "reference_chips": [
            {
                "input_id": item["input_id"],
                "family": item["family"],
                "owner": item["owner"],
                "state": item["state"],
            }
            for item in contract_inputs
            if item["state"] == "reference_only"
        ],
        "optional_context": [
            {
                "input_id": item["input_id"],
                "family": item["family"],
                "state": item["state"],
                "message": item.get("missing_reason"),
            }
            for item in contract_inputs
            if item["state"] == "optional_not_selected"
        ],
    }


def _continuation_affordances(cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "remeasurement_queue": [
            card["incident_id"] for card in cards if card["route_state"] == "requires_remeasurement"
        ],
        "continuation_targets": [
            card["incident_id"] for card in cards if card["route_state"] == "can_continue"
        ],
        "dataset_add_prompts": [
            card["incident_id"] for card in cards if card["dataset_prompt"]["enabled"]
        ],
    }


def build_calibration_continuation_route_shape_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a side-effect-free static calibration continuation route shape."""

    _validate_source(source)
    contract = source["route_input_contract_summary"]
    route_shape = source["route_shape"]
    selected_incident_id = route_shape["selected_incident_id"]
    cards = [
        _route_card(card, selected_incident_id)
        for card in sorted(route_shape["cards"], key=lambda item: item["order"])
    ]
    return {
        "summary_id": source["fixture_id"] + ".candidate",
        "route_context": copy.deepcopy(contract["route_context"]),
        "route_shell": {
            "shape_kind": route_shape["shape_kind"],
            "state": _shell_state(contract),
            "title": route_shape["title"],
            "selected_incident_id": selected_incident_id,
            "minimum_contract_state": contract["route_readiness"]["state"],
            "attention_count": len(contract["attention"]),
        },
        "fit_recovery_lane": {
            "selected_incident_id": selected_incident_id,
            "cards": cards,
        },
        "context_panel": _context_panel(contract),
        "continuation_affordances": _continuation_affordances(cards),
        "attention": copy.deepcopy(contract["attention"]),
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
