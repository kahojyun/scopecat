"""Notebook/CLI-shaped calibration continuation review surface."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

_EXPECTED_POLICY = {
    "surface_authority": "declared_calibration_continuation_review_surface",
    "input_source": "declared_review_state_backbone_and_findings_summaries",
    "surface_consumers": "notebook_or_cli",
    "payload_handling": "summary_facts_and_labels_only",
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
    "shared_surface_schema": "not_defined",
}

_FORBIDDEN_KEYS = {
    "gui_component",
    "notebook_cell",
    "callback",
    "command",
    "executable",
    "measurement_payload",
    "fit_payload",
    "hardware_session",
    "parameter_write",
    "storage_write",
}


@dataclass(frozen=True)
class CalibrationContinuationReviewSurfaceRequest:
    """Typed edge for declared calibration review summaries."""

    source: dict[str, Any]

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> CalibrationContinuationReviewSurfaceRequest:
        request = cls(copy.deepcopy(source))
        _validate_references(request.source)
        return request


@dataclass(frozen=True)
class CalibrationContinuationReviewSurfaceResult:
    """Route-local review-surface projection."""

    surface_policy: dict[str, Any]
    surface_request: dict[str, Any]
    route_header: dict[str, Any]
    step_review_lane: dict[str, Any]
    backbone_context_panel: dict[str, Any]
    backbone_findings_panel: dict[str, Any]
    action_palette: list[dict[str, str]]
    attention: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_policy": copy.deepcopy(self.surface_policy),
            "surface_request": copy.deepcopy(self.surface_request),
            "route_header": copy.deepcopy(self.route_header),
            "step_review_lane": copy.deepcopy(self.step_review_lane),
            "backbone_context_panel": copy.deepcopy(self.backbone_context_panel),
            "backbone_findings_panel": copy.deepcopy(self.backbone_findings_panel),
            "action_palette": copy.deepcopy(self.action_palette),
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
                raise ValueError(f"review surface input must not include {key} at {path}")
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["surface_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("calibration continuation review surface policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"calibration continuation review surface policy {key} must be {expected}"
            )


def _validate_review_state(source: dict[str, Any]) -> None:
    cards = source["review_state_summary"]["review_cards"]
    cards_by_step = _records_by_key(cards, "step_record_id")
    for card in cards:
        if card["action_posture"] != "labels_only_not_executed":
            raise ValueError("review card actions must remain labels-only")
        if not isinstance(card["available_review_actions"], list):
            raise ValueError("review card available actions must be labels")
        for action in card["available_review_actions"]:
            if not isinstance(action, str):
                raise ValueError("review card available actions must be string labels")
    selected_step_id = source["surface_request"].get("selected_step_id")
    if selected_step_id is not None and selected_step_id not in cards_by_step:
        raise ValueError("selected step must exist in review cards")


def _validate_backbone_context(source: dict[str, Any]) -> None:
    context = source["backbone_context_summary"]
    if context["classification"] not in {
        "calibration_derived_parameter_state_selected_for_later_measurement_context",
        "calibration_derived_parameter_state_context_needs_review",
    }:
        raise ValueError("unsupported backbone context classification")
    if (
        context["prepared_run_context"]["selected_parameter_state_id"]
        != context["measurement_record_context"]["linked_parameter_state_id"]
    ):
        raise ValueError("backbone context summary must preserve selected parameter-state identity")


def _validate_backbone_findings(source: dict[str, Any]) -> None:
    findings = source["backbone_findings_summary"]
    if findings["classification"] not in {
        "calibration_backbone_context_ready",
        "calibration_backbone_context_needs_review",
        "calibration_backbone_context_blocked",
    }:
        raise ValueError("unsupported backbone findings classification")
    for finding in findings["review_findings"]:
        if finding["severity"] not in {"info", "review", "blocked"}:
            raise ValueError("unsupported backbone finding severity")


def _validate_references(source: dict[str, Any]) -> None:
    _reject_forbidden_keys(source)
    _validate_policy(source)
    _validate_review_state(source)
    _validate_backbone_context(source)
    _validate_backbone_findings(source)


def _surface_state(backbone_findings: dict[str, Any], review_state: dict[str, Any]) -> str:
    if backbone_findings["classification"] == "calibration_backbone_context_blocked":
        return "blocked_with_context_findings"
    if backbone_findings["classification"] == "calibration_backbone_context_needs_review":
        return "needs_context_review"
    if review_state["review_findings"]:
        return "needs_step_review"
    return "ready_for_local_review"


def _step_cards(review_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "step_record_id": card["step_record_id"],
            "target": card["target"],
            "review_state": card["review_state"],
            "state_source": card["state_source"],
            "finding_count": len(card["finding_refs"]),
            "available_review_actions": list(card["available_review_actions"]),
            "action_posture": card["action_posture"],
        }
        for card in review_state["review_cards"]
    ]


def _backbone_context_panel(backbone_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": backbone_context["classification"],
        "prepared_run_context_id": backbone_context["prepared_run_context"][
            "prepared_run_context_id"
        ],
        "measurement_id": backbone_context["prepared_run_context"]["measurement_id"],
        "selected_parameter_state_id": backbone_context["prepared_run_context"][
            "selected_parameter_state_id"
        ],
        "measurement_context_link_id": backbone_context["measurement_record_context"][
            "parameter_context_link_id"
        ],
        "context_policy": backbone_context["measurement_record_context"]["context_policy"],
    }


def _backbone_findings_panel(backbone_findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": backbone_findings["classification"],
        "blocked_case_count": backbone_findings["blocked_case_count"],
        "review_case_count": backbone_findings["review_case_count"],
        "ready_case_count": backbone_findings["ready_case_count"],
        "finding_count": len(backbone_findings["review_findings"]),
        "findings": copy.deepcopy(backbone_findings["review_findings"]),
    }


def _action_palette(
    review_state: dict[str, Any], backbone_findings: dict[str, Any]
) -> list[dict[str, str]]:
    labels = []
    for card in review_state["review_cards"]:
        for action in card["available_review_actions"]:
            labels.append(
                {
                    "source": "review_state_card",
                    "target_id": card["step_record_id"],
                    "action_label": action,
                    "posture": "labels_only_not_executed",
                }
            )
    for finding in backbone_findings["review_findings"]:
        labels.append(
            {
                "source": "backbone_context_finding",
                "target_id": finding["case_id"],
                "action_label": f"inspect_{finding['code']}",
                "posture": "labels_only_not_executed",
            }
        )
    return labels


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "surface_is_not_gui",
            "severity": "review",
            "basis": "The output is notebook/CLI-shaped data and does not define components.",
            "does_not_claim": "gui_contract",
        },
        {
            "code": "actions_are_labels_only",
            "severity": "review",
            "basis": "Available actions name possible reviewer moves but cannot execute them.",
            "does_not_claim": "action_execution",
        },
        {
            "code": "context_findings_do_not_invalidate_measurements",
            "severity": "info",
            "basis": "Backbone context findings stay review evidence.",
            "does_not_claim": "measurement_validity_decision",
        },
    ]


def compose_calibration_continuation_review_surface(
    request: CalibrationContinuationReviewSurfaceRequest,
) -> CalibrationContinuationReviewSurfaceResult:
    """Compose a compact local review surface from prior route summaries."""
    source = request.source
    review_state = source["review_state_summary"]
    backbone_context = source["backbone_context_summary"]
    backbone_findings = source["backbone_findings_summary"]
    return CalibrationContinuationReviewSurfaceResult(
        surface_policy=copy.deepcopy(source["surface_policy"]),
        surface_request=copy.deepcopy(source["surface_request"]),
        route_header={
            "surface_state": _surface_state(backbone_findings, review_state),
            "review_card_count": len(review_state["review_cards"]),
            "backbone_finding_count": len(backbone_findings["review_findings"]),
            "selected_step_id": source["surface_request"].get("selected_step_id"),
        },
        step_review_lane={
            "state_counts": copy.deepcopy(review_state["state_counts"]),
            "cards": _step_cards(review_state),
        },
        backbone_context_panel=_backbone_context_panel(backbone_context),
        backbone_findings_panel=_backbone_findings_panel(backbone_findings),
        action_palette=_action_palette(review_state, backbone_findings),
        attention=_attention(),
    )


def build_calibration_continuation_review_surface_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Raw-dictionary adapter for current fixture and edge callers."""
    request = CalibrationContinuationReviewSurfaceRequest.from_dict(source)
    return compose_calibration_continuation_review_surface(request).to_dict()
