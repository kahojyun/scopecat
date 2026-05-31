"""Structured summary builder for trusted parameter drift projection.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not render plots, write parameters, inspect current
instrument state, mutate external JSON files, perform schema migration, apply
rollback, or define a shared domain model.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "parameter_authority": "scopecat_parameter_state",
    "projection": "side_effect_free_summary",
    "history_source": "accepted_committed_states_only",
    "trusted_entries": "declared_trusted_entry_paths_only",
    "drift_plot_rendering": "not_performed",
    "hardware_write_back": "not_performed",
    "current_hardware_state_claim": "not_claimed",
    "schema_migration": "not_performed",
}

_INCLUDE_ELIGIBILITY = "include_declared_trusted_entries_only"
_EXCLUDE_ELIGIBILITIES = {
    "exclude_from_trusted_drift_plots",
    "exclude_exploratory_from_trusted_drift_plots",
}
_PROJECTION_STATES = {
    "computed_summary_not_rendered",
    "review_required",
}


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


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


def _projections_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["drift_projections"], "projection_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["parameter_trusted_drift_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("parameter trusted drift policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"parameter trusted drift policy {key} must be {expected}")


def _validate_state(state: dict[str, Any], lineages: dict[str, dict[str, Any]]) -> None:
    if state["lineage_id"] not in lineages:
        raise ValueError(f"state {state['state_id']} references missing lineage")

    eligibility = state["history_plot_eligibility"]
    if eligibility not in _EXCLUDE_ELIGIBILITIES | {_INCLUDE_ELIGIBILITY}:
        raise ValueError(f"unsupported history_plot_eligibility: {eligibility}")

    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate entry path")

    trusted_entry_paths = state.get("trusted_entry_paths", [])
    if len(trusted_entry_paths) != len(set(trusted_entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate trusted entry path")
    for trusted_path in trusted_entry_paths:
        if trusted_path not in entry_paths:
            raise ValueError(f"state {state['state_id']} trusts missing entry path")

    if eligibility == _INCLUDE_ELIGIBILITY:
        if state["state_kind"] != "committed_snapshot":
            raise ValueError("trusted drift included state must be committed_snapshot")
        if state["trust_status"] != "trusted_for_declared_scope":
            raise ValueError("trusted drift included state must be trusted for declared scope")
        if not state.get("accepted_review_id"):
            raise ValueError("trusted drift included state requires accepted_review_id")
        if not trusted_entry_paths:
            raise ValueError("trusted drift included state requires trusted entry paths")


def _validate_projection(
    projection: dict[str, Any],
    lineages: dict[str, dict[str, Any]],
    states: dict[str, dict[str, Any]],
) -> None:
    if projection["lineage_id"] not in lineages:
        raise ValueError(f"projection {projection['projection_id']} references missing lineage")
    if projection["projection_state"] not in _PROJECTION_STATES:
        raise ValueError(f"unsupported projection_state: {projection['projection_state']}")
    if not projection["parameter_paths"]:
        raise ValueError("trusted drift projection requires parameter paths")
    if len(projection["parameter_paths"]) != len(set(projection["parameter_paths"])):
        raise ValueError("trusted drift projection contains duplicate parameter path")
    if not projection["state_ids"]:
        raise ValueError("trusted drift projection requires state_ids")
    if len(projection["state_ids"]) != len(set(projection["state_ids"])):
        raise ValueError("trusted drift projection contains duplicate state_id")

    for state_id in projection["state_ids"]:
        state = states.get(state_id)
        if state is None:
            raise ValueError(f"projection {projection['projection_id']} references missing state")
        if state["lineage_id"] != projection["lineage_id"]:
            raise ValueError(f"projection {projection['projection_id']} crosses parameter lineages")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    lineages = _lineages_by_id(source)
    states = _states_by_id(source)
    _projections_by_id(source)

    for state in source["parameter_states"]:
        _validate_state(state, lineages)
    for projection in source["drift_projections"]:
        _validate_projection(projection, lineages, states)


def _lineage_summary(lineage: dict[str, Any]) -> dict[str, Any]:
    return {
        "lineage_id": lineage["lineage_id"],
        "lineage_label": lineage["lineage_label"],
        "lineage_purpose": lineage["lineage_purpose"],
        "target_scope": copy.deepcopy(lineage["target_scope"]),
    }


def _entry_lookup(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(state["entries"], "path")


def _exclude_reason(state: dict[str, Any]) -> str:
    if state["history_plot_eligibility"] == "exclude_exploratory_from_trusted_drift_plots":
        return "exploratory state is not trusted calibrated history"
    return "state is not eligible for trusted drift history"


def _projection_findings(
    projection: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for state_id in projection["state_ids"]:
        state = states[state_id]
        if state["history_plot_eligibility"] != _INCLUDE_ELIGIBILITY:
            findings.append(
                {
                    "projection_id": projection["projection_id"],
                    "kind": "excluded_state",
                    "state_id": state_id,
                    "reason": _exclude_reason(state),
                }
            )
            continue

        entries = _entry_lookup(state)
        trusted_paths = set(state["trusted_entry_paths"])
        for path in projection["parameter_paths"]:
            entry = entries.get(path)
            if entry is None:
                findings.append(
                    {
                        "projection_id": projection["projection_id"],
                        "kind": "missing_parameter_entry",
                        "state_id": state_id,
                        "path": path,
                        "reason": "requested parameter path is not present in this state",
                    }
                )
            elif path not in trusted_paths:
                findings.append(
                    {
                        "projection_id": projection["projection_id"],
                        "kind": "skipped_untrusted_entry",
                        "state_id": state_id,
                        "path": path,
                        "reason": "entry is not in declared trusted_entry_paths",
                    }
                )
            elif not _is_json_scalar(entry["value"]):
                findings.append(
                    {
                        "projection_id": projection["projection_id"],
                        "kind": "skipped_non_scalar_entry",
                        "state_id": state_id,
                        "path": path,
                        "reason": "trusted drift projection includes scalar values only",
                    }
                )
    return findings


def _point_for_entry(state: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": state["state_id"],
        "committed_at": state["committed_at"],
        "accepted_review_id": state["accepted_review_id"],
        "value": copy.deepcopy(entry["value"]),
        "trust": entry["trust"],
    }


def _path_series(
    projection: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    series = []
    for path in projection["parameter_paths"]:
        points = []
        unit = None
        label = None
        for state_id in projection["state_ids"]:
            state = states[state_id]
            if state["history_plot_eligibility"] != _INCLUDE_ELIGIBILITY:
                continue
            entry = _entry_lookup(state).get(path)
            if entry is None:
                continue
            if path not in set(state["trusted_entry_paths"]):
                continue
            if not _is_json_scalar(entry["value"]):
                continue
            unit = entry["unit"] if unit is None else unit
            label = entry["label"] if label is None else label
            points.append(_point_for_entry(state, entry))
        series.append(
            {
                "path": path,
                "label": label,
                "unit": unit,
                "point_count": len(points),
                "points": points,
            }
        )
    return series


def _state_filter_summary(
    projection: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    included = []
    excluded = []
    for state_id in projection["state_ids"]:
        state = states[state_id]
        if state["history_plot_eligibility"] == _INCLUDE_ELIGIBILITY:
            included.append(state_id)
        else:
            excluded.append(state_id)
    return {
        "included_state_ids": included,
        "excluded_state_ids": excluded,
        "included_state_count": len(included),
        "excluded_state_count": len(excluded),
    }


def _projection_summary(
    projection: dict[str, Any],
    states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "projection_id": projection["projection_id"],
        "lineage_id": projection["lineage_id"],
        "projection_state": projection["projection_state"],
        "rendered_plot": "not_performed",
        "state_filter": _state_filter_summary(projection, states),
        "path_series": _path_series(projection, states),
    }


def build_parameter_trusted_drift_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured trusted parameter drift projection summary."""
    _validate_references(source)
    states = _states_by_id(source)
    findings = []
    for projection in source["drift_projections"]:
        findings.extend(_projection_findings(projection, states))
    return {
        "policy": copy.deepcopy(source["parameter_trusted_drift_policy"]),
        "lineages": [_lineage_summary(lineage) for lineage in source["lineages"]],
        "drift_projections": [
            _projection_summary(projection, states) for projection in source["drift_projections"]
        ],
        "review_findings": findings,
    }
