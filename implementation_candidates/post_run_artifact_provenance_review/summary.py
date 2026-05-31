"""Compose post-run review with prior supporting-artifact provenance summaries."""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "review_authority": "explicit_post_run_artifact_provenance_review",
    "review_posture": "local_review_summary",
    "input_source": "post_run_review_and_supporting_artifact_provenance_summaries",
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
    "gui_workflow": "not_defined",
    "shared_review_schema": "not_defined",
}

_POST_RUN_POLICY_REQUIREMENTS = {
    "bundle_posture": "local_review_summary",
    "storage_mutation": "not_performed",
    "record_write": "not_performed",
    "primary_data_observation": "not_performed",
    "evidence_payload_import": "not_performed",
    "file_observation": "not_performed",
    "artifact_provenance": "not_performed",
    "fit_validation": "not_performed",
    "import_export_package": "not_produced",
    "measurement_validity": "not_claimed",
}

_ARTIFACT_PROVENANCE_POLICY_REQUIREMENTS = {
    "provenance_posture": "declared_source_links_for_supporting_artifact",
    "input_source": "supporting_evidence_reference_summary",
    "requires_supporting_evidence_kind": "artifact",
    "source_link_scope": "direct_declared_sources_only",
    "payload_import": "not_performed",
    "artifact_file_observation": "not_performed",
    "source_payload_observation": "not_performed",
    "checksum_validation": "not_performed",
    "storage_mutation": "not_performed",
    "artifact_generation": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "analysis_dag_inference": "not_performed",
    "fit_validation": "not_performed",
    "measurement_validity": "not_claimed",
    "portable_public_export": "not_declared",
}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["artifact_provenance_review_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("artifact provenance review policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"artifact provenance review policy {key} must be {expected}")


def _validate_post_run_summary(source: dict[str, Any]) -> None:
    summary = source["post_run_review_summary"]
    policy = summary["post_run_review_policy"]
    for key, expected in _POST_RUN_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"post-run review policy {key} must be {expected}")
    if "review_sections" not in summary:
        raise ValueError("post-run review summary must carry review_sections")
    if "supporting_evidence" not in summary["review_sections"]:
        raise ValueError("post-run review summary must carry supporting evidence section")
    if policy["artifact_provenance"] != "not_performed":
        raise ValueError("base post-run review must not perform artifact provenance")


def _artifact_evidence_refs(post_run_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = {}
    for ref in post_run_summary["review_sections"]["supporting_evidence"]["evidence_refs"]:
        if ref["evidence_kind"] != "artifact":
            continue
        evidence_id = ref["evidence_id"]
        if evidence_id in refs:
            raise ValueError(f"duplicate artifact evidence_id: {evidence_id}")
        refs[evidence_id] = ref
    return refs


def _validate_provenance_summary_policy(summary: dict[str, Any]) -> None:
    policy = summary["artifact_provenance_policy"]
    for key, expected in _ARTIFACT_PROVENANCE_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"artifact provenance policy {key} must be {expected}")


def _validate_provenance_summary(
    summary: dict[str, Any],
    artifact_refs: dict[str, dict[str, Any]],
    measurement_id: str,
) -> None:
    _validate_provenance_summary_policy(summary)
    artifact = summary["artifact"]
    artifact_id = artifact["artifact_id"]
    if artifact_id not in artifact_refs:
        raise ValueError("artifact provenance summary must match post-run artifact evidence")
    if artifact_refs[artifact_id]["declared_reference"] != artifact["declared_reference"]:
        raise ValueError("artifact provenance declared reference must match post-run evidence")
    if summary["producer"]["execution_state"] not in {
        "declared_completed",
        "unavailable",
        "redacted",
    }:
        raise ValueError("artifact producer execution_state is unsupported")
    if not any(
        link["source_type"] == "measurement_record" and link["source_id"] == measurement_id
        for link in summary["source_links"]
    ):
        raise ValueError("artifact provenance must link to the completed measurement")


def _validate_provenance_summaries(source: dict[str, Any]) -> None:
    post_run_summary = source["post_run_review_summary"]
    artifact_refs = _artifact_evidence_refs(post_run_summary)
    measurement_id = post_run_summary["completed_measurement"]["measurement_record_id"]
    seen = set()
    for summary in source["artifact_provenance_summaries"]:
        artifact_id = summary["artifact"]["artifact_id"]
        if artifact_id in seen:
            raise ValueError(f"duplicate artifact provenance summary: {artifact_id}")
        seen.add(artifact_id)
        _validate_provenance_summary(summary, artifact_refs, measurement_id)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_post_run_summary(source)
    _validate_provenance_summaries(source)


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(source: dict[str, Any]) -> str:
    base_classification = source["post_run_review_summary"]["classification"]
    if base_classification == "post_run_review_blocked":
        return "post_run_artifact_provenance_review_blocked"
    provenance_summaries = source["artifact_provenance_summaries"]
    if (
        source["post_run_review_summary"]["review_findings"]
        or any(summary["provenance_findings"] for summary in provenance_summaries)
        or any(
            summary["classification"] != "ready_for_artifact_provenance_review"
            for summary in provenance_summaries
        )
    ):
        return "post_run_artifact_provenance_review_needs_attention"
    return "post_run_artifact_provenance_review_ready"


def _artifact_provenance_section(source: dict[str, Any]) -> dict[str, Any]:
    summaries = source["artifact_provenance_summaries"]
    artifacts = []
    findings = []
    for summary in summaries:
        artifacts.append(
            {
                "artifact": copy.deepcopy(summary["artifact"]),
                "producer": copy.deepcopy(summary["producer"]),
                "classification": summary["classification"],
                "source_link_count": summary["source_link_count"],
                "source_state_counts": copy.deepcopy(summary["source_state_counts"]),
                "source_links": copy.deepcopy(summary["source_links"]),
            }
        )
        findings.extend(copy.deepcopy(summary["provenance_findings"]))

    return {
        "artifact_provenance_count": len(summaries),
        "classification_counts": _state_counts(summaries, "classification"),
        "artifacts": artifacts,
        "provenance_finding_count": len(findings),
        "provenance_findings": findings,
    }


def _review_findings(source: dict[str, Any]) -> list[dict[str, Any]]:
    findings = copy.deepcopy(source["post_run_review_summary"]["review_findings"])
    for summary in source["artifact_provenance_summaries"]:
        for finding in summary["provenance_findings"]:
            item = copy.deepcopy(finding)
            item["source_section"] = "artifact_provenance"
            findings.append(item)
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "post_run_artifact_provenance_review_only",
            "severity": "info",
            "basis": "The review groups prior post-run and artifact-provenance summaries.",
            "does_not_claim": "durable_record_update",
        },
        {
            "code": "artifact_provenance_is_prior_summary",
            "severity": "info",
            "basis": "Artifact provenance is carried from prior declared provenance summaries.",
            "does_not_claim": "fresh_artifact_provenance_validation",
        },
        {
            "code": "artifact_and_sources_not_observed",
            "severity": "review",
            "basis": "Artifacts and source payloads are not opened, checksummed, or parsed.",
            "does_not_claim": "artifact_or_source_integrity_verified",
        },
        {
            "code": "analysis_dag_not_inferred",
            "severity": "review",
            "basis": "Only direct prior provenance links are surfaced.",
            "does_not_claim": "recursive_analysis_dag",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "Post-run provenance review does not judge fit quality or measurement validity.",
            "does_not_claim": "artifact_or_measurement_validity",
        },
    ]


def build_post_run_artifact_provenance_review_summary(
    source: dict[str, Any],
) -> dict[str, Any]:
    """Build a local post-run review summary with artifact provenance findings."""
    _validate_references(source)
    findings = _review_findings(source)
    post_run_summary = source["post_run_review_summary"]
    return {
        "artifact_provenance_review_policy": copy.deepcopy(
            source["artifact_provenance_review_policy"]
        ),
        "completed_measurement": copy.deepcopy(post_run_summary["completed_measurement"]),
        "classification": _classification(source),
        "review_sections": {
            "post_run_review": {
                "classification": post_run_summary["classification"],
                "review_finding_count": post_run_summary["review_finding_count"],
                "review_findings": copy.deepcopy(post_run_summary["review_findings"]),
            },
            "artifact_provenance": _artifact_provenance_section(source),
        },
        "review_finding_count": len(findings),
        "review_findings": findings,
        "attention": _attention(),
    }
