"""Review gate over prepared-run parameter-state consumption.

This module consumes one prepared-run parameter-state consumption summary and
projects a parameter-context gate state. It deliberately does not start runs,
write parameters, control hardware, read storage, discover catalogs, mutate
storage, sync environments, import or execute code, open GUIs, or define a
shared gate schema.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.parameter_state._contracts import validate_non_negative_integer

_EXPECTED_POLICY = {
    "gate_authority": "declared_prepared_run_parameter_review_policy",
    "consumption_source": "prepared_run_parameter_state_consumption_summary",
    "review_gate_scope": "parameter_state_context_only",
    "automatic_run_start": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "storage_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "parameter_review_gate_only",
    "gui_workflow": "not_defined",
    "shared_gate_schema": "not_defined",
}

_CONSUMPTION_POLICY_EXPECTED = {
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
}


@dataclass(frozen=True, init=False)
class PreparedRunParameterStateGateRequest:
    """Typed route-local request for a parameter-state pre-run review gate."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunParameterStateGateRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class PreparedRunParameterStateGateResult:
    """Typed route-local result for parameter-state gate review."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def gate_state(self) -> str:
        return self._summary["gate_decision"]["gate_state"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["gate_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run parameter-state gate policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared-run parameter-state gate policy {key} must be {expected}")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["gate_request"]
    if request["gate_mode"] != "manual_run_precheck_review":
        raise ValueError("parameter-state gate mode must be manual_run_precheck_review")
    if request["unresolved_finding_policy"] != "needs_review":
        raise ValueError("parameter-state gate unresolved finding policy must be needs_review")
    if request["unavailable_context_policy"] != "block_manual_run_review":
        raise ValueError(
            "parameter-state gate unavailable context policy must be block_manual_run_review"
        )
    validate_non_negative_integer(
        request["required_min_trusted_entries"], "required_min_trusted_entries"
    )


def _validate_consumption_summary(source: dict[str, Any]) -> None:
    summary = source["parameter_state_consumption_summary"]
    policy = summary["consumption_policy"]
    for key, expected in _CONSUMPTION_POLICY_EXPECTED.items():
        if policy[key] != expected:
            raise ValueError(f"parameter-state consumption summary {key} must be {expected}")
    request = source["gate_request"]
    prepared_context = summary["prepared_run_context"]
    if prepared_context["prepared_run_context_id"] != request["prepared_run_context_id"]:
        raise ValueError("gate request prepared_run_context_id must match consumption summary")
    if summary["consumption_request"]["expected_state_id"] != request["expected_state_id"]:
        raise ValueError("gate request expected_state_id must match consumption request")
    for entry in summary["trusted_entries"]:
        if entry["trust"] != "review_accepted":
            raise ValueError("parameter-state gate trusted entries must be review_accepted")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_request(source)
    _validate_consumption_summary(source)


def _finding(code: str, basis: Any, does_not_claim: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "review",
        "basis": copy.deepcopy(basis),
        "does_not_claim": does_not_claim,
    }


def _gate_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    request = source["gate_request"]
    summary = source["parameter_state_consumption_summary"]
    parameter_state = summary.get("parameter_state")
    findings = []

    if summary["classification"] == "prepared_run_parameter_state_unavailable_for_review":
        findings.append(
            _finding(
                "required_parameter_context_unavailable",
                summary["classification"],
                "run_start_or_context_repair",
            )
        )
    elif summary["classification"] != "prepared_run_parameter_state_ready":
        findings.append(
            _finding(
                "parameter_consumption_needs_review",
                summary["classification"],
                "automatic_run_blocking_or_parameter_write_back",
            )
        )

    for finding in summary["review_findings"]:
        findings.append(
            _finding(
                "parameter_consumption_finding",
                finding,
                "automatic_run_blocking_or_parameter_write_back",
            )
        )

    if parameter_state is None:
        return findings

    if parameter_state["state_id"] != request["expected_state_id"]:
        findings.append(
            _finding(
                "gate_state_id_mismatch",
                {
                    "expected_state_id": request["expected_state_id"],
                    "observed_state_id": parameter_state["state_id"],
                },
                "state_repair_or_hardware_safety_decision",
            )
        )
    if parameter_state["trust_status"] != "trusted_for_declared_scope":
        findings.append(
            _finding(
                "parameter_state_not_trusted_for_declared_scope",
                parameter_state["trust_status"],
                "hardware_safety_or_write_back_decision",
            )
        )
    trusted_entry_count = len(summary["trusted_entries"])
    if trusted_entry_count < request["required_min_trusted_entries"]:
        findings.append(
            _finding(
                "insufficient_trusted_entries",
                {
                    "required_min_trusted_entries": request["required_min_trusted_entries"],
                    "trusted_entry_count": trusted_entry_count,
                },
                "automatic_parameter_completion_or_write_back",
            )
        )
    return findings


def _gate_state(findings: list[dict[str, Any]]) -> str:
    codes = {finding["code"] for finding in findings}
    if "required_parameter_context_unavailable" in codes:
        return "blocked_by_required_parameter_context"
    if findings:
        return "needs_parameter_review"
    return "ready_for_manual_run_review"


def _recommended_action(gate_state: str) -> str:
    if gate_state == "ready_for_manual_run_review":
        return "present_parameter_context_for_manual_run_review"
    if gate_state == "blocked_by_required_parameter_context":
        return "select_or_repair_required_parameter_context_before_review"
    return "review_parameter_context_findings_before_manual_run_review"


def _parameter_state_input(summary: dict[str, Any]) -> dict[str, Any] | None:
    parameter_state = summary.get("parameter_state")
    if parameter_state is None:
        return None
    return {
        "state_id": parameter_state["state_id"],
        "state_kind": parameter_state["state_kind"],
        "readiness": parameter_state["readiness"],
        "trust_status": parameter_state["trust_status"],
        "trusted_entry_count": len(summary["trusted_entries"]),
        "trusted_entry_paths": [entry["path"] for entry in summary["trusted_entries"]],
        "consumption_classification": summary["classification"],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "parameter_gate_only",
            "severity": "info",
            "basis": "Gate output classifies parameter-context review state only.",
            "does_not_claim": "run_can_start_or_hardware_safe",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "Gate output does not apply trusted entries to instruments or files.",
            "does_not_claim": "parameter_application",
        },
        {
            "code": "fresh_storage_read_not_performed",
            "severity": "info",
            "basis": "Gate output consumes prior parameter-state consumption facts.",
            "does_not_claim": "new_integrity_observation",
        },
        {
            "code": "execution_not_granted",
            "severity": "review",
            "basis": "Gate output does not import code, sync an environment, or start a run.",
            "does_not_claim": "execution_permission",
        },
    ]


def build_prepared_run_parameter_state_gate_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a parameter-context review gate from explicit consumption facts."""
    request_model = PreparedRunParameterStateGateRequest.from_dict(source)
    source = request_model.source
    summary = source["parameter_state_consumption_summary"]
    findings = _gate_findings(source)
    gate_state = _gate_state(findings)
    summary = {
        "gate_policy": copy.deepcopy(source["gate_policy"]),
        "gate_request": copy.deepcopy(source["gate_request"]),
        "gate_decision": {
            "gate_state": gate_state,
            "recommended_action": _recommended_action(gate_state),
            "run_start_claim": "not_claimed",
            "parameter_write_back": "not_performed",
            "hardware_control": "not_performed",
            "reason_codes": [finding["code"] for finding in findings],
        },
        "prepared_run_context": {
            "prepared_run_context_id": summary["prepared_run_context"]["prepared_run_context_id"],
            "label": summary["prepared_run_context"]["label"],
            "manual_run_target": copy.deepcopy(
                summary["prepared_run_context"]["manual_run_target"]
            ),
        },
        "parameter_state_gate_input": _parameter_state_input(summary),
        "review_findings": findings,
        "attention": _attention(),
    }
    return PreparedRunParameterStateGateResult(summary=summary).to_dict()
