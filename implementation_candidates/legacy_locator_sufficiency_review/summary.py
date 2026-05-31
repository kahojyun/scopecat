"""Review-only sufficiency summary for legacy source locators.

This module consumes a legacy-run sidecar manifest summary and classifies
declared locators by review sufficiency. It does not parse locator values,
perform backend lookup, observe files, import legacy data, repair references,
mutate storage, or define GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "review_authority": "explicit_legacy_locator_sufficiency_review",
    "input_authority": "legacy_run_sidecar_manifest_summary",
    "locator_semantics": "declared_user_navigation_only",
    "backend_lookup": "not_performed",
    "path_parsing": "not_performed",
    "file_observation": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "reference_repair": "not_performed",
    "gui_workflow": "not_defined",
}

_SIDE_CAR_POLICY_EXPECTATIONS = {
    "sidecar_authority": "declared_legacy_runtime_boundary",
    "primary_data_observation": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
}

_NAVIGATION_LOCATOR_KINDS = {
    "legacy_record_id",
    "legacy_path",
    "legacy_uri",
    "session_record_pair",
    "other",
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
    policy = source["locator_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy locator review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy locator review policy {key} must be {expected}")


def _validate_sidecar_summary(summary: dict[str, Any]) -> None:
    sidecar_policy = summary["sidecar_policy"]
    for key, expected in _SIDE_CAR_POLICY_EXPECTATIONS.items():
        if sidecar_policy[key] != expected:
            raise ValueError(f"sidecar summary policy {key} must be {expected}")
    measurement = summary["measurement_record"]
    if measurement["legacy_source_system_kind"] != "external_legacy_system":
        raise ValueError("legacy locator review requires external legacy source facts")
    _validate_locator_list(measurement["legacy_source_locators"], "measurement source")
    _records_by_key(summary["primary_data_refs"], "data_id")
    for primary_ref in summary["primary_data_refs"]:
        if primary_ref["reference_state"] == "declared_available":
            _validate_locator_list(primary_ref["legacy_source_locators"], "primary data")


def _validate_locator_list(locators: list[dict[str, Any]], owner: str) -> None:
    if not locators:
        raise ValueError(f"{owner} locator list must not be empty")
    _records_by_key(locators, "locator_id")
    for locator in locators:
        if not locator["display"]:
            raise ValueError(f"{owner} locator display is required")
        if locator["reference_state"] == "declared_available" and locator.get("reason"):
            raise ValueError(f"{owner} available locator must not carry reason")
        if locator["reference_state"] == "unavailable" and not locator.get("reason"):
            raise ValueError(f"{owner} unavailable locator requires reason")


def _validate_source(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_sidecar_summary(source["legacy_run_sidecar_summary"])


def _locator_counts(locators: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "locator_count": len(locators),
        "available_locator_count": sum(
            1 for locator in locators if locator["reference_state"] == "declared_available"
        ),
        "unavailable_locator_count": sum(
            1 for locator in locators if locator["reference_state"] == "unavailable"
        ),
        "navigation_locator_count": sum(
            1
            for locator in locators
            if locator["reference_state"] == "declared_available"
            and locator["kind"] in _NAVIGATION_LOCATOR_KINDS
        ),
        "operator_note_count": sum(1 for locator in locators if locator["kind"] == "operator_note"),
    }


def _classification(locators: list[dict[str, Any]]) -> str:
    counts = _locator_counts(locators)
    if counts["available_locator_count"] == 0:
        return "locator_unavailable_for_review"
    if counts["navigation_locator_count"] == 0:
        return "locator_insufficient_operator_note_only"
    if counts["unavailable_locator_count"]:
        return "locator_declared_with_unavailable_alternative"
    return "locator_declared_sufficient_for_review"


def _finding_for_target(target: dict[str, Any]) -> dict[str, str] | None:
    classification = target["classification"]
    if classification == "locator_declared_sufficient_for_review":
        return None
    if classification == "locator_declared_with_unavailable_alternative":
        return {
            "code": "legacy_locator_alternative_unavailable",
            "severity": "review",
            "target_id": target["target_id"],
            "basis": "At least one declared locator is unavailable, although another locator appears sufficient for review.",
            "does_not_claim": "backend_lookup_or_reference_repair",
        }
    if classification == "locator_insufficient_operator_note_only":
        return {
            "code": "legacy_locator_operator_note_only",
            "severity": "review",
            "target_id": target["target_id"],
            "basis": "Only operator-note locators are available; this may be insufficient for another user to find the legacy data.",
            "does_not_claim": "legacy_record_missing",
        }
    return {
        "code": "legacy_locator_unavailable",
        "severity": "review",
        "target_id": target["target_id"],
        "basis": "No declared locator is currently available for review.",
        "does_not_claim": "legacy_record_missing_or_deleted",
    }


def _target_summary(
    *,
    target_type: str,
    target_id: str,
    label: str,
    locators: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "target_id": target_id,
        "label": label,
        "counts": _locator_counts(locators),
        "available_locator_kinds": sorted(
            {
                locator["kind"]
                for locator in locators
                if locator["reference_state"] == "declared_available"
            }
        ),
        "classification": _classification(locators),
        "locators": copy.deepcopy(locators),
    }


def _targets(summary: dict[str, Any]) -> list[dict[str, Any]]:
    measurement = summary["measurement_record"]
    targets = [
        _target_summary(
            target_type="measurement_legacy_source",
            target_id=measurement["measurement_id"],
            label=measurement["label"],
            locators=measurement["legacy_source_locators"],
        )
    ]
    for primary_ref in summary["primary_data_refs"]:
        if primary_ref["reference_state"] == "declared_available":
            locators = primary_ref["legacy_source_locators"]
        else:
            locators = primary_ref.get("legacy_source_locators", [])
        targets.append(
            _target_summary(
                target_type="primary_data_legacy_source",
                target_id=primary_ref["data_id"],
                label=primary_ref["data_id"],
                locators=locators,
            )
        )
    return targets


def _classification_for_targets(targets: list[dict[str, Any]]) -> str:
    target_classifications = {target["classification"] for target in targets}
    if "locator_unavailable_for_review" in target_classifications:
        return "legacy_locator_review_unavailable"
    if "locator_insufficient_operator_note_only" in target_classifications:
        return "legacy_locator_review_insufficient"
    if "locator_declared_with_unavailable_alternative" in target_classifications:
        return "legacy_locator_review_ready_with_findings"
    return "legacy_locator_review_ready"


def _attention(targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    attention = [
        {
            "code": "locator_values_not_parsed",
            "severity": "info",
            "basis": "Locator values are carried as declared user-navigation hints.",
            "does_not_claim": "backend_reference_validation",
        },
        {
            "code": "backend_lookup_not_performed",
            "severity": "review",
            "basis": "The review does not connect to the legacy system or open referenced files.",
            "does_not_claim": "locator_openability",
        },
    ]
    if any(
        target["classification"] != "locator_declared_sufficient_for_review" for target in targets
    ):
        attention.append(
            {
                "code": "locator_review_findings_present",
                "severity": "review",
                "basis": "At least one locator target needs review before another user can reliably find the legacy data.",
                "does_not_claim": "legacy_data_missing",
            }
        )
    return attention


def build_legacy_locator_sufficiency_review_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a review-only locator sufficiency summary from sidecar facts."""
    _validate_source(source)
    targets = _targets(source["legacy_run_sidecar_summary"])
    findings = [
        finding
        for target in targets
        for finding in [_finding_for_target(target)]
        if finding is not None
    ]
    return {
        "locator_review_policy": copy.deepcopy(source["locator_review_policy"]),
        "source_sidecar": {
            "measurement_id": source["legacy_run_sidecar_summary"]["measurement_record"][
                "measurement_id"
            ],
            "classification": source["legacy_run_sidecar_summary"]["measurement_record"][
                "classification"
            ],
        },
        "classification": _classification_for_targets(targets),
        "target_count": len(targets),
        "targets": targets,
        "locator_findings": findings,
        "attention": _attention(targets),
    }
