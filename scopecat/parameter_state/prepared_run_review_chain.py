"""Review chain for source-agnostic prepared-run parameter-state consumption."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from scopecat.parameter_state.prepared_run_gate import (
    build_prepared_run_parameter_state_gate_summary,
)
from scopecat.parameter_state.prepared_run_scope_alignment import (
    build_prepared_run_scope_alignment_summary,
)

_EXPECTED_POLICY = {
    "chain_authority": "declared_prepared_run_parameter_review_chain",
    "parameter_consumption_source": "prepared_run_source_agnostic_parameter_state_consumption_summary",
    "gate_source": "existing_prepared_run_parameter_state_gate",
    "scope_alignment_source": "existing_prepared_run_scope_alignment",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "compatibility_output": "not_produced",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "gui_workflow": "not_defined",
    "new_gate_schema": "not_defined",
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
class PreparedRunParameterStateReviewChainRequest:
    """Typed route-local request for prepared-run parameter review chain."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> PreparedRunParameterStateReviewChainRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class PreparedRunParameterStateReviewChainResult:
    """Typed route-local result for prepared-run parameter review chain."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def classification(self) -> str:
        return self._summary["classification"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["review_chain_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run source-agnostic review-chain policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"prepared-run source-agnostic review-chain policy {key} must be {expected}"
            )


def _validate_consumption_summary(source: dict[str, Any]) -> None:
    summary = source["source_agnostic_consumption_summary"]
    if summary["consumption_policy"]["parameter_state_source"] != (
        "source_agnostic_storage_read_view_summary"
    ):
        raise ValueError("review chain requires source-agnostic parameter-state consumption")
    for key, expected in _CONSUMPTION_POLICY_EXPECTED.items():
        if summary["consumption_policy"][key] != expected:
            raise ValueError(f"source-agnostic consumption summary {key} must be {expected}")
    if summary["parameter_state"] is None:
        raise ValueError("review chain requires selected parameter_state facts")
    if summary["parameter_state"]["source_kind"] != "calibration_handoff":
        raise ValueError("first review-chain fixture expects calibration_handoff source_kind")


def _validate_gate_input(source: dict[str, Any]) -> None:
    gate = source["gate_input"]
    summary = source["source_agnostic_consumption_summary"]
    if gate["parameter_state_consumption_summary"] != summary:
        raise ValueError("gate input must use the source-agnostic consumption summary unchanged")
    request = gate["gate_request"]
    if (
        request["prepared_run_context_id"]
        != summary["prepared_run_context"]["prepared_run_context_id"]
    ):
        raise ValueError("gate request prepared_run_context_id must match consumption summary")
    if request["expected_state_id"] != summary["parameter_state"]["state_id"]:
        raise ValueError("gate request expected_state_id must match selected parameter state")


def _validate_alignment_input(source: dict[str, Any]) -> None:
    alignment = source["scope_alignment_input"]
    summary = source["source_agnostic_consumption_summary"]
    if alignment["parameter_state_consumption_summary"] != summary:
        raise ValueError(
            "scope alignment input must use source-agnostic consumption summary unchanged"
        )
    request = alignment["alignment_request"]
    target = summary["prepared_run_context"]["manual_run_target"]
    if (
        request["prepared_run_context_id"]
        != summary["prepared_run_context"]["prepared_run_context_id"]
    ):
        raise ValueError("alignment request prepared_run_context_id must match consumption summary")
    if request["measurement_id"] != target["measurement_id"]:
        raise ValueError("alignment request measurement_id must match prepared target")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_consumption_summary(source)
    _validate_gate_input(source)
    _validate_alignment_input(source)


def _chain_classification(gate_summary: dict[str, Any], alignment_summary: dict[str, Any]) -> str:
    if gate_summary["gate_decision"]["gate_state"] == "blocked_by_required_parameter_context":
        return "parameter_review_chain_blocked"
    if alignment_summary["classification"] == "scope_alignment_blocked_for_review":
        return "parameter_review_chain_blocked"
    if gate_summary["gate_decision"]["gate_state"] != "ready_for_manual_run_review":
        return "parameter_review_chain_needs_review"
    if alignment_summary["classification"] != "scope_alignment_ready":
        return "parameter_review_chain_needs_review"
    return "parameter_review_chain_ready_for_manual_review"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "existing_gate_reused",
            "severity": "info",
            "basis": "Source-agnostic parameter-state consumption is accepted by the existing parameter-state gate shape.",
            "does_not_claim": "new_gate_schema",
        },
        {
            "code": "existing_scope_alignment_reused",
            "severity": "info",
            "basis": "Source-agnostic parameter-state consumption is accepted by the existing scope-alignment shape.",
            "does_not_claim": "new_scope_schema",
        },
        {
            "code": "calibration_derived_state_reaches_pre_run_review",
            "severity": "review",
            "basis": "The selected calibration-derived parameter state flows through gate and scope review without storage reads or hardware apply.",
            "does_not_claim": "run_start_or_hardware_safety",
        },
    ]


def build_prepared_run_source_agnostic_parameter_state_review_chain_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a review-chain summary using existing gate and scope candidates."""
    request_model = PreparedRunParameterStateReviewChainRequest.from_dict(source)
    source = request_model.source
    gate_summary = build_prepared_run_parameter_state_gate_summary(source["gate_input"])
    alignment_summary = build_prepared_run_scope_alignment_summary(source["scope_alignment_input"])
    consumption = source["source_agnostic_consumption_summary"]
    summary = {
        "review_chain_policy": copy.deepcopy(source["review_chain_policy"]),
        "classification": _chain_classification(gate_summary, alignment_summary),
        "selected_parameter_state": {
            "state_id": consumption["parameter_state"]["state_id"],
            "source_kind": consumption["parameter_state"]["source_kind"],
            "trust_status": consumption["parameter_state"]["trust_status"],
            "trusted_entry_count": consumption["parameter_state"]["trusted_entry_count"],
        },
        "prepared_run_context": {
            "prepared_run_context_id": consumption["prepared_run_context"][
                "prepared_run_context_id"
            ],
            "measurement_id": consumption["prepared_run_context"]["manual_run_target"][
                "measurement_id"
            ],
            "logical_targets": list(
                consumption["prepared_run_context"]["manual_run_target"]["logical_targets"]
            ),
        },
        "gate_summary": gate_summary,
        "scope_alignment_summary": alignment_summary,
        "review_findings": [
            {"source": "parameter_state_gate", **finding}
            for finding in gate_summary["review_findings"]
        ]
        + [
            {"source": "scope_alignment", **finding}
            for finding in alignment_summary["review_findings"]
        ],
        "attention": _attention(),
    }
    return PreparedRunParameterStateReviewChainResult(summary=summary).to_dict()
