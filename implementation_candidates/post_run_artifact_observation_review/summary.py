"""Compose post-run artifact review with prior artifact observation summaries."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "review_authority": "explicit_post_run_artifact_observation_review",
    "review_posture": "local_review_summary",
    "input_source": "post_run_artifact_provenance_review_and_supporting_artifact_observation_summaries",
    "artifact_observation_handling": "prior_summary_only",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_observation": "not_performed",
    "evidence_payload_import": "not_performed",
    "fresh_artifact_file_observation": "not_performed",
    "fresh_checksum_validation": "not_performed",
    "artifact_parsing": "not_performed",
    "preview_generation": "not_performed",
    "source_payload_observation": "not_performed",
    "artifact_generation": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "analysis_dag_inference": "not_performed",
    "fit_validation": "not_performed",
    "measurement_validity": "not_claimed",
    "import_export_package": "not_produced",
    "gui_workflow": "not_defined",
    "shared_review_schema": "not_defined",
}

_POST_RUN_PROVENANCE_REVIEW_POLICY_REQUIREMENTS = {
    "review_posture": "local_review_summary",
    "artifact_provenance_handling": "prior_summary_only",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_observation": "not_performed",
    "evidence_payload_import": "not_performed",
    "artifact_file_observation": "not_performed",
    "source_payload_observation": "not_performed",
    "checksum_validation": "not_performed",
    "artifact_generation": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "analysis_dag_inference": "not_performed",
    "fit_validation": "not_performed",
    "measurement_validity": "not_claimed",
    "import_export_package": "not_produced",
}

_ARTIFACT_OBSERVATION_POLICY_REQUIREMENTS = {
    "artifact_observation": "file_level_only",
    "checksum_algorithm": "sha256",
    "payload_import": "not_performed",
    "artifact_parsing": "not_performed",
    "preview_generation": "not_performed",
    "source_payload_observation": "not_performed",
    "storage_mutation": "not_performed",
    "artifact_generation": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "analysis_dag_inference": "not_performed",
    "fit_validation": "not_performed",
    "measurement_validity": "not_claimed",
    "import_export_package": "not_produced",
}

_READY_OBSERVATION_CLASSIFICATIONS = {
    "supporting_artifact_observed_matches_declared_file_facts",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["artifact_observation_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("artifact observation review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"artifact observation review policy {key} must be {expected}")


def _validate_post_run_artifact_provenance_review(source: dict[str, Any]) -> None:
    summary = source["post_run_artifact_provenance_review_summary"]
    policy = summary["artifact_provenance_review_policy"]
    for key, expected in _POST_RUN_PROVENANCE_REVIEW_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"post-run artifact provenance review policy {key} must be {expected}")
    sections = summary["review_sections"]
    if "artifact_provenance" not in sections:
        raise ValueError("post-run artifact provenance review must carry artifact_provenance")


def _reviewed_artifacts(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = {}
    for item in summary["review_sections"]["artifact_provenance"]["artifacts"]:
        artifact = item["artifact"]
        artifact_id = artifact["artifact_id"]
        if artifact_id in artifacts:
            raise ValueError(f"duplicate reviewed artifact_id: {artifact_id}")
        artifacts[artifact_id] = artifact
    return artifacts


def _validate_observation_summary_policy(summary: dict[str, Any]) -> None:
    policy = summary["artifact_observation_policy"]
    for key, expected in _ARTIFACT_OBSERVATION_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"artifact observation policy {key} must be {expected}")


def _validate_observation_summary(
    summary: dict[str, Any],
    reviewed_artifacts: dict[str, dict[str, Any]],
) -> None:
    _validate_observation_summary_policy(summary)
    artifact = summary["artifact"]
    artifact_id = artifact["artifact_id"]
    if artifact_id not in reviewed_artifacts:
        raise ValueError("artifact observation summary must match reviewed artifact")
    if reviewed_artifacts[artifact_id]["declared_reference"] != artifact["declared_reference"]:
        raise ValueError("artifact observation declared reference must match reviewed artifact")
    observed = summary["observed_artifact"]
    if observed["artifact_id"] != artifact_id:
        raise ValueError("observed artifact_id must match observation artifact")
    if observed["path"] != artifact["declared_reference"]["value"]:
        raise ValueError("observed artifact path must match declared artifact reference")


def _validate_observation_summaries(source: dict[str, Any]) -> None:
    reviewed = _reviewed_artifacts(source["post_run_artifact_provenance_review_summary"])
    seen = set()
    for summary in source["artifact_observation_summaries"]:
        artifact_id = summary["artifact"]["artifact_id"]
        if artifact_id in seen:
            raise ValueError(f"duplicate artifact observation summary: {artifact_id}")
        seen.add(artifact_id)
        _validate_observation_summary(summary, reviewed)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_post_run_artifact_provenance_review(source)
    _validate_observation_summaries(source)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(source: dict[str, Any]) -> str:
    base_classification = source["post_run_artifact_provenance_review_summary"]["classification"]
    if base_classification == "post_run_artifact_provenance_review_blocked":
        return "post_run_artifact_observation_review_blocked"
    observation_summaries = source["artifact_observation_summaries"]
    if (
        source["post_run_artifact_provenance_review_summary"]["review_findings"]
        or any(summary["review_findings"] for summary in observation_summaries)
        or any(
            summary["artifact"]["classification"] not in _READY_OBSERVATION_CLASSIFICATIONS
            for summary in observation_summaries
        )
    ):
        return "post_run_artifact_observation_review_needs_attention"
    return "post_run_artifact_observation_review_ready"


def _artifact_observation_section(source: dict[str, Any]) -> dict[str, Any]:
    summaries = source["artifact_observation_summaries"]
    artifacts = []
    findings = []
    for summary in summaries:
        artifacts.append(
            {
                "artifact": copy.deepcopy(summary["artifact"]),
                "observation_request": copy.deepcopy(summary["observation_request"]),
                "observed_artifact": copy.deepcopy(summary["observed_artifact"]),
                "review_findings": copy.deepcopy(summary["review_findings"]),
            }
        )
        findings.extend(copy.deepcopy(summary["review_findings"]))

    observed_items = [summary["observed_artifact"] for summary in summaries]
    artifact_items = [summary["artifact"] for summary in summaries]
    return {
        "artifact_observation_count": len(summaries),
        "classification_counts": _state_counts(artifact_items, "classification"),
        "observation_status_counts": _state_counts(observed_items, "status"),
        "artifacts": artifacts,
        "observation_finding_count": len(findings),
        "observation_findings": findings,
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = copy.deepcopy(
        source["post_run_artifact_provenance_review_summary"]["review_findings"]
    )
    for summary in source["artifact_observation_summaries"]:
        artifact_id = summary["artifact"]["artifact_id"]
        for finding in summary["review_findings"]:
            item = copy.deepcopy(finding)
            item["artifact_id"] = artifact_id
            item["source_section"] = "artifact_observation"
            findings.append(item)
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "post_run_artifact_observation_review_only",
            "severity": "info",
            "basis": "The review groups prior artifact-provenance review and artifact-observation summaries.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "artifact_observation_is_prior_summary",
            "severity": "info",
            "basis": "Artifact observation is carried from prior file-level observation summaries.",
            "does_not_claim": "fresh_artifact_file_observation",
        },
        {
            "code": "artifact_payload_not_parsed",
            "severity": "review",
            "basis": "Observed artifact facts are file-level only and payloads are not parsed.",
            "does_not_claim": "artifact_payload_or_preview_validation",
        },
        {
            "code": "source_payloads_not_observed",
            "severity": "review",
            "basis": "Source links remain prior provenance facts; source payloads are not opened.",
            "does_not_claim": "source_payload_or_integrity_verified",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "Post-run artifact observation review does not judge fit quality or measurement validity.",
            "does_not_claim": "artifact_or_measurement_validity",
        },
    ]


def build_post_run_artifact_observation_review_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a local post-run review summary with artifact observation findings."""
    _validate_references(source)
    findings = _review_findings(source)
    base = source["post_run_artifact_provenance_review_summary"]
    return {
        "artifact_observation_review_policy": copy.deepcopy(
            source["artifact_observation_review_policy"]
        ),
        "completed_measurement": copy.deepcopy(base["completed_measurement"]),
        "classification": _classification(source),
        "review_sections": {
            "post_run_artifact_provenance_review": {
                "classification": base["classification"],
                "review_finding_count": base["review_finding_count"],
                "review_findings": copy.deepcopy(base["review_findings"]),
            },
            "artifact_observation": _artifact_observation_section(source),
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "attention": _attention(),
    }
