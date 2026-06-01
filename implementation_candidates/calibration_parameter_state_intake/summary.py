"""Parameter-state intake from accepted calibration handoff.

This module is a side-effect-free implementation candidate. It consumes a
validated calibration accepted-write handoff summary and an explicit
parameter-state review acceptance, then projects a managed parameter-state
summary. It does not write storage, emit compatibility output, write hardware,
define rollback, execute calibration, or extract a shared parameter schema.
"""

from __future__ import annotations

import copy
from typing import Any

from implementation_candidates.calibration_accepted_write_handoff import (
    build_calibration_accepted_write_handoff_summary,
)

_EXPECTED_POLICY = {
    "input_authority": "validated_calibration_accepted_write_handoff",
    "intake_authority": "parameter_state_management_route",
    "review_required": "explicit_parameter_state_review_acceptance",
    "managed_parameter_state_creation": "summary_only_not_written",
    "durable_history": "summary_only_not_written",
    "calibration_payload_handling": "summary_only",
    "storage_mutation": "not_performed",
    "external_compatibility_output": "not_produced",
    "hardware_write_back": "not_performed",
    "rollback": "not_defined",
    "calibration_execution": "not_performed",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
}

_REVIEW_STATUSES = {"accepted"}
_MANAGED_STATE_KINDS = {"committed_snapshot"}
_READINESS = {"partially_calibrated"}
_TRUST_STATUS = {"trusted_for_declared_scope", "not_fully_trusted"}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["calibration_parameter_state_intake_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("calibration parameter-state intake policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"calibration parameter-state intake policy {key} must be {expected}")


def _validate_side_effects(source: dict[str, Any]) -> None:
    side_effects = source["side_effect_claims"]
    for key in (
        "storage_mutation",
        "hardware_write_back",
        "calibration_execution",
    ):
        if side_effects[key] != "not_performed":
            raise ValueError(f"side effect claim {key} must be not_performed")
    if side_effects["external_compatibility_output"] != "not_produced":
        raise ValueError("side effect claim external_compatibility_output must be not_produced")
    if side_effects["rollback"] != "not_defined":
        raise ValueError("side effect claim rollback must be not_defined")
    if side_effects["durable_history"] != "summary_only_not_written":
        raise ValueError("side effect claim durable_history must be summary_only_not_written")


def _handoff_requests_by_id(handoff_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(handoff_summary["handoff_requests"], "handoff_id")


def _accepted_writes_by_id(handoff_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(handoff_summary["accepted_proposed_writes"], "write_id")


def _step_records_by_id(handoff_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(handoff_summary["calibration_step_records"], "step_record_id")


def _base_contexts_by_id(handoff_input: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(handoff_input["parameter_state_base_contexts"], "context_id")


def _base_entries_by_path(base_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(base_context["entries"], "path")


def _selected_handoff(
    source: dict[str, Any],
    handoff_summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    review = source["intake_review"]
    request = _handoff_requests_by_id(handoff_summary).get(review["handoff_id"])
    if request is None:
        raise ValueError("intake review references missing handoff request")
    if request["request_state"] != "ready_for_parameter_state_review":
        raise ValueError("parameter-state intake requires ready handoff request")
    if review["reviewed_request_state"] != request["request_state"]:
        raise ValueError("intake review request state must match handoff request")

    write = _accepted_writes_by_id(handoff_summary).get(request["write_id"])
    if write is None:
        raise ValueError("handoff request references missing accepted write")
    step = _step_records_by_id(handoff_summary).get(write["step_record_id"])
    if step is None:
        raise ValueError("accepted write references missing calibration step record")

    base_context = _base_contexts_by_id(source["calibration_handoff_input"]).get(
        write["before_summary"]["context_id"]
    )
    if base_context is None:
        raise ValueError("accepted write references missing base parameter context")

    return request, write, step, base_context


def _validate_review(review: dict[str, Any], request: dict[str, Any]) -> None:
    if review["review_status"] not in _REVIEW_STATUSES:
        raise ValueError("calibration parameter-state intake review must be accepted")
    if not review["accepted_by_role"]:
        raise ValueError("calibration parameter-state intake review requires accepted_by_role")
    if review["source_handoff_review_id"] != request["reviewable_diff_request"]["review_id"]:
        raise ValueError("intake review source_handoff_review_id must match handoff review")
    request_paths = [entry["path"] for entry in request["reviewable_diff_request"]["diff_entries"]]
    if review["accepted_diff_paths"] != request_paths:
        raise ValueError("intake review accepted diff paths must match handoff request")


def _expected_entries(
    request: dict[str, Any],
    base_context: dict[str, Any],
) -> list[dict[str, Any]]:
    base_entries = _base_entries_by_path(base_context)
    diff_by_path = _records_by_key(request["reviewable_diff_request"]["diff_entries"], "path")
    expected = []

    for path, entry in base_entries.items():
        diff = diff_by_path.get(path)
        if diff is None:
            expected.append(
                {
                    "path": path,
                    "value": copy.deepcopy(entry["value"]),
                    "unit": entry["unit"],
                    "trust": "review_accepted",
                    "source_ids": [f"base_parameter_state:{base_context['state_id']}"],
                    "change_source": "carried_forward_from_base_state",
                }
            )
            continue
        if diff["old_value"] != entry["value"]:
            raise ValueError("handoff diff old value must match base parameter state entry")
        if diff["unit"] != entry["unit"]:
            raise ValueError("handoff diff unit must match base parameter state entry")
        expected.append(
            {
                "path": path,
                "value": copy.deepcopy(diff["new_value"]),
                "unit": diff["unit"],
                "trust": "review_accepted",
                "source_ids": [f"calibration_handoff:{request['handoff_id']}"],
                "change_source": "accepted_calibration_handoff",
            }
        )

    missing_paths = set(diff_by_path) - set(base_entries)
    if missing_paths:
        raise ValueError("handoff diff references path missing from base parameter state")
    return expected


def _validate_managed_state(
    managed_state: dict[str, Any],
    review: dict[str, Any],
    request: dict[str, Any],
    write: dict[str, Any],
    base_context: dict[str, Any],
) -> None:
    if managed_state["state_kind"] not in _MANAGED_STATE_KINDS:
        raise ValueError("calibration intake managed state kind is unsupported")
    if managed_state["readiness"] not in _READINESS:
        raise ValueError("calibration intake managed state readiness is unsupported")
    if managed_state["trust_status"] not in _TRUST_STATUS:
        raise ValueError("calibration intake managed state trust_status is unsupported")
    if managed_state["created_by_review_id"] != review["review_id"]:
        raise ValueError("managed state must reference intake review")
    if managed_state["source_handoff_id"] != request["handoff_id"]:
        raise ValueError("managed state must reference source handoff")
    if managed_state["base_state_id"] != base_context["state_id"]:
        raise ValueError("managed state base_state_id must match base context")
    if managed_state["lineage"]["lineage_id"] != write["target_parameter"]["lineage_id"]:
        raise ValueError("managed state lineage must match accepted write target lineage")

    expected = _expected_entries(request, base_context)
    expected_by_path = _records_by_key(expected, "path")
    entries_by_path = _records_by_key(managed_state["entries"], "path")
    if set(entries_by_path) != set(expected_by_path):
        raise ValueError("managed state entries must match base state entries with handoff diff")
    for path, expected_entry in expected_by_path.items():
        entry = entries_by_path[path]
        for field in ("value", "unit", "trust", "source_ids", "change_source"):
            if entry[field] != expected_entry[field]:
                raise ValueError(f"managed state entry {field} must match handoff intake")

    trusted_paths = managed_state["trusted_entry_paths"]
    if len(trusted_paths) != len(set(trusted_paths)):
        raise ValueError("managed state contains duplicate trusted entry path")
    if set(trusted_paths) != set(entries_by_path):
        raise ValueError("managed state trusted paths must match entries")


def _validate_references(source: dict[str, Any], handoff_summary: dict[str, Any]) -> None:
    _validate_policy(source)
    if handoff_summary["review_findings"]:
        raise ValueError("parameter-state intake requires handoff without review findings")
    request, write, _step, base_context = _selected_handoff(source, handoff_summary)
    _validate_review(source["intake_review"], request)
    _validate_managed_state(
        source["managed_parameter_state"],
        source["intake_review"],
        request,
        write,
        base_context,
    )
    _validate_side_effects(source)


def _managed_state_summary(managed_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_id": managed_state["state_id"],
        "state_kind": managed_state["state_kind"],
        "state_label": managed_state["state_label"],
        "lineage": copy.deepcopy(managed_state["lineage"]),
        "source_handoff_id": managed_state["source_handoff_id"],
        "base_state_id": managed_state["base_state_id"],
        "created_by_review_id": managed_state["created_by_review_id"],
        "readiness": managed_state["readiness"],
        "trust_status": managed_state["trust_status"],
        "trusted_entry_paths": list(managed_state["trusted_entry_paths"]),
        "entries": copy.deepcopy(managed_state["entries"]),
    }


def _changed_entries(
    managed_state: dict[str, Any],
    request: dict[str, Any],
    base_context: dict[str, Any],
) -> list[dict[str, Any]]:
    base_entries = _base_entries_by_path(base_context)
    entries_by_path = _records_by_key(managed_state["entries"], "path")
    output = []
    for diff in request["reviewable_diff_request"]["diff_entries"]:
        output.append(
            {
                "path": diff["path"],
                "old_value": copy.deepcopy(base_entries[diff["path"]]["value"]),
                "new_value": copy.deepcopy(entries_by_path[diff["path"]]["value"]),
                "unit": diff["unit"],
                "source_handoff_id": request["handoff_id"],
                "source_handoff_review_id": request["reviewable_diff_request"]["review_id"],
                "change_source": "accepted_calibration_handoff",
            }
        )
    return output


def _provenance_summary(
    request: dict[str, Any],
    write: dict[str, Any],
    step: dict[str, Any],
    base_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_kind": "calibration_accepted_write_handoff",
        "source_handoff_id": request["handoff_id"],
        "source_write_id": write["write_id"],
        "source_step_record_id": step["step_record_id"],
        "source_step_intent_id": step["step_intent_id"],
        "base_context_id": base_context["context_id"],
        "base_state_id": base_context["state_id"],
        "measurement_record_refs": [
            link["measurement_record_id"] for link in step["observation_link_refs"]
        ],
        "observation_links": copy.deepcopy(step["observation_link_refs"]),
        "source_observation": "validated_calibration_handoff_summary",
    }


def _review_findings(handoff_summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "severity": "review",
            "source": "calibration_accepted_write_handoff",
            "finding": finding["finding"],
            "handoff_id": finding["handoff_id"],
            "does_not_claim": "parameter_state_commit_or_storage_write",
        }
        for finding in handoff_summary["review_findings"]
    ]


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "parameter_state_route_accepts_calibration_handoff",
            "severity": "info",
            "basis": "A ready accepted calibration handoff can become a managed parameter-state summary after explicit parameter-state review.",
            "does_not_claim": "calibration_owned_commit",
        },
        {
            "code": "managed_state_summary_not_written",
            "severity": "review",
            "basis": "The intake summary projects a new managed state without writing storage or durable history.",
            "does_not_claim": "storage_mutation",
        },
        {
            "code": "calibration_evidence_preserved_as_provenance",
            "severity": "info",
            "basis": "Step, observation, write, and handoff identities are preserved as provenance.",
            "does_not_claim": "measurement_payload_read_or_fit_execution",
        },
        {
            "code": "hardware_write_back_not_performed",
            "severity": "review",
            "basis": "Accepting parameter-state intake does not apply values to instruments.",
            "does_not_claim": "instrument_command_or_current_hardware_state",
        },
    ]


def build_calibration_parameter_state_intake_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a parameter-state intake summary from an accepted calibration handoff."""
    handoff_summary = build_calibration_accepted_write_handoff_summary(
        source["calibration_handoff_input"]
    )
    _validate_references(source, handoff_summary)
    request, write, step, base_context = _selected_handoff(source, handoff_summary)
    review = source["intake_review"]
    return {
        "policy": copy.deepcopy(source["calibration_parameter_state_intake_policy"]),
        "source_handoff": {
            "handoff_id": request["handoff_id"],
            "write_id": write["write_id"],
            "target_route": request["target_route"],
            "request_state": request["request_state"],
            "base_state_id": request["draft_request"]["base_state_id"],
            "lineage_id": request["draft_request"]["lineage_id"],
            "diff_paths": [
                entry["path"] for entry in request["reviewable_diff_request"]["diff_entries"]
            ],
            "apply_state": write["apply_state"],
            "handoff_posture": request["route_input_posture"],
        },
        "intake_review": {
            "review_id": review["review_id"],
            "review_status": review["review_status"],
            "accepted_at": review["accepted_at"],
            "accepted_by_role": review["accepted_by_role"],
            "source_handoff_review_id": review["source_handoff_review_id"],
            "accepted_diff_paths": list(review["accepted_diff_paths"]),
        },
        "managed_parameter_state": _managed_state_summary(source["managed_parameter_state"]),
        "changed_entries": _changed_entries(
            source["managed_parameter_state"], request, base_context
        ),
        "provenance": _provenance_summary(request, write, step, base_context),
        "review_findings": _review_findings(handoff_summary),
        "side_effects": copy.deepcopy(source["side_effect_claims"]),
        "attention": _attention(),
    }
