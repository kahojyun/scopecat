"""Structured summary builder for parameter state management.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not write parameters, inspect current instrument
state, mutate external JSON files, perform rollback, define branch/tag/commit
semantics, generate drift plots, or define a shared domain model.
"""

from __future__ import annotations

import copy
from typing import Any

_STATE_ROLES = {
    "seed_snapshot": "base_seed_state",
    "committed_snapshot": "committed_parameter_state",
}

_DIFF_KINDS = ("changed", "added", "removed")


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


def _drafts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["draft_changes"], "draft_id")


def _reviews_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["reviewable_diffs"], "review_id")


def _validate_state(
    state: dict[str, Any],
    lineages: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
) -> None:
    if state["state_kind"] not in _STATE_ROLES:
        raise ValueError(f"unsupported state_kind: {state['state_kind']}")
    if state["lineage_id"] not in lineages:
        raise ValueError(f"state {state['state_id']} references missing lineage")

    parent_state_id = state.get("parent_state_id")
    if parent_state_id is not None:
        parent = states.get(parent_state_id)
        if parent is None:
            raise ValueError(f"state {state['state_id']} references missing parent state")
        if parent["lineage_id"] != state["lineage_id"]:
            raise ValueError(f"state {state['state_id']} parent belongs to wrong lineage")

    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate entry path")

    for trusted_path in state.get("trusted_entry_paths", []):
        if trusted_path not in entry_paths:
            raise ValueError(f"state {state['state_id']} trusts missing entry path")


def _validate_draft(
    draft: dict[str, Any],
    lineages: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
) -> None:
    if draft["lineage_id"] not in lineages:
        raise ValueError(f"draft {draft['draft_id']} references missing lineage")
    base_state = states.get(draft["base_state_id"])
    if base_state is None:
        raise ValueError(f"draft {draft['draft_id']} references missing base state")
    if base_state["lineage_id"] != draft["lineage_id"]:
        raise ValueError(f"draft {draft['draft_id']} base state belongs to wrong lineage")


def _validate_review(
    review: dict[str, Any],
    drafts: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
) -> None:
    draft = drafts.get(review["draft_id"])
    if draft is None:
        raise ValueError(f"review {review['review_id']} references missing draft")
    base_state = states.get(review["base_state_id"])
    target_state = states.get(review["target_state_id"])
    if base_state is None:
        raise ValueError(f"review {review['review_id']} references missing base state")
    if target_state is None:
        raise ValueError(f"review {review['review_id']} references missing target state")
    if review["base_state_id"] != draft["base_state_id"]:
        raise ValueError(f"review {review['review_id']} base state does not match draft")
    if base_state["lineage_id"] != target_state["lineage_id"]:
        raise ValueError(f"review {review['review_id']} crosses parameter lineages")

    target_review_id = target_state.get("accepted_review_id")
    if review["review_status"] == "accepted" and target_review_id != review["review_id"]:
        raise ValueError(f"review {review['review_id']} is not linked from target state")

    for entry in review["diff_entries"]:
        if entry["kind"] not in _DIFF_KINDS:
            raise ValueError(f"unsupported diff kind: {entry['kind']}")


def _validate_measurement(
    measurement: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> None:
    state_id = measurement["selected_parameter_state_id"]
    if state_id not in states:
        raise ValueError(
            f"measurement {measurement['measurement_id']} references missing parameter state"
        )
    if measurement["hardware_state_claim"] != "not_recorded":
        raise ValueError("measurement hardware_state_claim must remain not_recorded")


def _validate_references(source: dict[str, Any]) -> None:
    lineages = _lineages_by_id(source)
    states = _states_by_id(source)
    drafts = _drafts_by_id(source)
    _reviews_by_id(source)

    for state in source["parameter_states"]:
        _validate_state(state, lineages, states)
    for draft in source["draft_changes"]:
        _validate_draft(draft, lineages, states)
    for review in source["reviewable_diffs"]:
        _validate_review(review, drafts, states)
    for measurement in source["measurements"]:
        _validate_measurement(measurement, states)


def _lineage_summary(lineage: dict[str, Any]) -> dict[str, Any]:
    return {
        "lineage_id": lineage["lineage_id"],
        "lineage_label": lineage["lineage_label"],
        "lineage_purpose": lineage["lineage_purpose"],
        "purpose_kind": "domain_label",
        "target_scope": copy.deepcopy(lineage["target_scope"]),
    }


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    output = {
        "state_id": state["state_id"],
        "role": _STATE_ROLES[state["state_kind"]],
        "lineage_id": state["lineage_id"],
        "parent_state_id": state["parent_state_id"],
        "state_label": state["state_label"],
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "history_plot_eligibility": state["history_plot_eligibility"],
        "entry_count": len(state["entries"]),
        "trusted_entry_paths": copy.deepcopy(state.get("trusted_entry_paths", [])),
    }
    if "accepted_review_id" in state:
        output["accepted_review_id"] = state["accepted_review_id"]
    return output


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_id": draft["draft_id"],
        "base_state_id": draft["base_state_id"],
        "lineage_id": draft["lineage_id"],
        "durable_history": draft["durable_history"],
        "draft_status": draft["draft_status"],
    }


def _diff_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {kind: sum(1 for entry in entries if entry["kind"] == kind) for kind in _DIFF_KINDS}


def _diff_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": entry["kind"],
        "path": entry["path"],
        "old_value": entry["old_value"],
        "new_value": entry["new_value"],
        "unit": entry["unit"],
    }


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": review["review_id"],
        "draft_id": review["draft_id"],
        "base_state_id": review["base_state_id"],
        "target_state_id": review["target_state_id"],
        "review_status": review["review_status"],
        "creates_durable_history": review["creates_durable_history"],
        "diff_counts": _diff_counts(review["diff_entries"]),
        "diff_entries": [_diff_entry_summary(entry) for entry in review["diff_entries"]],
    }


def _measurement_reference_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_id": measurement["measurement_id"],
        "experiment_label": measurement["experiment_label"],
        "selected_parameter_state_id": measurement["selected_parameter_state_id"],
        "selection_time": measurement["selection_time"],
        "hardware_state_claim": measurement["hardware_state_claim"],
    }


def build_parameter_state_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured parameter-state summary from explicit fixture input."""
    _validate_references(source)
    return {
        "lineages": [_lineage_summary(lineage) for lineage in source["lineages"]],
        "states": [_state_summary(state) for state in source["parameter_states"]],
        "drafts": [_draft_summary(draft) for draft in source["draft_changes"]],
        "reviewable_changes": [_review_summary(review) for review in source["reviewable_diffs"]],
        "measurement_references": [
            _measurement_reference_summary(measurement) for measurement in source["measurements"]
        ],
        "warnings": [],
    }
