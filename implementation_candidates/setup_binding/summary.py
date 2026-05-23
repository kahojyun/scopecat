"""Structured summary builder for setup binding.

This module validates explicit setup-binding fixture records. It does not
inspect hardware, mutate parameters, execute project generator code, interpret
user/project-defined inner payloads, define station registry ownership, or
accept a shared snapshot framework.
"""

from __future__ import annotations

import copy
from typing import Any

_INPUT_SNAPSHOT_LIFECYCLE = {
    "parameter_state": "parameter_lineage_and_review",
    "setup_binding": "binding_snapshot_and_diff",
    "station_registry": "station_context_reference",
}
_REQUIRED_MEASUREMENT_INPUTS = set(_INPUT_SNAPSHOT_LIFECYCLE)

_EXPECTED_INNER_PAYLOAD_POLICY = {
    "ownership": "user_project_defined",
    "scopecat_default_handling": "opaque_payload",
    "declared_summary_fields": ["logical_bindings", "generated_views"],
    "downstream_use": "project_runtime_code",
}

_DIFF_KINDS = {"changed", "added", "removed"}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _station_registries_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["station_registry_contexts"], "registry_id")


def _parameter_states_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_state_summaries"], "snapshot_id")


def _setup_bindings_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["setup_binding_snapshots"], "snapshot_id")


def _measurement_refs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["measurements"], "measurement_id")


def _generated_views_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output = {}
    for snapshot in source["setup_binding_snapshots"]:
        for view in snapshot["generated_views"]:
            view_id = view["view_id"]
            if view_id in output:
                raise ValueError(f"duplicate view_id: {view_id}")
            output[view_id] = view
    return output


def _generated_view_ids_by_snapshot(snapshot: dict[str, Any]) -> set[str]:
    return {view["view_id"] for view in snapshot["generated_views"]}


def _logical_bindings_by_key(snapshot: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    output = {}
    for logical_binding in snapshot["logical_bindings"]:
        key = (logical_binding["logical_entity"], logical_binding["role"])
        if key in output:
            raise ValueError(
                f"duplicate logical binding in {snapshot['snapshot_id']}: {key[0]} {key[1]}"
            )
        output[key] = logical_binding
    return output


def _selected_setup_binding_ids(source: dict[str, Any]) -> set[str]:
    selected = set()
    for measurement in source["measurements"]:
        for input_ref in measurement["inputs"]:
            if input_ref["name"] == "setup_binding":
                selected.add(input_ref["snapshot_id"])
    return selected


def _prior_setup_binding_ids(source: dict[str, Any]) -> set[str]:
    selected = _selected_setup_binding_ids(source)
    prior = set()
    for diff in source["binding_diffs"]:
        if diff["to_snapshot_id"] in selected:
            prior.add(diff["from_snapshot_id"])
    return prior


def _validate_inner_payload_policy(snapshot: dict[str, Any]) -> None:
    policy = snapshot["inner_payload_policy"]
    if set(policy) != set(_EXPECTED_INNER_PAYLOAD_POLICY):
        raise ValueError("inner payload policy must match expected shape")
    for key, expected in _EXPECTED_INNER_PAYLOAD_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"inner payload policy {key} must be {expected}")


def _validate_station_registry(registry: dict[str, Any]) -> None:
    if registry["registry_scope"] != "station_configuration":
        raise ValueError("station registry scope must remain station_configuration")
    if registry["contains_connection_payloads"]:
        raise ValueError("station registry connection payloads must remain redacted")
    _records_by_key(registry["resource_labels"], "resource_id")


def _validate_parameter_state(parameter_state: dict[str, Any]) -> None:
    if parameter_state["snapshot_family"] != "parameter_state":
        raise ValueError("parameter state snapshot_family must be parameter_state")


def _validate_setup_binding(
    snapshot: dict[str, Any],
    station_registries: dict[str, dict[str, Any]],
) -> None:
    if snapshot["snapshot_family"] != "setup_binding":
        raise ValueError("setup binding snapshot_family must be setup_binding")
    _validate_inner_payload_policy(snapshot)
    registry_id = snapshot["selected_registry_id"]
    if registry_id not in station_registries:
        raise ValueError(f"setup binding references missing station registry: {registry_id}")
    registry_resources = {
        item["resource_id"] for item in station_registries[registry_id]["resource_labels"]
    }
    for logical_binding in snapshot["logical_bindings"]:
        resource_id = logical_binding["registry_resource_id"]
        if resource_id not in registry_resources:
            raise ValueError(f"setup binding references missing registry resource: {resource_id}")
    _logical_bindings_by_key(snapshot)
    for artifact in snapshot["source_artifacts"]:
        if artifact["artifact_kind"] == "project_generator_reference":
            if artifact.get("execution_claim") != "not_executed_by_fixture":
                raise ValueError("project generator references must not claim execution")


def _validate_diff(diff: dict[str, Any], setup_bindings: dict[str, dict[str, Any]]) -> None:
    if diff["from_snapshot_id"] not in setup_bindings:
        raise ValueError("binding diff references missing from_snapshot_id")
    if diff["to_snapshot_id"] not in setup_bindings:
        raise ValueError("binding diff references missing to_snapshot_id")
    from_bindings = _logical_bindings_by_key(setup_bindings[diff["from_snapshot_id"]])
    to_bindings = _logical_bindings_by_key(setup_bindings[diff["to_snapshot_id"]])
    for entry in diff["diff_entries"]:
        if entry["kind"] not in _DIFF_KINDS:
            raise ValueError(f"unsupported binding diff kind: {entry['kind']}")
        key = (entry["logical_entity"], entry["role"])
        from_binding = from_bindings.get(key)
        to_binding = to_bindings.get(key)
        old_label = entry["old_physical_resource_label"]
        new_label = entry["new_physical_resource_label"]
        if entry["kind"] == "changed":
            if from_binding is None or to_binding is None:
                raise ValueError("changed binding diff entry must exist in both snapshots")
            if from_binding["physical_resource_label"] != old_label:
                raise ValueError("changed binding diff old value does not match from snapshot")
            if to_binding["physical_resource_label"] != new_label:
                raise ValueError("changed binding diff new value does not match to snapshot")
            if old_label == new_label:
                raise ValueError("changed binding diff must change physical resource label")
        elif entry["kind"] == "added":
            if from_binding is not None:
                raise ValueError("added binding diff entry must be absent from from snapshot")
            if to_binding is None:
                raise ValueError("added binding diff entry must exist in to snapshot")
            if old_label is not None:
                raise ValueError("added binding diff old value must be null")
            if to_binding["physical_resource_label"] != new_label:
                raise ValueError("added binding diff new value does not match to snapshot")
        elif entry["kind"] == "removed":
            if from_binding is None:
                raise ValueError("removed binding diff entry must exist in from snapshot")
            if to_binding is not None:
                raise ValueError("removed binding diff entry must be absent from to snapshot")
            if from_binding["physical_resource_label"] != old_label:
                raise ValueError("removed binding diff old value does not match from snapshot")
            if new_label is not None:
                raise ValueError("removed binding diff new value must be null")


def _validate_measurement(
    measurement: dict[str, Any],
    parameter_states: dict[str, dict[str, Any]],
    setup_bindings: dict[str, dict[str, Any]],
    station_registries: dict[str, dict[str, Any]],
    generated_views: dict[str, dict[str, Any]],
) -> None:
    seen_input_names = set()
    input_refs_by_name = {}
    for input_ref in measurement["inputs"]:
        name = input_ref["name"]
        if name in seen_input_names:
            raise ValueError(f"measurement contains duplicate input name: {name}")
        seen_input_names.add(name)
        input_refs_by_name[name] = input_ref
        snapshot_id = input_ref["snapshot_id"]
        if name == "parameter_state" and snapshot_id not in parameter_states:
            raise ValueError("measurement references missing parameter state")
        elif name == "setup_binding" and snapshot_id not in setup_bindings:
            raise ValueError("measurement references missing setup binding")
        elif name == "station_registry" and snapshot_id not in station_registries:
            raise ValueError("measurement references missing station registry")
        elif name not in _INPUT_SNAPSHOT_LIFECYCLE:
            raise ValueError(f"unsupported measurement input family: {name}")

    missing_input_names = _REQUIRED_MEASUREMENT_INPUTS - seen_input_names
    if missing_input_names:
        missing = ", ".join(sorted(missing_input_names))
        raise ValueError(f"measurement missing required input family: {missing}")

    selected_setup_binding = setup_bindings[input_refs_by_name["setup_binding"]["snapshot_id"]]
    selected_station_registry_id = input_refs_by_name["station_registry"]["snapshot_id"]
    if selected_setup_binding["selected_registry_id"] != selected_station_registry_id:
        raise ValueError("measurement station registry input must match selected setup binding")

    selected_view_ids = _generated_view_ids_by_snapshot(selected_setup_binding)
    for view_id in measurement["runtime_context_refs"]:
        if view_id not in generated_views:
            raise ValueError(f"measurement references missing generated view: {view_id}")
        if view_id not in selected_view_ids:
            raise ValueError(
                "measurement runtime context ref must belong to selected setup binding"
            )
    if measurement["hardware_state_claim"] != "not_recorded":
        raise ValueError("measurement hardware state must remain not_recorded")


def _validate_references(source: dict[str, Any]) -> None:
    station_registries = _station_registries_by_id(source)
    parameter_states = _parameter_states_by_id(source)
    setup_bindings = _setup_bindings_by_id(source)
    _measurement_refs_by_id(source)
    generated_views = _generated_views_by_id(source)

    for registry in source["station_registry_contexts"]:
        _validate_station_registry(registry)
    for parameter_state in source["parameter_state_summaries"]:
        _validate_parameter_state(parameter_state)
    for snapshot in source["setup_binding_snapshots"]:
        _validate_setup_binding(snapshot, station_registries)
    for diff in source["binding_diffs"]:
        _validate_diff(diff, setup_bindings)
    for measurement in source["measurements"]:
        _validate_measurement(
            measurement,
            parameter_states,
            setup_bindings,
            station_registries,
            generated_views,
        )


def _station_registry_summary(registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "registry_id": registry["registry_id"],
        "registry_label": registry["registry_label"],
        "registry_scope": registry["registry_scope"],
        "contains_connection_payloads": registry["contains_connection_payloads"],
        "resource_count": len(registry["resource_labels"]),
    }


def _input_snapshot_families(source: dict[str, Any]) -> list[dict[str, str]]:
    families = []
    seen = set()
    for measurement in source["measurements"]:
        for input_ref in measurement["inputs"]:
            name = input_ref["name"]
            if name in seen:
                continue
            seen.add(name)
            families.append(
                {
                    "name": name,
                    "snapshot_id": input_ref["snapshot_id"],
                    "lifecycle_semantics": _INPUT_SNAPSHOT_LIFECYCLE[name],
                }
            )
    return families


def _setup_binding_role(snapshot_id: str, selected_ids: set[str], prior_ids: set[str]) -> str:
    if snapshot_id in selected_ids:
        return "selected_binding_snapshot"
    if snapshot_id in prior_ids:
        return "prior_binding_snapshot"
    return "referenced_binding_snapshot"


def _setup_binding_summary(
    snapshot: dict[str, Any],
    selected_ids: set[str],
    prior_ids: set[str],
) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "role": _setup_binding_role(snapshot["snapshot_id"], selected_ids, prior_ids),
        "snapshot_label": snapshot["snapshot_label"],
        "sample_id": snapshot["sample_id"],
        "cooldown_id": snapshot["cooldown_id"],
        "selected_registry_id": snapshot["selected_registry_id"],
        "inner_payload_handling": "opaque_payload_with_declared_summary_fields",
        "logical_binding_count": len(snapshot["logical_bindings"]),
        "generated_view_count": len(snapshot["generated_views"]),
    }


def _selected_setup_bindings(source: dict[str, Any]) -> list[dict[str, Any]]:
    selected_ids = _selected_setup_binding_ids(source)
    return [
        snapshot
        for snapshot in source["setup_binding_snapshots"]
        if snapshot["snapshot_id"] in selected_ids
    ]


def _logical_binding_summary(
    snapshot: dict[str, Any],
    logical_binding: dict[str, Any],
) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "logical_entity": logical_binding["logical_entity"],
        "logical_kind": logical_binding["logical_kind"],
        "role": logical_binding["role"],
        "physical_resource_label": logical_binding["physical_resource_label"],
    }


def _generated_view_summary(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "view_id": view["view_id"],
        "view_kind": view["view_kind"],
        "consumer_hint": view["consumer_hint"],
        "entry_count": len(view["entries"]),
    }


def _diff_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        kind: sum(1 for entry in entries if entry["kind"] == kind) for kind in sorted(_DIFF_KINDS)
    }


def _ordered_diff_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = _diff_counts(entries)
    return {
        "changed": counts["changed"],
        "added": counts["added"],
        "removed": counts["removed"],
    }


def _diff_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": entry["kind"],
        "logical_entity": entry["logical_entity"],
        "role": entry["role"],
        "old_physical_resource_label": entry["old_physical_resource_label"],
        "new_physical_resource_label": entry["new_physical_resource_label"],
    }


def _binding_diff_summary(diff: dict[str, Any]) -> dict[str, Any]:
    return {
        "diff_id": diff["diff_id"],
        "from_snapshot_id": diff["from_snapshot_id"],
        "to_snapshot_id": diff["to_snapshot_id"],
        "diff_counts": _ordered_diff_counts(diff["diff_entries"]),
        "diff_entries": [_diff_entry_summary(entry) for entry in diff["diff_entries"]],
    }


def _measurement_summary(measurement: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_id": measurement["measurement_id"],
        "experiment_label": measurement["experiment_label"],
        "run_start_time": measurement["run_start_time"],
        "logical_targets": copy.deepcopy(measurement["logical_targets"]),
        "inputs": copy.deepcopy(measurement["inputs"]),
        "runtime_context_refs": copy.deepcopy(measurement["runtime_context_refs"]),
        "hardware_state_claim": measurement["hardware_state_claim"],
    }


def _attention(source: dict[str, Any]) -> list[dict[str, str]]:
    attention = []
    for diff in source["binding_diffs"]:
        for entry in diff["diff_entries"]:
            if entry["kind"] != "changed":
                continue
            attention.append(
                {
                    "code": "binding_changed_since_prior_calibration",
                    "severity": "review",
                    "basis": (
                        f"{entry['logical_entity']} {entry['role']} changed from "
                        f"{entry['old_physical_resource_label']} to "
                        f"{entry['new_physical_resource_label']} relative to the "
                        "prior setup-binding snapshot."
                    ),
                    "does_not_claim": "parameter_state_invalid",
                }
            )
    return attention


def build_setup_binding_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured setup-binding summary from explicit fixture input."""
    _validate_references(source)
    selected_ids = _selected_setup_binding_ids(source)
    prior_ids = _prior_setup_binding_ids(source)
    selected_snapshots = _selected_setup_bindings(source)
    return {
        "station_registry_contexts": [
            _station_registry_summary(registry) for registry in source["station_registry_contexts"]
        ],
        "input_snapshot_families": _input_snapshot_families(source),
        "setup_bindings": [
            _setup_binding_summary(snapshot, selected_ids, prior_ids)
            for snapshot in source["setup_binding_snapshots"]
        ],
        "logical_bindings": [
            _logical_binding_summary(snapshot, logical_binding)
            for snapshot in selected_snapshots
            for logical_binding in snapshot["logical_bindings"]
        ],
        "generated_views": [
            _generated_view_summary(view)
            for snapshot in selected_snapshots
            for view in snapshot["generated_views"]
        ],
        "binding_diffs": [_binding_diff_summary(diff) for diff in source["binding_diffs"]],
        "measurement_references": [
            _measurement_summary(measurement) for measurement in source["measurements"]
        ],
        "attention": _attention(source),
    }
