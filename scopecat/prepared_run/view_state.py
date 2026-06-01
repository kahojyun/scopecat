"""Local view-state projection for prepared-run manual review."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.prepared_run.review_gate import PreparedRunReviewGateResult

VIEW_STATE_POLICY = {
    "summary_policy": "review_summary",
    "projection_authority": "local_prepared_run_review_view_state",
    "input_source": "prepared_run_review_gate_result",
    "optional_acknowledgement_source": "prepared_run_acknowledgement_review_summary",
    "view_scope": "manual_pre_run_review_presentation",
    "gui_component": "not_defined",
    "gui_persistence": "not_performed",
    "action_execution": "not_performed",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "environment_operation": "not_performed",
    "dependency_sync": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_fact_refresh": "not_performed",
    "code_import_execution": "not_performed",
    "portable_export": "not_performed",
    "readiness_claim": "not_claimed",
}


@dataclass(frozen=True, init=False)
class PreparedRunReviewViewStateRequest:
    """Typed local request for a prepared-run review view-state projection."""

    view_state_id: str
    _gate_summary: dict[str, Any] = field(repr=False)
    _acknowledgement_summary: dict[str, Any] | None = field(default=None, repr=False)

    def __init__(
        self,
        *,
        view_state_id: str,
        gate_summary: dict[str, Any],
        acknowledgement_summary: dict[str, Any] | None = None,
    ) -> None:
        if not view_state_id:
            raise ValueError("view_state_id is required")
        _validate_gate_summary(gate_summary)
        if acknowledgement_summary is not None:
            _validate_acknowledgement_summary(gate_summary, acknowledgement_summary)
        object.__setattr__(self, "view_state_id", view_state_id)
        object.__setattr__(self, "_gate_summary", copy.deepcopy(gate_summary))
        object.__setattr__(
            self,
            "_acknowledgement_summary",
            copy.deepcopy(acknowledgement_summary),
        )

    @classmethod
    def from_gate_result(
        cls,
        gate_result: PreparedRunReviewGateResult,
        *,
        view_state_id: str,
        acknowledgement_summary: dict[str, Any] | None = None,
    ) -> PreparedRunReviewViewStateRequest:
        return cls(
            view_state_id=view_state_id,
            gate_summary=gate_result.to_dict(),
            acknowledgement_summary=acknowledgement_summary,
        )

    @classmethod
    def from_summary(
        cls,
        gate_summary: dict[str, Any],
        *,
        view_state_id: str,
        acknowledgement_summary: dict[str, Any] | None = None,
    ) -> PreparedRunReviewViewStateRequest:
        return cls(
            view_state_id=view_state_id,
            gate_summary=gate_summary,
            acknowledgement_summary=acknowledgement_summary,
        )

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunReviewViewStateRequest:
        request = source["view_state_request"]
        return cls(
            view_state_id=_require_text(request, "view_state_id", "view-state request"),
            gate_summary=source["review_gate_summary"],
            acknowledgement_summary=source.get("acknowledgement_summary"),
        )

    @property
    def gate_summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._gate_summary)

    @property
    def acknowledgement_summary(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._acknowledgement_summary)


@dataclass(frozen=True, init=False)
class PreparedRunReviewViewStateResult:
    """Local prepared-run review view-state projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def presentation_state(self) -> str:
        return self._summary["header"]["presentation_state"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def project_prepared_run_review_view_state(
    request: PreparedRunReviewViewStateRequest,
) -> PreparedRunReviewViewStateResult:
    """Project local manual pre-run review state without GUI or action execution."""

    gate_summary = request.gate_summary
    acknowledgement_summary = request.acknowledgement_summary
    acknowledgement_state = _acknowledgement_state(acknowledgement_summary)
    presentation_state = _presentation_state(gate_summary, acknowledgement_summary)
    summary = {
        "view_state_policy": copy.deepcopy(VIEW_STATE_POLICY),
        "view_state_request": {
            "view_state_id": request.view_state_id,
            "prepared_run_context_id": gate_summary["review_gate_request"][
                "prepared_run_context_id"
            ],
            "measurement_id": gate_summary["review_gate_request"]["measurement_id"],
            "acknowledgement_summary_present": acknowledgement_summary is not None,
        },
        "header": {
            "prepared_run_context_id": gate_summary["review_gate_request"][
                "prepared_run_context_id"
            ],
            "measurement_id": gate_summary["review_gate_request"]["measurement_id"],
            "label": gate_summary["prepared_run_context"]["label"],
            "gate_state": gate_summary["gate_decision"]["overall_state"],
            "acknowledgement_state": acknowledgement_state,
            "presentation_state": presentation_state,
            "recommended_action": _recommended_action(presentation_state),
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
        },
        "review_item_rows": _review_item_rows(gate_summary, acknowledgement_summary),
        "finding_rows": _finding_rows(gate_summary, acknowledgement_summary),
        "next_action_labels": _next_action_labels(presentation_state),
        "attention": _attention(gate_summary, acknowledgement_summary),
    }
    return PreparedRunReviewViewStateResult(summary=summary)


def build_prepared_run_review_view_state(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for local prepared-run review view state."""

    request = PreparedRunReviewViewStateRequest.from_dict(source)
    return project_prepared_run_review_view_state(request).to_dict()


def _validate_gate_summary(gate_summary: dict[str, Any]) -> None:
    gate_decision = gate_summary["gate_decision"]
    if gate_decision["run_start_claim"] != "not_claimed":
        raise ValueError("review gate summary must not claim run start")
    for key in (
        "hardware_control",
        "parameter_write_back",
        "environment_operation",
        "code_import_execution",
    ):
        if gate_decision[key] != "not_performed":
            raise ValueError(f"review gate summary {key} must be not_performed")
    policy = gate_summary["review_gate_policy"]
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "dependency_sync",
        "workspace_mutation",
        "code_import_execution",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"review gate policy {key} must be not_performed")


def _validate_acknowledgement_summary(
    gate_summary: dict[str, Any],
    acknowledgement_summary: dict[str, Any],
) -> None:
    policy = acknowledgement_summary["acknowledgement_policy"]
    if policy["summary_policy"] != "review_summary":
        raise ValueError("acknowledgement summary must be review_summary")
    for key in (
        "automatic_run_start",
        "parameter_write_back",
        "hardware_control",
        "environment_operation",
        "code_import_execution",
        "gui_persistence",
        "portable_export",
    ):
        if policy[key] != "not_performed":
            raise ValueError(f"acknowledgement policy {key} must be not_performed")
    if policy["readiness_claim"] != "not_claimed":
        raise ValueError("acknowledgement policy must not claim readiness")

    acknowledgement_request = acknowledgement_summary["acknowledgement_request"]
    gate_request = gate_summary["review_gate_request"]
    if (
        acknowledgement_request["prepared_run_context_id"]
        != gate_request["prepared_run_context_id"]
    ):
        raise ValueError("acknowledgement summary prepared_run_context_id must match gate summary")
    if acknowledgement_request["measurement_id"] != gate_request["measurement_id"]:
        raise ValueError("acknowledgement summary measurement_id must match gate summary")

    source_gate = acknowledgement_summary["source_review_gate"]
    gate_decision = gate_summary["gate_decision"]
    for key in (
        "overall_state",
        "run_start_claim",
        "hardware_control",
        "parameter_write_back",
        "environment_operation",
        "code_import_execution",
    ):
        if source_gate[key] != gate_decision[key]:
            raise ValueError(f"acknowledgement source gate {key} must match gate summary")

    gate_item_areas = {item["area"] for item in gate_summary["review_items"]}
    acknowledgement_item_areas = {
        item["area"] for item in acknowledgement_summary["review_item_acknowledgements"]
    }
    if acknowledgement_item_areas != gate_item_areas:
        raise ValueError("acknowledgement review item areas must match gate summary")

    gate_finding_keys = {
        (finding["source_area"], finding["code"])
        for finding in gate_summary["aggregated_review_findings"]
    }
    acknowledgement_finding_keys = {
        (finding["source_area"], finding["code"])
        for finding in acknowledgement_summary["finding_acknowledgements"]
    }
    if acknowledgement_finding_keys != gate_finding_keys:
        raise ValueError("acknowledgement findings must match gate summary")


def _acknowledgement_state(acknowledgement_summary: dict[str, Any] | None) -> str:
    if acknowledgement_summary is None:
        return "not_collected"
    return acknowledgement_summary["continuation_decision"]["continuation_state"]


def _presentation_state(
    gate_summary: dict[str, Any],
    acknowledgement_summary: dict[str, Any] | None,
) -> str:
    if acknowledgement_summary is not None:
        continuation_state = acknowledgement_summary["continuation_decision"]["continuation_state"]
        if continuation_state == "manual_review_acknowledged_for_continuation":
            return "manual_review_acknowledged"
        if continuation_state == "required_context_acknowledged_but_still_blocked":
            return "blocked_required_context"
        if continuation_state == "manual_review_acknowledgement_incomplete":
            return "needs_acknowledgement"
        return continuation_state

    gate_state = gate_summary["gate_decision"]["overall_state"]
    if gate_state == "blocked_by_required_context":
        return "blocked_required_context"
    if gate_state == "manual_pre_run_review_needed":
        return "needs_acknowledgement"
    return "ready_for_manual_review"


def _recommended_action(presentation_state: str) -> str:
    actions = {
        "ready_for_manual_review": "present_manual_pre_run_review",
        "needs_acknowledgement": "collect_review_acknowledgements",
        "manual_review_acknowledged": "continue_manual_review_without_execution_authority",
        "blocked_required_context": "repair_required_context_before_manual_pre_run_review",
    }
    return actions[presentation_state]


def _review_item_rows(
    gate_summary: dict[str, Any],
    acknowledgement_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    acknowledgement_by_area = {}
    if acknowledgement_summary is not None:
        acknowledgement_by_area = {
            item["area"]: item for item in acknowledgement_summary["review_item_acknowledgements"]
        }
    rows = []
    for index, item in enumerate(gate_summary["review_items"]):
        acknowledgement_state = "not_collected"
        if item["state"] == "ready_for_manual_review":
            acknowledgement_state = "not_required"
        if item["area"] in acknowledgement_by_area:
            acknowledgement_state = acknowledgement_by_area[item["area"]]["acknowledgement_state"]
        rows.append(
            {
                "row_id": f"review-item-{index:02d}-{item['area']}",
                "area": item["area"],
                "state": item["state"],
                "reason_codes": list(item["reason_codes"]),
                "finding_count": item["finding_count"],
                "acknowledgement_state": acknowledgement_state,
                "display_priority": index,
            }
        )
    return rows


def _finding_rows(
    gate_summary: dict[str, Any],
    acknowledgement_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    acknowledgement_by_key = {}
    if acknowledgement_summary is not None:
        acknowledgement_by_key = {
            (finding["source_area"], finding["code"]): finding
            for finding in acknowledgement_summary["finding_acknowledgements"]
        }
    rows = []
    for index, finding in enumerate(gate_summary["aggregated_review_findings"]):
        key = (finding["source_area"], finding["code"])
        acknowledgement_state = "not_collected"
        if key in acknowledgement_by_key:
            acknowledgement_state = acknowledgement_by_key[key]["acknowledgement_state"]
        rows.append(
            {
                "row_id": f"review-finding-{index:02d}-{finding['source_area']}-{finding['code']}",
                "source_area": finding["source_area"],
                "code": finding["code"],
                "severity": finding["severity"],
                "acknowledgement_state": acknowledgement_state,
                "basis": copy.deepcopy(finding["basis"]),
                "does_not_claim": finding["does_not_claim"],
                "display_priority": index,
            }
        )
    return rows


def _next_action_labels(presentation_state: str) -> list[dict[str, Any]]:
    label_map = {
        "ready_for_manual_review": [
            ("present_manual_review", "Present manual review"),
        ],
        "needs_acknowledgement": [
            ("collect_acknowledgements", "Collect acknowledgements"),
            ("review_findings", "Review findings"),
        ],
        "manual_review_acknowledged": [
            ("continue_manual_review", "Continue manual review"),
        ],
        "blocked_required_context": [
            ("repair_required_context", "Repair required context"),
            ("review_required_context", "Review required context finding"),
        ],
    }
    return [
        {
            "action_id": action_id,
            "label": label,
            "action_kind": "label_only",
            "execution": "not_performed",
        }
        for action_id, label in label_map[presentation_state]
    ]


def _attention(
    gate_summary: dict[str, Any],
    acknowledgement_summary: dict[str, Any] | None,
) -> list[dict[str, str]]:
    notices = [
        {
            "code": "view_state_projection_only",
            "severity": "info",
            "basis": "The view state is a deterministic local data projection for manual review presentation.",
            "does_not_claim": "gui_component_or_gui_persistence",
        },
        {
            "code": "labels_are_not_executable_actions",
            "severity": "review",
            "basis": "Next action labels describe review choices but do not execute commands.",
            "does_not_claim": "action_execution_or_run_start_permission",
        },
        {
            "code": "source_facts_not_refreshed",
            "severity": "review",
            "basis": "The view state does not refresh gate, acknowledgement, environment, runtime, or hardware facts.",
            "does_not_claim": "fresh_readiness_or_execution_authority",
        },
    ]
    notices.extend(
        {
            "code": f"gate_{notice['code']}",
            "severity": notice["severity"],
            "basis": notice["basis"],
            "does_not_claim": notice["does_not_claim"],
        }
        for notice in gate_summary["attention"]
    )
    if acknowledgement_summary is not None:
        notices.extend(
            {
                "code": f"acknowledgement_{notice['code']}",
                "severity": notice["severity"],
                "basis": notice["basis"],
                "does_not_claim": notice["does_not_claim"],
            }
            for notice in acknowledgement_summary["attention"]
        )
    return notices


def _require_text(source: dict[str, Any], key: str, owner: str) -> str:
    value = source[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} {key} must be non-empty text")
    return value
