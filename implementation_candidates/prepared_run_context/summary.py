"""Structured summary builder for a prepared run context.

This module is an experimental production-shaped boundary. It is deliberately
side-effect free: it does not inspect workspaces, control hardware, write
parameters, mutate setup bindings, sync environments, import code, execute
code, restore context, or define a universal context schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "run_context_authority": "preparation_summary_only",
    "context_source": "declared_fixture_records",
    "workspace_observation_source": "declared_editable_folder_observation_summary",
    "shared_context_schema": "not_defined",
    "hardware_control": "not_performed",
    "parameter_write_back": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "selection_and_workspace_observation_only",
}

_SUPPORTED_CONTEXT_FAMILIES = {
    "measurement_intent",
    "parameter_state",
    "setup_binding",
    "station_registry",
    "managed_code_version",
    "editable_workspace_observation",
    "declared_environment",
}

_ALLOWED_INCLUDE_STATES = {
    "selected",
    "unavailable",
    "optional_not_selected",
}

_OBSERVATION_FINDINGS_NEEDING_REVIEW = {
    "changed_observed",
    "missing_expected",
    "target_is_symlink",
    "not_a_file",
    "extra_observed",
    "extra_symlink_not_read",
    "extra_unstable_not_read",
    "skipped_redacted",
    "unavailable_reference",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _context_records_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["context_records"], "context_id")


def _prepared_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["prepared_run_contexts"], "prepared_run_context_id")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["prepared_run_context_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared run context policy must match the expected policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared run context policy {key} must be {expected}")


def _validate_context_records(source: dict[str, Any]) -> None:
    _context_records_by_id(source)
    for context in source["context_records"]:
        family = context["family"]
        if family not in _SUPPORTED_CONTEXT_FAMILIES:
            raise ValueError(f"unsupported context family: {family}")
        if context["payload_handling"] != "family_owned_summary_only":
            raise ValueError("context payload handling must remain family-owned")


def _validate_selected_context(
    prepared_context_id: str,
    selected_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    family = selected_context["family"]
    include_state = selected_context["include_state"]
    if family not in _SUPPORTED_CONTEXT_FAMILIES:
        raise ValueError(f"unsupported selected context family: {family}")
    if include_state not in _ALLOWED_INCLUDE_STATES:
        raise ValueError(f"unsupported include_state: {include_state}")

    context_id = selected_context.get("context_id")
    if include_state == "selected":
        if selected_context.get("missing_reason") is not None:
            raise ValueError(
                f"prepared run context {prepared_context_id} selected context must not carry missing_reason"
            )
        if context_id not in context_records:
            raise ValueError(
                f"prepared run context {prepared_context_id} references missing selected context"
            )
        if context_records[context_id]["family"] != family:
            raise ValueError(
                f"prepared run context {prepared_context_id} references context from wrong family"
            )
        return

    if context_id is not None:
        raise ValueError(
            f"prepared run context {prepared_context_id} non-selected context must not carry context_id"
        )

    if include_state == "optional_not_selected" and selected_context["required"]:
        raise ValueError(
            f"prepared run context {prepared_context_id} optional_not_selected context must not be required"
        )

    if selected_context["required"] and not selected_context.get("missing_reason"):
        raise ValueError(
            f"prepared run context {prepared_context_id} required unavailable context needs a reason"
        )


def _selected_context_for_family(
    prepared_context: dict[str, Any],
    family: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in prepared_context["selected_contexts"]
        if item["family"] == family and item["include_state"] == "selected"
    ]
    if len(matches) > 1:
        raise ValueError(f"prepared run context contains multiple selected {family} contexts")
    return matches[0] if matches else None


def _validate_workspace_observation_alignment(
    prepared_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    managed_context = _selected_context_for_family(prepared_context, "managed_code_version")
    observation_context = _selected_context_for_family(
        prepared_context, "editable_workspace_observation"
    )
    if managed_context is None and observation_context is None:
        raise ValueError(
            "prepared run context requires selected managed code version and editable workspace observation"
        )
    if managed_context is None:
        raise ValueError("prepared run context requires selected managed code version")
    if observation_context is None:
        raise ValueError("prepared run context requires selected editable workspace observation")

    managed_id = managed_context["context_id"]
    observation = context_records[observation_context["context_id"]]
    observed_version_id = observation["declared_summary"].get("selected_version_id")
    if observed_version_id != managed_id:
        raise ValueError(
            "editable workspace observation must reference the selected managed code version"
        )


def _validate_measurement_intent_alignment(
    prepared_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> None:
    measurement_intent_context = _selected_context_for_family(
        prepared_context, "measurement_intent"
    )
    if measurement_intent_context is None:
        raise ValueError("prepared run context requires selected measurement intent")

    intent = context_records[measurement_intent_context["context_id"]]["declared_summary"]
    target = prepared_context["manual_run_target"]
    compared_fields = ("experiment_label", "logical_targets", "entrypoint_hint")
    for field in compared_fields:
        if target.get(field) != intent.get(field):
            raise ValueError(
                f"manual run target does not match selected measurement intent field: {field}"
            )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_context_records(source)
    context_records = _context_records_by_id(source)
    _prepared_contexts_by_id(source)

    for prepared_context in source["prepared_run_contexts"]:
        seen_roles = set()
        for selected_context in prepared_context["selected_contexts"]:
            role_key = (selected_context["family"], selected_context["role"])
            if role_key in seen_roles:
                raise ValueError("prepared run context contains duplicate family role")
            seen_roles.add(role_key)
            _validate_selected_context(
                prepared_context["prepared_run_context_id"],
                selected_context,
                context_records,
            )
        _validate_workspace_observation_alignment(prepared_context, context_records)
        _validate_measurement_intent_alignment(prepared_context, context_records)


def _context_record_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "family": context["family"],
        "label": context["label"],
        "record_status": context["record_status"],
        "authority": context["authority"],
        "payload_handling": context["payload_handling"],
        "declared_summary": copy.deepcopy(context["declared_summary"]),
    }


def _selected_context_summary(
    prepared_context_id: str,
    selected_context: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {
        "prepared_run_context_id": prepared_context_id,
        "family": selected_context["family"],
        "role": selected_context["role"],
        "required": selected_context["required"],
        "include_state": selected_context["include_state"],
        "context_id": selected_context.get("context_id"),
    }
    context = context_records.get(selected_context.get("context_id"))
    if context is not None:
        output["context_label"] = context["label"]
        output["record_status"] = context["record_status"]
        output["authority"] = context["authority"]
    else:
        output["missing_reason"] = selected_context.get("missing_reason")
    return output


def _missing_context_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for prepared_context in source["prepared_run_contexts"]:
        for selected_context in prepared_context["selected_contexts"]:
            if selected_context["include_state"] == "selected":
                continue
            if not selected_context["required"]:
                continue
            findings.append(
                {
                    "prepared_run_context_id": prepared_context["prepared_run_context_id"],
                    "family": selected_context["family"],
                    "role": selected_context["role"],
                    "severity": "review",
                    "finding": "required_context_unavailable",
                    "basis": selected_context["missing_reason"],
                    "does_not_claim": "run_is_blocked_or_unsafe",
                }
            )
    return findings


def _workspace_context_findings(
    source: dict[str, Any],
    context_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for prepared_context in source["prepared_run_contexts"]:
        observation_context = _selected_context_for_family(
            prepared_context, "editable_workspace_observation"
        )
        if observation_context is None:
            continue

        observation = context_records[observation_context["context_id"]]
        summary = observation["declared_summary"]
        finding_counts = summary["finding_counts"]
        review_findings = {
            finding: count
            for finding, count in finding_counts.items()
            if finding in _OBSERVATION_FINDINGS_NEEDING_REVIEW and count > 0
        }
        if review_findings:
            findings.append(
                {
                    "prepared_run_context_id": prepared_context["prepared_run_context_id"],
                    "context_id": observation["context_id"],
                    "severity": "review",
                    "finding": "workspace_observation_has_review_findings",
                    "basis": copy.deepcopy(review_findings),
                    "does_not_claim": "run_is_blocked_or_workspace_is_unusable",
                }
            )
    return findings


def _prepared_context_summary(prepared_context: dict[str, Any]) -> dict[str, Any]:
    required_count = sum(1 for item in prepared_context["selected_contexts"] if item["required"])
    selected_count = sum(
        1 for item in prepared_context["selected_contexts"] if item["include_state"] == "selected"
    )
    unavailable_required_count = sum(
        1
        for item in prepared_context["selected_contexts"]
        if item["required"] and item["include_state"] != "selected"
    )
    return {
        "prepared_run_context_id": prepared_context["prepared_run_context_id"],
        "label": prepared_context["label"],
        "manual_run_target": copy.deepcopy(prepared_context["manual_run_target"]),
        "context_ref_count": len(prepared_context["selected_contexts"]),
        "required_context_count": required_count,
        "selected_context_count": selected_count,
        "unavailable_required_context_count": unavailable_required_count,
        "preparation_claim": prepared_context["preparation_claim"],
    }


def _attention(source: dict[str, Any]) -> list[dict[str, Any]]:
    policy = source["prepared_run_context_policy"]
    attention = []

    if any(
        selected_context["include_state"] != "selected" and selected_context["required"]
        for prepared_context in source["prepared_run_contexts"]
        for selected_context in prepared_context["selected_contexts"]
    ):
        attention.append(
            {
                "code": "required_context_unavailable",
                "severity": "review",
                "basis": "At least one required prepared-run context record is unavailable.",
                "does_not_claim": "automatic_run_blocking",
            }
        )

    if policy["workspace_observation_source"] == "declared_editable_folder_observation_summary":
        attention.append(
            {
                "code": "workspace_observation_reused_as_declared_context",
                "severity": "info",
                "basis": "Prepared run context uses declared editable-folder observation results.",
                "does_not_claim": "fresh_filesystem_observation",
            }
        )

    if policy["shared_context_schema"] == "not_defined":
        attention.append(
            {
                "code": "shared_context_schema_not_defined",
                "severity": "info",
                "basis": "The prepared run context groups family-owned context records by reference.",
                "does_not_claim": "universal_context_payload_schema",
            }
        )

    if policy["hardware_control"] == "not_performed":
        attention.append(
            {
                "code": "hardware_control_not_granted",
                "severity": "review",
                "basis": "Prepared run context selection does not configure instruments.",
                "does_not_claim": "hardware_state_applied",
            }
        )

    if policy["environment_sync"] == "not_performed":
        attention.append(
            {
                "code": "environment_sync_not_performed",
                "severity": "review",
                "basis": "Declared environment context is represented by run-context reference state, not a synced runtime.",
                "does_not_claim": "runnable_environment",
            }
        )

    if policy["code_import_execution"] == "not_performed":
        attention.append(
            {
                "code": "code_execution_not_granted",
                "severity": "review",
                "basis": "Selected code and workspace context are not imported, loaded, or executed.",
                "does_not_claim": "execution_permission",
            }
        )

    return attention


def build_prepared_run_context_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a prepared run context summary from explicit fixture input."""
    _validate_references(source)
    context_records = _context_records_by_id(source)
    return {
        "prepared_run_context_policy": copy.deepcopy(source["prepared_run_context_policy"]),
        "context_records": [
            _context_record_summary(context) for context in source["context_records"]
        ],
        "prepared_run_contexts": [
            _prepared_context_summary(prepared_context)
            for prepared_context in source["prepared_run_contexts"]
        ],
        "selected_context_refs": [
            _selected_context_summary(
                prepared_context["prepared_run_context_id"],
                selected_context,
                context_records,
            )
            for prepared_context in source["prepared_run_contexts"]
            for selected_context in prepared_context["selected_contexts"]
        ],
        "missing_context_findings": _missing_context_findings(source),
        "workspace_context_findings": _workspace_context_findings(source, context_records),
        "attention": _attention(source),
    }
