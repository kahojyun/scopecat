"""Prepared-run scope alignment review projection.

This module compares explicit prepared-run parameter-state consumption facts
with explicit setup-binding facts. It deliberately does not write parameters,
control hardware, start runs, read storage, discover catalogs, mutate setup
bindings, sync environments, import or execute code, open GUIs, or define a
shared parameter/setup/measurement schema.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "alignment_authority": "declared_prepared_run_scope_review",
    "parameter_context_source": "prepared_run_parameter_state_consumption_summary",
    "setup_binding_source": "declared_setup_binding_summary",
    "measurement_intent_source": "prepared_run_manual_target",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "automatic_run_start": "not_performed",
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
    "readiness_claim": "scope_review_facts_only",
    "gui_workflow": "not_defined",
    "shared_scope_schema": "not_defined",
}

_CONSUMPTION_POLICY_EXPECTED = {
    "fresh_storage_read": "not_performed",
    "catalog_discovery": "not_performed",
    "storage_mutation": "not_performed",
    "parameter_write_back": "not_performed",
    "hardware_control": "not_performed",
    "setup_mutation": "not_performed",
    "environment_sync": "not_performed",
    "code_import_execution": "not_performed",
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
    policy = source["alignment_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("prepared-run scope alignment policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"prepared-run scope alignment policy {key} must be {expected}")


def _setup_bindings_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(source["setup_binding_summary"]["setup_bindings"], "snapshot_id")


def _logical_bindings_for_snapshot(
    source: dict[str, Any],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    return [
        binding
        for binding in source["setup_binding_summary"]["logical_bindings"]
        if binding["snapshot_id"] == snapshot_id
    ]


def _measurement_refs_by_id(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _records_by_key(
        source["setup_binding_summary"]["measurement_references"], "measurement_id"
    )


def _input_ref(measurement: dict[str, Any], name: str) -> dict[str, Any] | None:
    matches = [item for item in measurement["inputs"] if item["name"] == name]
    if len(matches) > 1:
        raise ValueError(f"measurement contains duplicate input name: {name}")
    return matches[0] if matches else None


def _validate_consumption_summary(source: dict[str, Any]) -> None:
    summary = source["parameter_state_consumption_summary"]
    policy = summary["consumption_policy"]
    for key, expected in _CONSUMPTION_POLICY_EXPECTED.items():
        if policy[key] != expected:
            raise ValueError(f"parameter-state consumption summary {key} must be {expected}")
    if summary["parameter_state"] is None:
        raise ValueError("scope alignment requires parameter_state consumption facts")
    if summary["classification"] not in {
        "prepared_run_parameter_state_ready",
        "prepared_run_parameter_state_needs_review",
        "prepared_run_parameter_state_unavailable_for_review",
    }:
        raise ValueError("unsupported parameter-state consumption classification")


def _validate_setup_binding_summary(source: dict[str, Any]) -> None:
    _setup_bindings_by_id(source)
    logical_keys = set()
    for binding in source["setup_binding_summary"]["logical_bindings"]:
        key = (binding["snapshot_id"], binding["logical_entity"], binding["role"])
        if key in logical_keys:
            raise ValueError("setup binding summary contains duplicate logical binding")
        logical_keys.add(key)
    _measurement_refs_by_id(source)
    for measurement in source["setup_binding_summary"]["measurement_references"]:
        if measurement["hardware_state_claim"] != "not_recorded":
            raise ValueError("scope alignment requires hardware_state_claim not_recorded")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["alignment_request"]
    consumption = source["parameter_state_consumption_summary"]
    prepared_context = consumption["prepared_run_context"]
    if request["prepared_run_context_id"] != prepared_context["prepared_run_context_id"]:
        raise ValueError("alignment request prepared_run_context_id must match consumption")
    if request["measurement_id"] != prepared_context["manual_run_target"]["measurement_id"]:
        raise ValueError("alignment request measurement_id must match prepared target")
    setup_bindings = _setup_bindings_by_id(source)
    if request["setup_binding_id"] not in setup_bindings:
        raise ValueError("alignment request references missing setup binding")
    measurements = _measurement_refs_by_id(source)
    if request["measurement_id"] not in measurements:
        raise ValueError("alignment request references missing measurement")
    setup_input = _input_ref(measurements[request["measurement_id"]], "setup_binding")
    if setup_input is None or setup_input["snapshot_id"] != request["setup_binding_id"]:
        raise ValueError("measurement setup_binding input must match alignment request")


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_consumption_summary(source)
    _validate_setup_binding_summary(source)
    _validate_request(source)


def _finding(code: str, basis: Any, does_not_claim: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "review",
        "basis": copy.deepcopy(basis),
        "does_not_claim": does_not_claim,
    }


def _lineage_tokens(source: dict[str, Any]) -> set[str]:
    return set(
        source["parameter_state_consumption_summary"]["parameter_state"]["lineage"]["target_scope"]
    )


def _measurement_targets(source: dict[str, Any]) -> list[str]:
    return list(
        source["parameter_state_consumption_summary"]["prepared_run_context"]["manual_run_target"][
            "logical_targets"
        ]
    )


def _setup_sample(source: dict[str, Any]) -> dict[str, str]:
    setup = _setup_bindings_by_id(source)[source["alignment_request"]["setup_binding_id"]]
    return {
        "sample_id": setup["sample_id"],
        "cooldown_id": setup["cooldown_id"],
    }


def _bound_logical_entities(source: dict[str, Any]) -> set[str]:
    bindings = _logical_bindings_for_snapshot(
        source, source["alignment_request"]["setup_binding_id"]
    )
    return {binding["logical_entity"] for binding in bindings}


def _alignment_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    request = source["alignment_request"]
    consumption = source["parameter_state_consumption_summary"]
    lineage_tokens = _lineage_tokens(source)
    measurement_targets = set(_measurement_targets(source))
    bound_entities = _bound_logical_entities(source)
    setup_sample = _setup_sample(source)

    expected_sample_id = request["expected_sample_id"]
    if setup_sample["sample_id"] != expected_sample_id:
        findings.append(
            _finding(
                "setup_sample_mismatch",
                {
                    "expected_sample_id": expected_sample_id,
                    "setup_sample_id": setup_sample["sample_id"],
                },
                "automatic_parameter_invalidation_or_hardware_safety",
            )
        )
    if expected_sample_id not in lineage_tokens:
        findings.append(
            _finding(
                "parameter_lineage_sample_not_in_scope",
                {
                    "expected_sample_id": expected_sample_id,
                    "lineage_target_scope": sorted(lineage_tokens),
                },
                "automatic_parameter_invalidation_or_lineage_repair",
            )
        )

    missing_binding_targets = sorted(measurement_targets - bound_entities)
    if missing_binding_targets:
        findings.append(
            _finding(
                "measurement_targets_missing_setup_binding",
                {
                    "missing_targets": missing_binding_targets,
                    "setup_binding_id": request["setup_binding_id"],
                },
                "hardware_mapping_repair_or_run_blocking",
            )
        )

    lineage_covered_targets = measurement_targets & lineage_tokens
    lineage_missing_targets = sorted(measurement_targets - lineage_tokens)
    if not lineage_covered_targets:
        findings.append(
            _finding(
                "parameter_lineage_covers_no_measurement_targets",
                {
                    "measurement_targets": sorted(measurement_targets),
                    "lineage_target_scope": sorted(lineage_tokens),
                },
                "automatic_parameter_invalidation_or_run_blocking",
            )
        )
    elif lineage_missing_targets:
        findings.append(
            _finding(
                "parameter_lineage_partial_target_coverage",
                {
                    "covered_targets": sorted(lineage_covered_targets),
                    "missing_targets": lineage_missing_targets,
                },
                "automatic_parameter_invalidation_or_run_blocking",
            )
        )

    if consumption["classification"] != "prepared_run_parameter_state_ready":
        findings.append(
            _finding(
                "parameter_consumption_not_ready",
                consumption["classification"],
                "automatic_run_blocking_or_parameter_write_back",
            )
        )
    return findings


def _classification(findings: list[dict[str, Any]]) -> str:
    blocking_codes = {
        "setup_sample_mismatch",
        "parameter_lineage_sample_not_in_scope",
        "measurement_targets_missing_setup_binding",
        "parameter_lineage_covers_no_measurement_targets",
    }
    codes = {finding["code"] for finding in findings}
    if codes & blocking_codes:
        return "scope_alignment_blocked_for_review"
    if findings:
        return "scope_alignment_needs_review"
    return "scope_alignment_ready"


def _scope_summary(source: dict[str, Any]) -> dict[str, Any]:
    bindings = _logical_bindings_for_snapshot(
        source, source["alignment_request"]["setup_binding_id"]
    )
    return {
        "prepared_run_context_id": source["alignment_request"]["prepared_run_context_id"],
        "measurement_id": source["alignment_request"]["measurement_id"],
        "measurement_logical_targets": _measurement_targets(source),
        "parameter_state_id": source["parameter_state_consumption_summary"]["parameter_state"][
            "state_id"
        ],
        "parameter_lineage_target_scope": copy.deepcopy(
            source["parameter_state_consumption_summary"]["parameter_state"]["lineage"][
                "target_scope"
            ]
        ),
        "setup_binding_id": source["alignment_request"]["setup_binding_id"],
        "setup_sample": _setup_sample(source),
        "bound_logical_entities": sorted(_bound_logical_entities(source)),
        "logical_binding_count": len(bindings),
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "scope_alignment_review_only",
            "severity": "info",
            "basis": "Alignment compares declared context summaries without owning their payload schemas.",
            "does_not_claim": "shared_parameter_setup_measurement_schema",
        },
        {
            "code": "hardware_control_not_performed",
            "severity": "review",
            "basis": "Setup-binding alignment does not inspect or configure hardware.",
            "does_not_claim": "current_instrument_state",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "Alignment does not apply, repair, or invalidate parameter values.",
            "does_not_claim": "parameter_application_or_invalidation",
        },
        {
            "code": "run_start_not_performed",
            "severity": "review",
            "basis": "Alignment findings are review facts, not execution permission.",
            "does_not_claim": "run_can_start",
        },
    ]


def build_prepared_run_scope_alignment_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a prepared-run scope alignment summary from explicit summaries."""
    _validate_references(source)
    findings = _alignment_findings(source)
    return {
        "alignment_policy": copy.deepcopy(source["alignment_policy"]),
        "alignment_request": copy.deepcopy(source["alignment_request"]),
        "classification": _classification(findings),
        "scope_summary": _scope_summary(source),
        "review_findings": findings,
        "attention": _attention(),
    }
