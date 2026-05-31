"""Post-run review projection for legacy sidecar summaries.

This module composes prior sidecar and locator-review summaries into one local
post-run review projection. It does not execute legacy code, observe files,
import legacy data, mutate storage, write parameters, repair references, or
define GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "review_authority": "explicit_legacy_sidecar_post_run_review",
    "review_posture": "local_review_summary",
    "input_source": "prior_sidecar_and_locator_summaries",
    "fresh_observation": "not_performed",
    "primary_data_import": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_review_schema": "not_defined",
}

_SIDECAR_POLICY_EXPECTATIONS = {
    "sidecar_authority": "declared_legacy_runtime_boundary",
    "manifest_posture": "local_review_summary",
    "primary_data_observation": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
}

_LOCATOR_REVIEW_POLICY_EXPECTATIONS = {
    "review_authority": "explicit_legacy_locator_sufficiency_review",
    "backend_lookup": "not_performed",
    "file_observation": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "reference_repair": "not_performed",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["sidecar_post_run_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy sidecar post-run review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy sidecar post-run review policy {key} must be {expected}")


def _validate_sidecar_summary(summary: dict[str, Any]) -> None:
    sidecar_policy = summary["sidecar_policy"]
    for key, expected in _SIDECAR_POLICY_EXPECTATIONS.items():
        if sidecar_policy[key] != expected:
            raise ValueError(f"sidecar summary policy {key} must be {expected}")
    measurement = summary["measurement_record"]
    if not measurement["measurement_id"]:
        raise ValueError("sidecar measurement id is required")
    if measurement["legacy_source_system_kind"] != "external_legacy_system":
        raise ValueError("sidecar measurement must preserve external legacy source facts")


def _validate_locator_review(sidecar: dict[str, Any], locator_review: dict[str, Any]) -> None:
    policy = locator_review["locator_review_policy"]
    for key, expected in _LOCATOR_REVIEW_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"locator review policy {key} must be {expected}")
    measurement_id = sidecar["measurement_record"]["measurement_id"]
    if locator_review["source_sidecar"]["measurement_id"] != measurement_id:
        raise ValueError("locator review measurement_id must match sidecar measurement")
    if (
        locator_review["source_sidecar"]["classification"]
        != sidecar["measurement_record"]["classification"]
    ):
        raise ValueError("locator review source classification must match sidecar classification")
    target_ids = {target["target_id"] for target in locator_review["targets"]}
    if measurement_id not in target_ids:
        raise ValueError("locator review must include the sidecar measurement target")
    for primary_ref in sidecar["primary_data_refs"]:
        if primary_ref["data_id"] not in target_ids:
            raise ValueError("locator review must include each sidecar primary data target")


def _validate_source(source: dict[str, Any]) -> None:
    _validate_policy(source)
    sidecar = source["legacy_run_sidecar_summary"]
    locator_review = source["legacy_locator_sufficiency_review_summary"]
    _validate_sidecar_summary(sidecar)
    _validate_locator_review(sidecar, locator_review)


def _lifecycle_section(sidecar: dict[str, Any]) -> dict[str, Any]:
    measurement = sidecar["measurement_record"]
    return {
        "measurement_id": measurement["measurement_id"],
        "label": measurement["label"],
        "experiment_type": measurement["experiment_type"],
        "target": copy.deepcopy(measurement["target"]),
        "lifecycle": copy.deepcopy(measurement["lifecycle"]),
        "sidecar_classification": measurement["classification"],
    }


def _locator_section(locator_review: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": locator_review["classification"],
        "target_count": locator_review["target_count"],
        "targets": copy.deepcopy(locator_review["targets"]),
        "locator_findings": copy.deepcopy(locator_review["locator_findings"]),
    }


def _primary_data_section(sidecar: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_data_ref_count": len(sidecar["primary_data_refs"]),
        "primary_data_refs": copy.deepcopy(sidecar["primary_data_refs"]),
    }


def _evidence_section(sidecar: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = sidecar["supporting_evidence_refs"]
    counts: dict[str, int] = {}
    for ref in evidence_refs:
        kind = ref["evidence_kind"]
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "supporting_evidence_ref_count": len(evidence_refs),
        "evidence_kind_counts": dict(sorted(counts.items())),
        "supporting_evidence_refs": copy.deepcopy(evidence_refs),
    }


def _review_findings(
    sidecar: dict[str, Any], locator_review: dict[str, Any]
) -> list[dict[str, Any]]:
    findings = []
    for finding in sidecar["manifest_findings"]:
        item = copy.deepcopy(finding)
        item["source_section"] = "sidecar_manifest"
        findings.append(item)
    for finding in locator_review["locator_findings"]:
        item = copy.deepcopy(finding)
        item["source_section"] = "legacy_locator_review"
        findings.append(item)
    return findings


def _classification(sidecar: dict[str, Any], locator_review: dict[str, Any]) -> str:
    lifecycle_state = sidecar["measurement_record"]["lifecycle"]["state"]
    locator_classification = locator_review["classification"]
    if lifecycle_state == "failed":
        return "legacy_sidecar_post_run_failed_needs_review"
    if lifecycle_state == "partial":
        return "legacy_sidecar_post_run_partial_needs_review"
    if locator_classification == "legacy_locator_review_unavailable":
        return "legacy_sidecar_post_run_locator_unavailable"
    if locator_classification in {
        "legacy_locator_review_insufficient",
        "legacy_locator_review_ready_with_findings",
    }:
        return "legacy_sidecar_post_run_needs_locator_review"
    if sidecar["manifest_findings"] or locator_review["locator_findings"]:
        return "legacy_sidecar_post_run_needs_attention"
    return "legacy_sidecar_post_run_ready"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "sidecar_post_run_review_only",
            "severity": "info",
            "basis": "The projection composes prior sidecar and locator review summaries.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "fresh_observation_not_performed",
            "severity": "review",
            "basis": "The projection does not open files, connect to legacy systems, or observe primary data.",
            "does_not_claim": "locator_openability_or_data_validity",
        },
        {
            "code": "legacy_import_not_performed",
            "severity": "review",
            "basis": "Legacy primary data references remain external declarations.",
            "does_not_claim": "import_acceptance_or_normalized_data",
        },
        {
            "code": "parameter_write_back_not_performed",
            "severity": "review",
            "basis": "The projection does not apply parameter or calibration changes.",
            "does_not_claim": "parameter_state_updated",
        },
    ]


def build_legacy_sidecar_post_run_review_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a local post-run review projection from sidecar summaries."""
    _validate_source(source)
    sidecar = source["legacy_run_sidecar_summary"]
    locator_review = source["legacy_locator_sufficiency_review_summary"]
    findings = _review_findings(sidecar, locator_review)
    return {
        "sidecar_post_run_review_policy": copy.deepcopy(source["sidecar_post_run_review_policy"]),
        "classification": _classification(sidecar, locator_review),
        "source_sidecar": {
            "measurement_id": sidecar["measurement_record"]["measurement_id"],
            "sidecar_classification": sidecar["measurement_record"]["classification"],
            "locator_review_classification": locator_review["classification"],
        },
        "review_sections": {
            "lifecycle": _lifecycle_section(sidecar),
            "legacy_locators": _locator_section(locator_review),
            "primary_data": _primary_data_section(sidecar),
            "supporting_evidence": _evidence_section(sidecar),
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "attention": _attention(),
    }
