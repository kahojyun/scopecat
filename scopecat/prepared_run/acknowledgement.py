"""Local acknowledgements over prepared-run review-gate results."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.prepared_run.review_gate import PreparedRunReviewGateResult

ACKNOWLEDGEMENT_STATE = "acknowledged_for_manual_review_continuation"

ACKNOWLEDGEMENT_POLICY = {
    "summary_policy": "review_summary",
    "acknowledgement_authority": "operator_declared_local_review_acknowledgements",
    "input_source": "prepared_run_review_gate_result",
    "review_scope": "manual_pre_run_acknowledgement_review",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "environment_operation": "not_performed",
    "dependency_sync": "not_performed",
    "runtime_probe": "not_performed",
    "fresh_fact_refresh": "not_performed",
    "stale_fact_execution_authority": "not_granted",
    "code_import_execution": "not_performed",
    "gui_persistence": "not_performed",
    "portable_export": "not_performed",
    "readiness_claim": "not_claimed",
}


@dataclass(frozen=True, init=False)
class PreparedRunAcknowledgement:
    """One local operator acknowledgement of a gate item or finding."""

    acknowledgement_id: str
    target_type: str
    _target: dict[str, str] = field(repr=False)
    actor_id: str
    acknowledged_at: str
    acknowledgement_state: str
    note: str

    def __init__(
        self,
        *,
        acknowledgement_id: str,
        target_type: str,
        target: dict[str, str],
        actor_id: str,
        acknowledged_at: str,
        acknowledgement_state: str = ACKNOWLEDGEMENT_STATE,
        note: str = "",
    ) -> None:
        if target_type not in {"review_item", "review_finding"}:
            raise ValueError("acknowledgement target_type must be review_item or review_finding")
        if acknowledgement_state != ACKNOWLEDGEMENT_STATE:
            raise ValueError(f"acknowledgement_state must be {ACKNOWLEDGEMENT_STATE}")
        if not acknowledgement_id:
            raise ValueError("acknowledgement_id is required")
        if not actor_id:
            raise ValueError("actor_id is required")
        if not acknowledged_at:
            raise ValueError("acknowledged_at is required")
        object.__setattr__(self, "acknowledgement_id", acknowledgement_id)
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "_target", copy.deepcopy(target))
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "acknowledged_at", acknowledged_at)
        object.__setattr__(self, "acknowledgement_state", acknowledgement_state)
        object.__setattr__(self, "note", note)

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunAcknowledgement:
        target = source["target"]
        target_type = target["target_type"]
        if target_type == "review_item":
            target_ref = {
                "target_type": target_type,
                "area": _require_text(target, "area", "acknowledgement target"),
            }
        elif target_type == "review_finding":
            target_ref = {
                "target_type": target_type,
                "source_area": _require_text(target, "source_area", "acknowledgement target"),
                "code": _require_text(target, "code", "acknowledgement target"),
            }
        else:
            target_ref = {"target_type": target_type}
        return cls(
            acknowledgement_id=_require_text(source, "acknowledgement_id", "acknowledgement"),
            target_type=target_type,
            target=target_ref,
            actor_id=_require_text(source, "actor_id", "acknowledgement"),
            acknowledged_at=_require_text(source, "acknowledged_at", "acknowledgement"),
            acknowledgement_state=source.get("acknowledgement_state", ACKNOWLEDGEMENT_STATE),
            note=source.get("note", ""),
        )

    @property
    def target(self) -> dict[str, str]:
        return copy.deepcopy(self._target)

    @property
    def target_key(self) -> tuple[str, str] | tuple[str, str, str]:
        if self.target_type == "review_item":
            return ("review_item", self._target["area"])
        return ("review_finding", self._target["source_area"], self._target["code"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "acknowledgement_id": self.acknowledgement_id,
            "target": self.target,
            "actor_id": self.actor_id,
            "acknowledged_at": self.acknowledged_at,
            "acknowledgement_state": self.acknowledgement_state,
            "note": self.note,
        }


@dataclass(frozen=True, init=False)
class PreparedRunAcknowledgementReviewRequest:
    """Typed local acknowledgement request over one review-gate result."""

    acknowledgement_review_id: str
    _gate_summary: dict[str, Any] = field(repr=False)
    acknowledgements: tuple[PreparedRunAcknowledgement, ...]

    def __init__(
        self,
        *,
        acknowledgement_review_id: str,
        gate_summary: dict[str, Any],
        acknowledgements: tuple[PreparedRunAcknowledgement, ...],
    ) -> None:
        _validate_gate_summary(gate_summary)
        _validate_acknowledgements(gate_summary, acknowledgements)
        object.__setattr__(self, "acknowledgement_review_id", acknowledgement_review_id)
        object.__setattr__(self, "_gate_summary", copy.deepcopy(gate_summary))
        object.__setattr__(self, "acknowledgements", tuple(acknowledgements))

    @classmethod
    def from_gate_result(
        cls,
        gate_result: PreparedRunReviewGateResult,
        *,
        acknowledgement_review_id: str,
        acknowledgements: tuple[PreparedRunAcknowledgement, ...],
    ) -> PreparedRunAcknowledgementReviewRequest:
        return cls(
            acknowledgement_review_id=acknowledgement_review_id,
            gate_summary=gate_result.to_dict(),
            acknowledgements=acknowledgements,
        )

    @classmethod
    def from_summary(
        cls,
        gate_summary: dict[str, Any],
        *,
        acknowledgement_review_id: str,
        acknowledgements: tuple[PreparedRunAcknowledgement, ...],
    ) -> PreparedRunAcknowledgementReviewRequest:
        return cls(
            acknowledgement_review_id=acknowledgement_review_id,
            gate_summary=gate_summary,
            acknowledgements=acknowledgements,
        )

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunAcknowledgementReviewRequest:
        request = source["acknowledgement_request"]
        acknowledgements = tuple(
            PreparedRunAcknowledgement.from_dict(acknowledgement)
            for acknowledgement in source["acknowledgements"]
        )
        return cls(
            acknowledgement_review_id=_require_text(
                request,
                "acknowledgement_review_id",
                "acknowledgement request",
            ),
            gate_summary=source["review_gate_summary"],
            acknowledgements=acknowledgements,
        )

    @property
    def gate_summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._gate_summary)


@dataclass(frozen=True, init=False)
class PreparedRunAcknowledgementReviewResult:
    """Local acknowledgement review over a prepared-run gate result."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def continuation_state(self) -> str:
        return self._summary["continuation_decision"]["continuation_state"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def compose_prepared_run_acknowledgement_review(
    request: PreparedRunAcknowledgementReviewRequest,
) -> PreparedRunAcknowledgementReviewResult:
    """Compose a local acknowledgement review without granting execution authority."""

    gate_summary = request.gate_summary
    item_states = _review_item_acknowledgement_states(
        gate_summary,
        request.acknowledgements,
    )
    finding_states = _finding_acknowledgement_states(gate_summary, request.acknowledgements)
    continuation_state = _continuation_state(gate_summary, item_states, finding_states)
    summary = {
        "acknowledgement_policy": copy.deepcopy(ACKNOWLEDGEMENT_POLICY),
        "acknowledgement_request": {
            "acknowledgement_review_id": request.acknowledgement_review_id,
            "prepared_run_context_id": gate_summary["review_gate_request"][
                "prepared_run_context_id"
            ],
            "measurement_id": gate_summary["review_gate_request"]["measurement_id"],
        },
        "source_review_gate": {
            "overall_state": gate_summary["gate_decision"]["overall_state"],
            "recommended_action": gate_summary["gate_decision"]["recommended_action"],
            "run_start_claim": gate_summary["gate_decision"]["run_start_claim"],
            "hardware_control": gate_summary["gate_decision"]["hardware_control"],
            "parameter_write_back": gate_summary["gate_decision"]["parameter_write_back"],
            "environment_operation": gate_summary["gate_decision"]["environment_operation"],
            "code_import_execution": gate_summary["gate_decision"]["code_import_execution"],
        },
        "acknowledgements": [
            acknowledgement.to_dict() for acknowledgement in request.acknowledgements
        ],
        "review_item_acknowledgements": item_states,
        "finding_acknowledgements": finding_states,
        "continuation_decision": {
            "continuation_state": continuation_state,
            "recommended_action": _recommended_action(continuation_state),
            "run_start_claim": "not_claimed",
            "hardware_control": "not_performed",
            "parameter_write_back": "not_performed",
            "environment_operation": "not_performed",
            "code_import_execution": "not_performed",
            "fresh_fact_refresh": "not_performed",
            "readiness_claim": "not_claimed",
        },
        "attention": _attention(),
    }
    return PreparedRunAcknowledgementReviewResult(summary=summary)


def build_prepared_run_acknowledgement_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for local prepared-run acknowledgement review."""

    request = PreparedRunAcknowledgementReviewRequest.from_dict(source)
    return compose_prepared_run_acknowledgement_review(request).to_dict()


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


def _validate_acknowledgements(
    gate_summary: dict[str, Any],
    acknowledgements: tuple[PreparedRunAcknowledgement, ...],
) -> None:
    item_areas = {item["area"] for item in gate_summary["review_items"]}
    finding_keys = {
        ("review_finding", finding["source_area"], finding["code"])
        for finding in gate_summary["aggregated_review_findings"]
    }
    seen_ids = set()
    seen_targets = set()
    for acknowledgement in acknowledgements:
        if acknowledgement.acknowledgement_id in seen_ids:
            raise ValueError(f"duplicate acknowledgement_id: {acknowledgement.acknowledgement_id}")
        seen_ids.add(acknowledgement.acknowledgement_id)
        if acknowledgement.target_key in seen_targets:
            raise ValueError(f"duplicate acknowledgement target: {acknowledgement.target_key}")
        seen_targets.add(acknowledgement.target_key)
        if acknowledgement.target_type == "review_item":
            area = acknowledgement.target["area"]
            if area not in item_areas:
                raise ValueError(f"acknowledgement references missing review item: {area}")
        elif acknowledgement.target_key not in finding_keys:
            raise ValueError(
                f"acknowledgement references missing review finding: {acknowledgement.target_key}"
            )


def _review_item_acknowledgement_states(
    gate_summary: dict[str, Any],
    acknowledgements: tuple[PreparedRunAcknowledgement, ...],
) -> list[dict[str, Any]]:
    acknowledged_areas = {
        acknowledgement.target["area"]
        for acknowledgement in acknowledgements
        if acknowledgement.target_type == "review_item"
    }
    states = []
    for item in gate_summary["review_items"]:
        if item["state"] == "ready_for_manual_review":
            acknowledgement_state = "not_required"
        elif item["area"] in acknowledged_areas:
            acknowledgement_state = ACKNOWLEDGEMENT_STATE
        else:
            acknowledgement_state = "unacknowledged"
        states.append(
            {
                "area": item["area"],
                "gate_state": item["state"],
                "finding_count": item["finding_count"],
                "acknowledgement_state": acknowledgement_state,
            }
        )
    return states


def _finding_acknowledgement_states(
    gate_summary: dict[str, Any],
    acknowledgements: tuple[PreparedRunAcknowledgement, ...],
) -> list[dict[str, Any]]:
    acknowledged_findings = {
        acknowledgement.target_key
        for acknowledgement in acknowledgements
        if acknowledgement.target_type == "review_finding"
    }
    states = []
    for finding in gate_summary["aggregated_review_findings"]:
        key = ("review_finding", finding["source_area"], finding["code"])
        acknowledgement_state = (
            ACKNOWLEDGEMENT_STATE if key in acknowledged_findings else "unacknowledged"
        )
        states.append(
            {
                "source_area": finding["source_area"],
                "code": finding["code"],
                "severity": finding["severity"],
                "acknowledgement_state": acknowledgement_state,
                "does_not_claim": finding["does_not_claim"],
            }
        )
    return states


def _continuation_state(
    gate_summary: dict[str, Any],
    item_states: list[dict[str, Any]],
    finding_states: list[dict[str, Any]],
) -> str:
    if gate_summary["gate_decision"]["overall_state"] == "ready_for_manual_review":
        return "ready_for_manual_review"
    if any(state["acknowledgement_state"] == "unacknowledged" for state in item_states):
        return "manual_review_acknowledgement_incomplete"
    if any(state["acknowledgement_state"] == "unacknowledged" for state in finding_states):
        return "manual_review_acknowledgement_incomplete"
    if gate_summary["gate_decision"]["overall_state"] == "blocked_by_required_context":
        return "required_context_acknowledged_but_still_blocked"
    return "manual_review_acknowledged_for_continuation"


def _recommended_action(continuation_state: str) -> str:
    actions = {
        "ready_for_manual_review": "present_manual_pre_run_review",
        "manual_review_acknowledgement_incomplete": "collect_missing_acknowledgements_before_continuation",
        "required_context_acknowledged_but_still_blocked": "repair_required_context_before_manual_pre_run_review",
        "manual_review_acknowledged_for_continuation": "continue_manual_pre_run_review_without_execution_authority",
    }
    return actions[continuation_state]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "acknowledgement_review_only",
            "severity": "info",
            "basis": "Acknowledgements record local operator review decisions over an existing gate result.",
            "does_not_claim": "run_start_permission_or_runtime_readiness",
        },
        {
            "code": "source_gate_facts_not_refreshed",
            "severity": "review",
            "basis": "The acknowledgement layer does not refresh prior context, environment, or finding facts.",
            "does_not_claim": "fresh_observation_or_execution_authority",
        },
        {
            "code": "required_context_still_required",
            "severity": "review",
            "basis": "Acknowledging a required-context finding does not repair the missing context.",
            "does_not_claim": "required_context_available",
        },
        {
            "code": "no_gui_persistence_or_export",
            "severity": "review",
            "basis": "The acknowledgement summary is a local review projection only.",
            "does_not_claim": "gui_state_saved_or_portable_artifact",
        },
    ]


def _require_text(source: dict[str, Any], key: str, owner: str) -> str:
    value = source[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} {key} must be non-empty text")
    return value
