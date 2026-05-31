"""Prepared-run consumption of explicit stored parameter-state read views.

This module composes declared prepared-run context summary facts with one
explicit parameter-state storage read-view summary. It deliberately does not
read storage, discover catalogs, write parameters, control hardware, mutate
setup bindings, sync environments, import or execute code, open GUIs, or define
shared domain models.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "composition_authority": "prepared_run_parameter_state_reference",
    "prepared_context_source": "declared_prepared_run_context_summary",
    "parameter_state_source": "explicit_storage_read_view_summary",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "composition_review_facts_only",
    "gui_workflow": "not_defined",
    "shared_parameter_schema": "not_defined",
    "shared_run_context_schema": "not_defined",
}


def _records_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    output = {}
    for record in records:
        record_key = record[key]
        if record_key in output:
            raise ValueError(f"duplicate {key}: {record_key}")
        output[record_key] = record
    return output


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["consumption_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run parameter-state consumption policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"prepared-run parameter-state consumption policy {key} must be {expected}"
            )


def _prepared_contexts_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["prepared_run_context_summary"]["prepared_run_contexts"],
        "prepared_run_context_id",
    )


def _selected_parameter_context(
    source: dict[str, Any],
    prepared_context_id: str,
    role: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in source["prepared_run_context_summary"]["selected_context_refs"]
        if item["prepared_run_context_id"] == prepared_context_id
        and item["family"] == "parameter_state"
        and item["role"] == role
    ]
    if len(matches) > 1:
        raise ValueError("prepared run context contains duplicate parameter_state role")
    return matches[0] if matches else None


def _validate_prepared_context_summary(source: dict[str, Any]) -> None:
    summary = source["prepared_run_context_summary"]
    if summary["prepared_run_context_policy"]["parameter_write_back"] != "not_performed":
        raise ValueError("prepared context summary must not perform parameter_write_back")
    if summary["prepared_run_context_policy"]["hardware_control"] != "not_performed":
        raise ValueError("prepared context summary must not perform hardware_control")
    if summary["prepared_run_context_policy"]["code_import_execution"] != "not_performed":
        raise ValueError("prepared context summary must not import or execute code")
    _prepared_contexts_by_id(source)


def _validate_read_view_summary(source: dict[str, Any]) -> None:
    summary = source["parameter_state_read_view_summary"]
    if summary["read_view_policy"]["storage_mutation"] != "not_performed":
        raise ValueError("parameter state read view must not mutate storage")
    if summary["read_view_policy"]["catalog_discovery"] != "not_performed":
        raise ValueError("parameter state read view must not perform catalog_discovery")
    if summary["read_view_policy"]["hardware_write_back"] != "not_performed":
        raise ValueError("parameter state read view must not perform hardware_write_back")

    state = summary.get("parameter_state")
    if state is None:
        return
    trusted_paths = state["trusted_entry_paths"]
    if len(trusted_paths) != len(set(trusted_paths)):
        raise ValueError("parameter state read view contains duplicate trusted entry path")
    entry_paths = [entry["path"] for entry in summary["trusted_entries"]]
    if len(entry_paths) != len(set(entry_paths)):
        raise ValueError("parameter state read view contains duplicate trusted entry")
    if set(entry_paths) != set(trusted_paths):
        raise ValueError("parameter state read view trusted entries must match trusted paths")
    if state["entry_count"] != len(summary["trusted_entries"]):
        raise ValueError("parameter state read view entry_count must match trusted entries")
    for entry in summary["trusted_entries"]:
        if entry["trust"] != "review_accepted":
            raise ValueError("parameter state consumed entries must be review_accepted")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["consumption_request"]
    prepared_contexts = _prepared_contexts_by_id(source)
    prepared_context_id = request["prepared_run_context_id"]
    if prepared_context_id not in prepared_contexts:
        raise ValueError("consumption request references missing prepared run context")
    if request["parameter_context_role"] != "calibrated_values":
        raise ValueError("consumption request parameter_context_role must be calibrated_values")

    parameter_context = _selected_parameter_context(
        source,
        prepared_context_id,
        request["parameter_context_role"],
    )
    if parameter_context is None:
        return
    if parameter_context["include_state"] != "selected":
        return
    if parameter_context.get("context_id") != request["parameter_context_id"]:
        raise ValueError("consumption request parameter_context_id must match selected context")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_prepared_context_summary(source)
    _validate_read_view_summary(source)
    _validate_request(source)


def _finding(code: str, basis: Any, does_not_claim: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "review",
        "basis": copy.deepcopy(basis),
        "does_not_claim": does_not_claim,
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    request = source["consumption_request"]
    read_view = source["parameter_state_read_view_summary"]
    parameter_context = _selected_parameter_context(
        source,
        request["prepared_run_context_id"],
        request["parameter_context_role"],
    )
    findings = []

    if parameter_context is None:
        findings.append(
            _finding(
                "prepared_parameter_context_missing",
                "Prepared run context does not select the requested parameter_state role.",
                "automatic_run_blocking_or_context_repair",
            )
        )
    elif parameter_context["include_state"] != "selected":
        findings.append(
            _finding(
                "prepared_parameter_context_unavailable",
                parameter_context.get("missing_reason"),
                "automatic_run_blocking_or_context_repair",
            )
        )

    state = read_view.get("parameter_state")
    if state is None:
        findings.append(
            _finding(
                "parameter_state_read_view_unavailable",
                "Stored parameter-state read view did not expose a parameter state.",
                "fresh_storage_read_or_catalog_discovery",
            )
        )
    else:
        if state["state_id"] != request["expected_state_id"]:
            findings.append(
                _finding(
                    "parameter_state_id_mismatch",
                    {
                        "expected_state_id": request["expected_state_id"],
                        "observed_state_id": state["state_id"],
                    },
                    "state_selection_repair_or_hardware_safety_decision",
                )
            )
        if (
            parameter_context is not None
            and parameter_context.get("context_id") != state["state_id"]
        ):
            findings.append(
                _finding(
                    "prepared_context_state_id_mismatch",
                    {
                        "prepared_context_id": parameter_context.get("context_id"),
                        "read_view_state_id": state["state_id"],
                    },
                    "state_selection_repair_or_hardware_safety_decision",
                )
            )

    if read_view["classification"] != "stored_parameter_state_read_view_ready":
        findings.append(
            _finding(
                "parameter_state_read_view_not_ready",
                read_view["classification"],
                "fresh_storage_read_or_automatic_repair",
            )
        )
    for finding in read_view["review_findings"]:
        findings.append(
            _finding(
                "parameter_state_read_view_finding",
                finding,
                "automatic_run_blocking_or_storage_repair",
            )
        )
    return findings


def _classification(findings: list[dict[str, Any]]) -> str:
    codes = {finding["code"] for finding in findings}
    if {
        "prepared_parameter_context_missing",
        "prepared_parameter_context_unavailable",
        "parameter_state_read_view_unavailable",
    } & codes:
        return "prepared_run_parameter_state_unavailable_for_review"
    if findings:
        return "prepared_run_parameter_state_needs_review"
    return "prepared_run_parameter_state_ready"


def _prepared_context_output(source: dict[str, Any]) -> dict[str, Any]:
    request = source["consumption_request"]
    prepared_context = _prepared_contexts_by_id(source)[request["prepared_run_context_id"]]
    selected = _selected_parameter_context(
        source,
        request["prepared_run_context_id"],
        request["parameter_context_role"],
    )
    return {
        "prepared_run_context_id": prepared_context["prepared_run_context_id"],
        "label": prepared_context["label"],
        "manual_run_target": copy.deepcopy(prepared_context["manual_run_target"]),
        "parameter_context_ref": copy.deepcopy(selected),
    }


def _parameter_state_output(source: dict[str, Any]) -> dict[str, Any] | None:
    state = source["parameter_state_read_view_summary"].get("parameter_state")
    if state is None:
        return None
    return {
        "state_id": state["state_id"],
        "state_kind": state["state_kind"],
        "state_label": state["state_label"],
        "lineage": copy.deepcopy(state["lineage"]),
        "readiness": state["readiness"],
        "trust_status": state["trust_status"],
        "trusted_entry_count": len(state["trusted_entry_paths"]),
        "read_view_classification": source["parameter_state_read_view_summary"]["classification"],
    }


def _storage_read_facts(source: dict[str, Any]) -> dict[str, Any]:
    read_view = source["parameter_state_read_view_summary"]
    observed_by_kind = {item["kind"]: item for item in read_view["observed_files"]}
    manifest = observed_by_kind["parameter_state_manifest"]
    receipt = observed_by_kind["write_receipt"]
    return {
        "manifest": {
            "path": manifest["path"],
            "status": manifest["status"],
            "observed_digest": manifest["observed_digest"],
            "observed_size_bytes": manifest["observed_size_bytes"],
        },
        "receipt": {
            "path": receipt["path"],
            "status": receipt["status"],
            "observed_digest": receipt["observed_digest"],
            "observed_size_bytes": receipt["observed_size_bytes"],
            "receipt_request_id": read_view["receipt"]["request_id"]
            if read_view.get("receipt") is not None
            else None,
        },
    }


def _provenance_summary(source: dict[str, Any]) -> dict[str, Any] | None:
    provenance = source["parameter_state_read_view_summary"].get("provenance")
    if provenance is None:
        return None
    return {
        "source_observation": provenance["source_observation"],
        "legacy_source_count": len(provenance["legacy_sources"]),
        "adapter_id": provenance["adapter_id"],
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "prepared_context_consumes_explicit_read_view",
            "severity": "info",
            "basis": "Prepared-run parameter context is checked against one explicit stored read-view summary.",
            "does_not_claim": "catalog_discovery_or_storage_lookup",
        },
        {
            "code": "trusted_entries_projected_for_review",
            "severity": "review",
            "basis": "Trusted parameter entries are visible as run-preparation facts.",
            "does_not_claim": "parameter_write_back_or_hardware_state",
        },
        {
            "code": "storage_read_not_repeated",
            "severity": "info",
            "basis": "The composition consumes prior read-view facts and does not open storage.",
            "does_not_claim": "fresh_integrity_observation",
        },
        {
            "code": "execution_not_granted",
            "severity": "review",
            "basis": "Composed run-preparation facts do not import code, sync an environment, or execute a run.",
            "does_not_claim": "run_start_or_runnable_readiness",
        },
    ]


def build_prepared_run_parameter_state_consumption_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a run-preparation parameter-state consumption summary."""
    _validate_references(source)
    findings = _review_findings(source)
    return {
        "consumption_policy": copy.deepcopy(source["consumption_policy"]),
        "consumption_request": copy.deepcopy(source["consumption_request"]),
        "classification": _classification(findings),
        "prepared_run_context": _prepared_context_output(source),
        "parameter_state": _parameter_state_output(source),
        "trusted_entries": copy.deepcopy(
            source["parameter_state_read_view_summary"]["trusted_entries"]
        ),
        "provenance": _provenance_summary(source),
        "storage_read_facts": _storage_read_facts(source),
        "review_findings": findings,
        "attention": _attention(),
    }
