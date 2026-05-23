"""Structured summary builder for parameter write compatibility output.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not write compatibility files, write parameters,
inspect current instrument state, mutate external JSON files, perform schema
migration, apply rollback, or define a shared domain model.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "parameter_authority": "scopecat_parameter_state",
    "external_compatibility_output": "planned_not_written",
    "file_write": "not_performed",
    "hardware_write_back": "not_performed",
    "current_hardware_state_claim": "not_claimed",
    "schema_migration": "not_performed",
    "external_json_authority": "not_claimed",
}

_OUTPUT_STATES = {
    "planned_not_written",
    "review_required",
}

_OUTPUT_FORMATS = {
    "legacy_parameters_json",
}

_EMIT_STATES = {
    "planned",
    "skipped_untrusted",
    "skipped_schema_limited",
}

_COMPATIBILITY_STATES = {
    "direct_scalar",
    "unsupported_table_shape",
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


def _states_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["parameter_states"], "state_id")


def _reviews_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["accepted_reviews"], "review_id")


def _outputs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["compatibility_outputs"], "output_id")


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["parameter_write_compatibility_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("parameter write compatibility policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"parameter write compatibility policy {key} must be {expected}")


def _validate_state(state: dict[str, Any]) -> None:
    if state["state_kind"] != "committed_snapshot":
        raise ValueError("compatibility output source state must be committed_snapshot")
    if state["trust_status"] != "trusted_for_declared_scope":
        raise ValueError("compatibility output source state must be trusted for declared scope")

    entry_paths = [entry["path"] for entry in state["entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate entry path")

    for entry in state["entries"]:
        if entry["compatibility_state"] not in _COMPATIBILITY_STATES:
            raise ValueError(f"unsupported compatibility_state: {entry['compatibility_state']}")

    trusted_entry_paths = state["trusted_entry_paths"]
    if len(trusted_entry_paths) != len(set(trusted_entry_paths)):
        raise ValueError(f"state {state['state_id']} contains duplicate trusted entry path")
    for trusted_path in trusted_entry_paths:
        if trusted_path not in entry_paths:
            raise ValueError(f"state {state['state_id']} trusts missing entry path")


def _validate_review(review: dict[str, Any], states: dict[str, dict[str, Any]]) -> None:
    if review["target_state_id"] not in states:
        raise ValueError(f"review {review['review_id']} references missing target state")
    if review["review_status"] != "accepted":
        raise ValueError("compatibility output requires accepted review")
    if not review["creates_durable_history"]:
        raise ValueError("compatibility output review must create durable history")


def _validate_output_entry(
    output: dict[str, Any],
    entry: dict[str, Any],
    source_state: dict[str, Any],
    state_entries: dict[str, dict[str, Any]],
) -> None:
    emit_state = entry["emit_state"]
    if emit_state not in _EMIT_STATES:
        raise ValueError(f"unsupported emit_state: {emit_state}")

    source_entry = state_entries.get(entry["path"])
    if source_entry is None:
        raise ValueError(f"output {output['output_id']} references missing parameter entry")

    trusted_paths = set(source_state["trusted_entry_paths"])
    compatibility_state = source_entry["compatibility_state"]
    is_trusted = entry["path"] in trusted_paths
    if emit_state == "planned":
        if not is_trusted:
            raise ValueError("planned compatibility entry must be trusted")
        if compatibility_state != "direct_scalar":
            raise ValueError("planned compatibility entry must be direct scalar")
        if not _is_json_scalar(source_entry["value"]):
            raise ValueError("planned compatibility entry value must be scalar")
        if "output_key" not in entry:
            raise ValueError("planned compatibility entry requires output_key")
    elif emit_state == "skipped_untrusted":
        if is_trusted:
            raise ValueError("skipped_untrusted entry must not be trusted")
        if not entry.get("reason"):
            raise ValueError("skipped compatibility entry requires reason")
    elif emit_state == "skipped_schema_limited":
        if not is_trusted:
            raise ValueError("skipped_schema_limited entry must be trusted")
        if compatibility_state != "unsupported_table_shape":
            raise ValueError("skipped_schema_limited entry must have unsupported table shape")
        if not entry.get("reason"):
            raise ValueError("skipped compatibility entry requires reason")


def _validate_output(
    output: dict[str, Any],
    states: dict[str, dict[str, Any]],
    reviews: dict[str, dict[str, Any]],
) -> None:
    source_state = states.get(output["source_state_id"])
    if source_state is None:
        raise ValueError(f"output {output['output_id']} references missing source state")

    review = reviews.get(output["source_state_review_id"])
    if review is None:
        raise ValueError(f"output {output['output_id']} references missing source state review")
    if review["target_state_id"] != output["source_state_id"]:
        raise ValueError("compatibility output review must target source state")
    if source_state["accepted_review_id"] != output["source_state_review_id"]:
        raise ValueError("compatibility output review must be accepted by source state")

    if output["output_state"] not in _OUTPUT_STATES:
        raise ValueError(f"unsupported output_state: {output['output_state']}")
    target = output["target"]
    if target["format"] not in _OUTPUT_FORMATS:
        raise ValueError(f"unsupported output format: {target['format']}")
    if not _path_is_relative(target["path"]):
        raise ValueError("compatibility output target path must be relative")

    claims = output["compatibility_claims"]
    for key in ("file_write", "hardware_write_back", "schema_migration"):
        if claims[key] != "not_performed":
            raise ValueError(f"compatibility output claim {key} must be not_performed")
    if claims["external_json_authority"] != "not_claimed":
        raise ValueError("compatibility output must not claim external JSON authority")

    state_entries = _records_by_key(source_state["entries"], "path")
    output_paths = [entry["path"] for entry in output["entries"]]
    if len(output_paths) != len(set(output_paths)):
        raise ValueError("compatibility output contains duplicate parameter entry path")
    if set(output_paths) != set(state_entries):
        raise ValueError("compatibility output entries must account for every source entry")

    seen_output_keys = set()
    for entry in output["entries"]:
        output_key = entry.get("output_key")
        if output_key is not None:
            if output_key in seen_output_keys:
                raise ValueError("compatibility output contains duplicate output_key")
            seen_output_keys.add(output_key)
        _validate_output_entry(output, entry, source_state, state_entries)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    states = _states_by_id(source)
    reviews = _reviews_by_id(source)
    _outputs_by_id(source)

    for state in source["parameter_states"]:
        _validate_state(state)
    for review in source["accepted_reviews"]:
        _validate_review(review, states)
    for output in source["compatibility_outputs"]:
        _validate_output(output, states, reviews)


def _source_state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": state["state_id"],
        "lineage_id": state["lineage_id"],
        "state_label": state["state_label"],
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "entry_count": len(state["entries"]),
        "trusted_entry_count": len(state["trusted_entry_paths"]),
    }


def _entry_lookup(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    states = _states_by_id(source)
    entries = {}
    for state in states.values():
        entries[state["state_id"]] = _records_by_key(state["entries"], "path")
    return entries


def _output_entry_summary(
    entry: dict[str, Any],
    source_entry: dict[str, Any],
) -> dict[str, Any]:
    output = {
        "path": entry["path"],
        "emit_state": entry["emit_state"],
        "compatibility_state": source_entry["compatibility_state"],
    }
    if "output_key" in entry:
        output["output_key"] = entry["output_key"]
    if entry["emit_state"] == "planned":
        output["value"] = copy.deepcopy(source_entry["value"])
        output["unit"] = source_entry["unit"]
    if "reason" in entry:
        output["reason"] = entry["reason"]
    return output


def _emit_state_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {state: 0 for state in sorted(_EMIT_STATES)}
    for entry in entries:
        counts[entry["emit_state"]] += 1
    return {state: count for state, count in counts.items() if count}


def _output_summary(
    output: dict[str, Any],
    entries_by_state: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    state_entries = entries_by_state[output["source_state_id"]]
    return {
        "output_id": output["output_id"],
        "source_state_id": output["source_state_id"],
        "source_state_review_id": output["source_state_review_id"],
        "output_state": output["output_state"],
        "target": {
            "path": output["target"]["path"],
            "format": output["target"]["format"],
            "target_role": "external_compatibility_target",
        },
        "emit_state_counts": _emit_state_counts(output["entries"]),
        "entries": [
            _output_entry_summary(entry, state_entries[entry["path"]])
            for entry in output["entries"]
        ],
    }


def _review_findings(output: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for entry in output["entries"]:
        if entry["emit_state"] == "planned":
            continue
        findings.append(
            {
                "output_id": output["output_id"],
                "kind": entry["emit_state"],
                "path": entry["path"],
                "reason": entry["reason"],
            }
        )
    return findings


def build_parameter_write_compatibility_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured parameter write compatibility output summary."""
    _validate_references(source)
    entries_by_state = _entry_lookup(source)
    findings = []
    for output in source["compatibility_outputs"]:
        findings.extend(_review_findings(output))
    return {
        "policy": copy.deepcopy(source["parameter_write_compatibility_policy"]),
        "source_states": [_source_state_summary(state) for state in source["parameter_states"]],
        "compatibility_outputs": [
            _output_summary(output, entries_by_state) for output in source["compatibility_outputs"]
        ],
        "review_findings": findings,
    }
