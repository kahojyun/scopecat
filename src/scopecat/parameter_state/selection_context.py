"""Structured summary builder for parameter-state selection contexts.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not write parameters, inspect current instrument
state, mutate external JSON files, perform rollback, define branch/tag/commit
semantics, execute future runs, or define a shared domain model.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

_EXPECTED_POLICY = {
    "parameter_authority": "scopecat_parameter_state",
    "selection_role": "context_input_reference",
    "selection_intent_semantics": "scenario_label_not_lifecycle",
    "hardware_write_back": "not_performed",
    "current_hardware_state_claim": "not_claimed",
    "rollback_mutation": "not_performed",
    "branch_tag_commit_semantics": "not_claimed",
}

_CONTEXT_KINDS = {
    "future_run_preparation",
    "analysis_comparison",
    "calibration_continuation",
}
_SELECTION_STATUSES = {
    "selected_for_context",
    "review_required",
}
_STATE_REQUIREMENTS = {
    "committed_trusted_for_declared_scope",
    "any_recorded_parameter_state",
}


@dataclass(frozen=True, init=False)
class ParameterStateSelectionRequest:
    """Typed route-local request for selecting parameter state for a context."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> ParameterStateSelectionRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class ParameterStateSelectionResult:
    """Typed route-local selection-context summary."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def selections(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["parameter_state_selections"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _lineages_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["lineages"], "lineage_id")


def _states_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_states"], "state_id")


def _contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["selection_contexts"], "context_id")


def _selections_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_state_selections"], "selection_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["parameter_state_selection_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("parameter state selection policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"parameter state selection policy {key} must be {expected}")


def _validate_state(state: dict[str, Any], lineages: dict[str, dict[str, Any]]) -> None:
    if state["lineage_id"] not in lineages:
        raise ValueError(f"state {state['state_id']} references missing lineage")
    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate entry path")
    trusted_entry_paths = state.get("trusted_entry_paths", [])
    if len(trusted_entry_paths) != len(set(trusted_entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate trusted entry path")
    for trusted_path in trusted_entry_paths:
        if trusted_path not in entry_paths:
            raise ValueError(f"state {state['state_id']} trusts missing entry path")


def _validate_context(context: dict[str, Any], lineages: dict[str, dict[str, Any]]) -> None:
    if context["context_kind"] not in _CONTEXT_KINDS:
        raise ValueError(f"unsupported selection context kind: {context['context_kind']}")
    if context["lineage_id"] not in lineages:
        raise ValueError(f"context {context['context_id']} references missing lineage")
    requirement = context["required_selected_state"]
    if requirement not in _STATE_REQUIREMENTS:
        raise ValueError(f"unsupported selected state requirement: {requirement}")


def _validate_requirement(
    selection: dict[str, Any],
    context: dict[str, Any],
    selected_state: dict[str, Any],
) -> None:
    requirement = context["required_selected_state"]
    if requirement == "any_recorded_parameter_state":
        return
    if selected_state["state_kind"] != "committed_snapshot":
        raise ValueError("selection context requires committed selected state")
    if selected_state["trust_status"] != "trusted_for_declared_scope":
        raise ValueError("selection context requires trusted selected state")
    if not selected_state.get("accepted_review_id"):
        raise ValueError("selection context requires accepted_review_id on selected state")
    if not selected_state.get("trusted_entry_paths"):
        raise ValueError("selection context requires selected state trusted entry paths")
    if selection["selection_status"] != "selected_for_context":
        raise ValueError("committed trusted selection must be selected_for_context")


def _validate_selection(
    selection: dict[str, Any],
    states: dict[str, dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
) -> None:
    context = contexts.get(selection["context_id"])
    if context is None:
        raise ValueError(f"selection {selection['selection_id']} references missing context")
    selected_state = states.get(selection["selected_state_id"])
    if selected_state is None:
        raise ValueError(f"selection {selection['selection_id']} references missing state")
    if selected_state["lineage_id"] != context["lineage_id"]:
        raise ValueError(f"selection {selection['selection_id']} crosses parameter lineages")
    if selection["selection_status"] not in _SELECTION_STATUSES:
        raise ValueError(f"unsupported selection_status: {selection['selection_status']}")
    if not selection.get("selection_intent_label"):
        raise ValueError("selection intent label is required")
    if not selection.get("selection_reason"):
        raise ValueError("selection reason is required")

    for key in ("hardware_write_back", "rollback_mutation"):
        if selection[key] != "not_performed":
            raise ValueError(f"selection claim {key} must be not_performed")
    if selection["current_hardware_state_claim"] != "not_claimed":
        raise ValueError("selection must not claim current hardware state")

    _validate_requirement(selection, context, selected_state)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    lineages = _lineages_by_id(source)
    states = _states_by_id(source)
    contexts = _contexts_by_id(source)
    _selections_by_id(source)

    for state in source["parameter_states"]:
        _validate_state(state, lineages)
    for context in source["selection_contexts"]:
        _validate_context(context, lineages)
    for selection in source["parameter_state_selections"]:
        _validate_selection(selection, states, contexts)


def _lineage_summary(lineage: dict[str, Any]) -> dict[str, Any]:
    return {
        "lineage_id": lineage["lineage_id"],
        "lineage_label": lineage["lineage_label"],
        "lineage_purpose": lineage["lineage_purpose"],
        "target_scope": copy.deepcopy(lineage["target_scope"]),
    }


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": state["state_id"],
        "lineage_id": state["lineage_id"],
        "state_label": state["state_label"],
        "state_kind": state["state_kind"],
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "accepted_review_id": state.get("accepted_review_id"),
        "trusted_entry_count": len(state.get("trusted_entry_paths", [])),
        "entry_count": len(state["entries"]),
    }


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "context_kind": context["context_kind"],
        "context_label": context["context_label"],
        "lineage_id": context["lineage_id"],
        "required_selected_state": context["required_selected_state"],
        "target_scope": copy.deepcopy(context["target_scope"]),
        "context_state": context["context_state"],
    }


def _selection_summary(
    selection: dict[str, Any],
    selected_state: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "selection_id": selection["selection_id"],
        "context_id": selection["context_id"],
        "context_kind": context["context_kind"],
        "selected_state_id": selection["selected_state_id"],
        "selected_state_label": selected_state["state_label"],
        "selected_state_readiness": selected_state["readiness"],
        "selected_state_trust_status": selected_state["trust_status"],
        "selection_status": selection["selection_status"],
        "selection_intent_label": selection["selection_intent_label"],
        "intent_role": "scenario_label_not_lifecycle",
        "selection_reason": selection["selection_reason"],
        "selected_at": selection["selected_at"],
        "selected_by_role": selection["selected_by_role"],
        "side_effects": {
            "hardware_write_back": selection["hardware_write_back"],
            "current_hardware_state_claim": selection["current_hardware_state_claim"],
            "rollback_mutation": selection["rollback_mutation"],
        },
    }


def _review_findings(
    selections: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for selection in selections:
        context = contexts[selection["context_id"]]
        selected_state = states[selection["selected_state_id"]]
        if selection["selection_intent_label"] in {
            "reuse_previous_working_state",
            "recover_known_good_context",
        }:
            findings.append(
                {
                    "selection_id": selection["selection_id"],
                    "kind": "intent_label_is_scenario_semantics",
                    "reason": "selection intent is carried for review but does not define a special lifecycle model",
                }
            )
        if context["required_selected_state"] == "committed_trusted_for_declared_scope":
            findings.append(
                {
                    "selection_id": selection["selection_id"],
                    "kind": "context_requirement_satisfied",
                    "selected_state_id": selected_state["state_id"],
                    "required_selected_state": context["required_selected_state"],
                }
            )
    return findings


def build_parameter_state_selection_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured parameter-state selection context summary."""
    request_model = ParameterStateSelectionRequest.from_dict(source)
    source = request_model.source
    states = _states_by_id(source)
    contexts = _contexts_by_id(source)
    summary = {
        "policy": copy.deepcopy(source["parameter_state_selection_policy"]),
        "lineages": [_lineage_summary(lineage) for lineage in source["lineages"]],
        "selection_contexts": [
            _context_summary(context) for context in source["selection_contexts"]
        ],
        "selected_states": [
            _state_summary(states[selection["selected_state_id"]])
            for selection in source["parameter_state_selections"]
        ],
        "parameter_state_selections": [
            _selection_summary(
                selection, states[selection["selected_state_id"]], contexts[selection["context_id"]]
            )
            for selection in source["parameter_state_selections"]
        ],
        "review_findings": _review_findings(source["parameter_state_selections"], states, contexts),
    }
    return ParameterStateSelectionResult(summary=summary).to_dict()
