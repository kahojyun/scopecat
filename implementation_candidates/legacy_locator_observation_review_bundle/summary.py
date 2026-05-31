"""Compose legacy sidecar review with prior locator-observation summaries.

This module groups an already-built legacy sidecar post-run review with zero
or more prior file-backed locator observation summaries. It does not perform
fresh file observation, query legacy backends, parse data, verify previews,
accept imports, mutate storage, repair references, write parameters, decide
measurement validity, or define GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "review_authority": "explicit_legacy_locator_observation_review_bundle",
    "review_posture": "local_review_summary",
    "input_source": "legacy_sidecar_post_run_review_and_locator_observation_summaries",
    "locator_observation_handling": "prior_summary_only",
    "fresh_file_observation": "not_performed",
    "backend_lookup": "not_performed",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_review_schema": "not_defined",
}

_POST_RUN_POLICY_EXPECTATIONS = {
    "review_authority": "explicit_legacy_sidecar_post_run_review",
    "fresh_observation": "not_performed",
    "primary_data_import": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
}

_LOCATOR_OBSERVATION_POLICY_EXPECTATIONS = {
    "observation_authority": "explicit_legacy_file_backed_locator_observation",
    "input_source": "legacy_sidecar_post_run_review_summary",
    "selected_locator_kind": "legacy_path",
    "external_root_authority": "caller_provided_external_root",
    "observation_level": "file_level_only",
    "checksum_algorithm": "sha256",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "backend_lookup": "not_performed",
    "legacy_import_acceptance": "not_performed",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "reference_repair": "not_performed",
    "parameter_write_back": "not_performed",
    "measurement_validity": "not_claimed",
    "gui_workflow": "not_defined",
}

_READY_OBSERVATION_CLASSIFICATIONS = {
    "legacy_file_backed_locator_observed",
}

_UNAVAILABLE_OBSERVATION_CLASSIFICATIONS = {
    "legacy_file_backed_locator_unavailable_for_review",
}

_MISMATCH_OBSERVATION_CLASSIFICATIONS = {
    "legacy_file_backed_locator_observed_with_file_fact_mismatch",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["locator_observation_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy locator observation review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"legacy locator observation review policy {key} must be {expected}")


def _validate_post_run_review(summary: dict[str, Any]) -> None:
    policy = summary["sidecar_post_run_review_policy"]
    for key, expected in _POST_RUN_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"sidecar post-run review policy {key} must be {expected}")
    sections = summary["review_sections"]
    for section in ("lifecycle", "legacy_locators", "primary_data"):
        if section not in sections:
            raise ValueError(f"sidecar post-run review missing {section} section")
    measurement_id = summary["source_sidecar"]["measurement_id"]
    if not measurement_id:
        raise ValueError("sidecar post-run review measurement_id is required")
    if sections["lifecycle"]["measurement_id"] != measurement_id:
        raise ValueError("lifecycle measurement_id must match source sidecar")
    if summary["review_finding_count"] != len(summary["review_findings"]):
        raise ValueError("sidecar post-run review_finding_count must match findings")


def _locator_targets(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    output = {}
    for target in summary["review_sections"]["legacy_locators"]["targets"]:
        for locator in target["locators"]:
            key = (target["target_id"], locator["locator_id"])
            if key in output:
                raise ValueError(f"duplicate sidecar locator target: {key}")
            output[key] = {
                "target": target,
                "locator": locator,
            }
    return output


def _validate_locator_observation_policy(summary: dict[str, Any]) -> None:
    policy = summary["locator_observation_policy"]
    for key, expected in _LOCATOR_OBSERVATION_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"locator observation policy {key} must be {expected}")


def _validate_locator_observation_summary(
    summary: dict[str, Any],
    *,
    measurement_id: str,
    reviewed_locators: dict[tuple[str, str], dict[str, Any]],
) -> None:
    _validate_locator_observation_policy(summary)
    if summary["source_review"]["measurement_id"] != measurement_id:
        raise ValueError("locator observation measurement_id must match sidecar review")
    selected = summary["selected_locator"]
    key = (selected["target_id"], selected["locator_id"])
    if key not in reviewed_locators:
        raise ValueError("locator observation must match a reviewed sidecar locator")
    reviewed = reviewed_locators[key]
    if selected["display"] != reviewed["locator"]["display"]:
        raise ValueError("locator observation display must match reviewed sidecar locator")
    if selected["kind"] != "legacy_path" or reviewed["locator"]["kind"] != "legacy_path":
        raise ValueError("locator observation must be for a legacy_path locator")
    if selected["redacted"] is not True:
        raise ValueError("locator observation display must remain redacted")
    request = summary["observation_request"]
    if request["measurement_id"] != measurement_id:
        raise ValueError("locator observation request measurement_id must match sidecar")
    if request["target_id"] != selected["target_id"]:
        raise ValueError("locator observation request target_id must match selected locator")
    if request["locator_id"] != selected["locator_id"]:
        raise ValueError("locator observation request locator_id must match selected locator")
    observed = summary["observed_legacy_source"]
    if observed["locator_id"] != selected["locator_id"]:
        raise ValueError("observed legacy source locator_id must match selected locator")
    if observed["path"] != request["source_path"]:
        raise ValueError("observed legacy source path must match observation request")
    effects = summary["observation_effects"]
    for key in (
        "backend_lookup",
        "data_observation",
        "row_count",
        "schema_inference",
        "preview_verification",
        "legacy_import_acceptance",
        "storage_mutation",
        "record_write",
        "reference_repair",
        "parameter_write_back",
    ):
        if effects[key] != "not_performed":
            raise ValueError(f"locator observation effect {key} must be not_performed")
    if effects["legacy_source_parsing"] != "not_performed_by_scopecat":
        raise ValueError("locator observation must not parse legacy sources")
    if effects["measurement_validity"] != "not_claimed":
        raise ValueError("locator observation must not claim measurement validity")


def _validate_locator_observation_summaries(source: dict[str, Any]) -> None:
    summary = source["legacy_sidecar_post_run_review_summary"]
    measurement_id = summary["source_sidecar"]["measurement_id"]
    reviewed_locators = _locator_targets(summary)
    seen = set()
    for observation in source["legacy_locator_observation_summaries"]:
        selected = observation["selected_locator"]
        key = (selected["target_id"], selected["locator_id"])
        if key in seen:
            raise ValueError(f"duplicate locator observation summary: {key}")
        seen.add(key)
        _validate_locator_observation_summary(
            observation,
            measurement_id=measurement_id,
            reviewed_locators=reviewed_locators,
        )


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    if not isinstance(source["legacy_locator_observation_summaries"], list):
        raise ValueError("legacy_locator_observation_summaries must be a list")
    _validate_post_run_review(source["legacy_sidecar_post_run_review_summary"])
    _validate_locator_observation_summaries(source)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _file_backed_locator_count(summary: dict[str, Any]) -> int:
    count = 0
    for target in summary["review_sections"]["legacy_locators"]["targets"]:
        for locator in target["locators"]:
            if locator["kind"] == "legacy_path":
                count += 1
    return count


def _classification(source: dict[str, Any]) -> str:
    base = source["legacy_sidecar_post_run_review_summary"]
    observations = source["legacy_locator_observation_summaries"]
    if base["classification"] in {
        "legacy_sidecar_post_run_failed_needs_review",
        "legacy_sidecar_post_run_partial_needs_review",
        "legacy_sidecar_post_run_locator_unavailable",
        "legacy_sidecar_post_run_needs_locator_review",
    }:
        return "legacy_locator_observation_review_needs_sidecar_attention"
    if any(
        observation["classification"] in _UNAVAILABLE_OBSERVATION_CLASSIFICATIONS
        for observation in observations
    ):
        return "legacy_locator_observation_review_has_unavailable_locator"
    if any(
        observation["classification"] in _MISMATCH_OBSERVATION_CLASSIFICATIONS
        for observation in observations
    ):
        return "legacy_locator_observation_review_has_file_fact_mismatch"
    if base["review_findings"] or any(
        observation["review_findings"] for observation in observations
    ):
        return "legacy_locator_observation_review_needs_attention"
    if observations:
        return "legacy_locator_observation_review_ready"
    if _file_backed_locator_count(base):
        return "legacy_locator_observation_review_ready_without_observation"
    return "legacy_locator_observation_review_no_file_backed_locators"


def _observation_section(source: dict[str, Any]) -> dict[str, Any]:
    observations = source["legacy_locator_observation_summaries"]
    items = []
    findings = []
    for observation in observations:
        items.append(
            {
                "classification": observation["classification"],
                "selected_locator": copy.deepcopy(observation["selected_locator"]),
                "observation_request": copy.deepcopy(observation["observation_request"]),
                "observed_legacy_source": copy.deepcopy(observation["observed_legacy_source"]),
                "declared_preview_assertion": copy.deepcopy(
                    observation["declared_preview_assertion"]
                ),
                "review_findings": copy.deepcopy(observation["review_findings"]),
            }
        )
        for finding in observation["review_findings"]:
            item = copy.deepcopy(finding)
            item["source_section"] = "legacy_locator_observation"
            item["target_id"] = observation["selected_locator"]["target_id"]
            item["locator_id"] = observation["selected_locator"]["locator_id"]
            findings.append(item)

    observed_items = [observation["observed_legacy_source"] for observation in observations]
    return {
        "locator_observation_count": len(observations),
        "file_backed_locator_count": _file_backed_locator_count(
            source["legacy_sidecar_post_run_review_summary"]
        ),
        "classification_counts": _state_counts(observations, "classification"),
        "observation_status_counts": _state_counts(observed_items, "status"),
        "observations": items,
        "observation_finding_count": len(findings),
        "observation_findings": findings,
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = copy.deepcopy(source["legacy_sidecar_post_run_review_summary"]["review_findings"])
    for observation in source["legacy_locator_observation_summaries"]:
        for finding in observation["review_findings"]:
            item = copy.deepcopy(finding)
            item["source_section"] = "legacy_locator_observation"
            item["target_id"] = observation["selected_locator"]["target_id"]
            item["locator_id"] = observation["selected_locator"]["locator_id"]
            findings.append(item)
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "legacy_locator_observation_review_only",
            "severity": "info",
            "basis": "The review groups prior sidecar post-run review and prior locator-observation summaries.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "locator_observation_is_prior_summary",
            "severity": "info",
            "basis": "Locator observation is carried from prior file-level observation summaries.",
            "does_not_claim": "fresh_file_observation",
        },
        {
            "code": "legacy_payload_not_parsed",
            "severity": "review",
            "basis": "Observed locator facts are file-level only and legacy payloads are not parsed.",
            "does_not_claim": "row_count_schema_preview_or_data_validation",
        },
        {
            "code": "reference_repair_not_performed",
            "severity": "review",
            "basis": "Unavailable or mismatched locator facts remain review findings.",
            "does_not_claim": "moved_reference_discovery_or_repair",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "Locator observation review does not judge measurement validity.",
            "does_not_claim": "measurement_validity",
        },
    ]


def build_legacy_locator_observation_review_bundle_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a local review bundle for legacy locator observation facts."""
    _validate_references(source)
    base = source["legacy_sidecar_post_run_review_summary"]
    findings = _review_findings(source)
    return {
        "locator_observation_review_policy": copy.deepcopy(
            source["locator_observation_review_policy"]
        ),
        "classification": _classification(source),
        "source_review": {
            "measurement_id": base["source_sidecar"]["measurement_id"],
            "post_run_classification": base["classification"],
            "locator_review_classification": base["source_sidecar"][
                "locator_review_classification"
            ],
            "sidecar_review_finding_count": base["review_finding_count"],
        },
        "review_sections": {
            "sidecar_post_run_review": {
                "classification": base["classification"],
                "review_finding_count": base["review_finding_count"],
                "review_findings": copy.deepcopy(base["review_findings"]),
            },
            "legacy_locator_observation": _observation_section(source),
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "attention": _attention(),
    }
