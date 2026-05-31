"""Declared provenance summary for supporting evidence artifacts.

This module validates explicit provenance/source links for supporting evidence
that is already labeled as an artifact. It does not open artifact files, import
payloads, observe source records, calculate checksums, generate artifacts,
infer analysis DAGs, judge fit quality, decide measurement validity, or define
GUI behavior.
"""

from __future__ import annotations

import copy
from typing import Any

_EXPECTED_POLICY = {
    "provenance_authority": "explicit_supporting_artifact_provenance_manifest",
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
    "gui_workflow": "not_defined",
    "shared_artifact_schema": "not_defined",
}

_AUTHORITY = "explicit_supporting_artifact_provenance_manifest"
_SUPPORTING_POLICY_REQUIREMENTS = {
    "evidence_posture": "supporting_evidence_reference",
    "evidence_context_role": "supporting_evidence_not_canonical_context",
    "evidence_kind_handling": "attachment_or_artifact_label_only",
    "artifact_provenance": "not_required_without_artifact_provenance_slice",
    "payload_import": "not_performed",
    "file_observation": "not_performed",
    "evidence_parsing": "not_performed",
    "checksum_validation": "not_performed",
    "storage_mutation": "not_performed",
    "preview_generation": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "measurement_validity": "not_claimed",
}
_PRODUCER_KINDS = {
    "analysis_script",
    "notebook",
    "user_adapter",
    "manual_report",
    "unknown_declared",
}
_PRODUCER_STATES = {"declared_completed", "unavailable", "redacted"}
_SOURCE_TYPES = {
    "measurement_record",
    "calibration_step",
    "parameter_state",
    "prepared_run",
    "running_measurement",
    "managed_code_version",
    "analysis_choice",
}
_SOURCE_ROLES = {
    "primary_input",
    "comparison_reference",
    "calibration_context",
    "parameter_context",
    "code_context",
    "analysis_setting",
}
_RELATIONS = {
    "derived_from",
    "compares_against",
    "uses_context",
    "documents_choice",
}
_SOURCE_STATES = {"declared_available", "unavailable", "redacted", "unlinked"}


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["artifact_provenance_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("artifact provenance policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"artifact provenance policy {key} must be {expected}")


def _validate_supporting_evidence_summary(source: dict[str, Any]) -> None:
    summary = source["supporting_evidence_summary"]
    policy = summary["supporting_evidence_policy"]
    for key, expected in _SUPPORTING_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"supporting evidence policy {key} must be {expected}")

    evidence = summary["evidence"]
    if evidence["evidence_kind"] != "artifact":
        raise ValueError("supporting evidence must be labeled as artifact")
    if evidence["declared_reference"]["reference_state"] not in {
        "declared_available",
        "unavailable",
        "redacted",
    }:
        raise ValueError("artifact evidence reference_state is unsupported")
    if "payload" in evidence:
        raise ValueError("supporting artifact payload must not be supplied")
    if "provenance" in evidence:
        raise ValueError("supporting artifact provenance must use this slice")


def _validate_artifact_identity(source: dict[str, Any]) -> None:
    evidence = source["supporting_evidence_summary"]["evidence"]
    identity = source["artifact_identity"]
    expected_keys = {
        "artifact_id",
        "evidence_id",
        "label",
        "declared_reference",
        "authority",
    }
    if set(identity) != expected_keys:
        raise ValueError("artifact identity must match expected shape")
    if identity["artifact_id"] != evidence["evidence_id"]:
        raise ValueError("artifact_id must match supporting evidence evidence_id")
    if identity["evidence_id"] != evidence["evidence_id"]:
        raise ValueError("artifact identity evidence_id must match supporting evidence")
    if identity["label"] != evidence["label"]:
        raise ValueError("artifact identity label must match supporting evidence")
    if identity["declared_reference"] != evidence["declared_reference"]:
        raise ValueError("artifact declared reference must match supporting evidence")
    if identity["authority"] != _AUTHORITY:
        raise ValueError("artifact identity authority must stay explicit")


def _validate_producer(producer: dict[str, Any]) -> None:
    expected_keys = {
        "producer_kind",
        "producer_id",
        "label",
        "authority",
        "execution_state",
        "reason",
    }
    if set(producer) != expected_keys:
        raise ValueError("artifact producer must match expected shape")
    if producer["producer_kind"] not in _PRODUCER_KINDS:
        raise ValueError("artifact producer_kind is unsupported")
    if not producer["producer_id"]:
        raise ValueError("artifact producer_id is required")
    if producer["authority"] != _AUTHORITY:
        raise ValueError("artifact producer authority must stay explicit")
    if producer["execution_state"] not in _PRODUCER_STATES:
        raise ValueError("artifact producer execution_state is unsupported")
    if producer["execution_state"] != "declared_completed" and not producer.get("reason"):
        raise ValueError("unavailable or redacted artifact producer requires reason")
    if producer["execution_state"] == "declared_completed" and producer.get("reason"):
        raise ValueError("completed artifact producer must not carry reason")


def _validate_source_link(link: dict[str, Any]) -> None:
    expected_keys = {
        "source_type",
        "source_id",
        "label",
        "source_role",
        "relation",
        "authority",
        "source_state",
        "reason",
    }
    if set(link) != expected_keys:
        raise ValueError("artifact source link must match expected shape")
    if link["source_type"] not in _SOURCE_TYPES:
        raise ValueError("artifact source_type is unsupported")
    if not link["source_id"]:
        raise ValueError("artifact source_id is required")
    if link["source_role"] not in _SOURCE_ROLES:
        raise ValueError("artifact source_role is unsupported")
    if link["relation"] not in _RELATIONS:
        raise ValueError("artifact source relation is unsupported")
    if link["authority"] != _AUTHORITY:
        raise ValueError("artifact source authority must stay explicit")
    if link["source_state"] not in _SOURCE_STATES:
        raise ValueError("artifact source_state is unsupported")
    if link["source_state"] != "declared_available" and not link.get("reason"):
        raise ValueError("unavailable, redacted, or unlinked artifact source requires reason")
    if link["source_state"] == "declared_available" and link.get("reason"):
        raise ValueError("available artifact source must not carry reason")


def _validate_source_links(source_links: list[dict[str, Any]]) -> None:
    seen = set()
    for link in source_links:
        key = (link["source_type"], link["source_id"], link["relation"])
        if key in seen:
            raise ValueError(f"duplicate artifact source link: {link['source_id']}")
        seen.add(key)
        _validate_source_link(link)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_supporting_evidence_summary(source)
    _validate_artifact_identity(source)
    _validate_producer(source["producer"])
    _validate_source_links(source["source_links"])


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(
    supporting_summary: dict[str, Any],
    producer: dict[str, Any],
    source_links: list[dict[str, Any]],
) -> str:
    reference_state = supporting_summary["evidence"]["declared_reference"]["reference_state"]
    if reference_state != "declared_available":
        return "needs_artifact_reference_review"
    if producer["execution_state"] != "declared_completed":
        return "needs_artifact_producer_review"
    if any(link["source_state"] == "unavailable" for link in source_links):
        return "needs_artifact_source_review"
    if any(link["source_state"] in {"redacted", "unlinked"} for link in source_links):
        return "needs_artifact_link_review"
    return "ready_for_artifact_provenance_review"


def _artifact_summary(source: dict[str, Any]) -> dict[str, Any]:
    evidence = source["supporting_evidence_summary"]["evidence"]
    return {
        "artifact_id": evidence["evidence_id"],
        "label": evidence["label"],
        "content_kind": evidence["content_kind"],
        "purpose": evidence["purpose"],
        "lifecycle_stage": evidence["lifecycle_stage"],
        "declared_reference": copy.deepcopy(evidence["declared_reference"]),
        "supporting_evidence_classification": source["supporting_evidence_summary"][
            "classification"
        ],
    }


def _source_link_summary(artifact_id: str, link: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_type": link["source_type"],
        "source_id": link["source_id"],
        "label": link["label"],
        "source_role": link["source_role"],
        "relation": link["relation"],
        "authority": link["authority"],
        "source_state": link["source_state"],
        "reason": link.get("reason"),
    }


def _findings(
    supporting_summary: dict[str, Any],
    producer: dict[str, Any],
    source_links: list[dict[str, Any]],
) -> list[dict[str, str]]:
    artifact_id = supporting_summary["evidence"]["evidence_id"]
    findings = []
    reference = supporting_summary["evidence"]["declared_reference"]
    if reference["reference_state"] != "declared_available":
        findings.append(
            {
                "artifact_id": artifact_id,
                "subject_type": "supporting_artifact",
                "subject_id": reference["value"],
                "severity": "review",
                "finding": f"artifact_reference_{reference['reference_state']}",
                "basis": reference["reason"],
                "does_not_claim": "artifact_payload_missing_or_invalid",
            }
        )

    if producer["execution_state"] != "declared_completed":
        findings.append(
            {
                "artifact_id": artifact_id,
                "subject_type": "artifact_producer",
                "subject_id": producer["producer_id"],
                "severity": "review",
                "finding": f"artifact_producer_{producer['execution_state']}",
                "basis": producer["reason"],
                "does_not_claim": "artifact_invalid_or_unreproducible",
            }
        )

    for link in source_links:
        if link["source_state"] == "declared_available":
            continue
        findings.append(
            {
                "artifact_id": artifact_id,
                "subject_type": link["source_type"],
                "subject_id": link["source_id"],
                "severity": "review",
                "finding": f"artifact_source_{link['source_state']}",
                "basis": link["reason"],
                "does_not_claim": "analysis_lineage_invalid_or_complete",
            }
        )
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "declared_provenance_only",
            "severity": "info",
            "basis": "Artifact provenance comes from an explicit provenance manifest.",
            "does_not_claim": "complete_analysis_provenance",
        },
        {
            "code": "artifact_payload_not_observed",
            "severity": "review",
            "basis": "The supporting artifact reference is carried without opening or parsing the artifact.",
            "does_not_claim": "artifact_contents_verified",
        },
        {
            "code": "sources_not_observed",
            "severity": "review",
            "basis": "Source links are declared identities and their payloads are not opened.",
            "does_not_claim": "source_payload_or_integrity_verified",
        },
        {
            "code": "direct_sources_only",
            "severity": "review",
            "basis": "Only directly declared source links are summarized.",
            "does_not_claim": "recursive_analysis_dag",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "Provenance links explain declared origin but do not judge fit quality or measurement validity.",
            "does_not_claim": "artifact_or_measurement_validity",
        },
    ]


def build_supporting_artifact_provenance_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a declared provenance summary for one supporting artifact."""
    _validate_references(source)
    supporting_summary = source["supporting_evidence_summary"]
    artifact = _artifact_summary(source)
    source_links = source["source_links"]
    findings = _findings(supporting_summary, source["producer"], source_links)
    return {
        "artifact_provenance_policy": copy.deepcopy(source["artifact_provenance_policy"]),
        "artifact": artifact,
        "producer": copy.deepcopy(source["producer"]),
        "source_link_count": len(source_links),
        "source_type_counts": _state_counts(source_links, "source_type"),
        "source_role_counts": _state_counts(source_links, "source_role"),
        "source_state_counts": _state_counts(source_links, "source_state"),
        "classification": _classification(
            supporting_summary,
            source["producer"],
            source_links,
        ),
        "source_links": [
            _source_link_summary(artifact["artifact_id"], link) for link in source_links
        ],
        "provenance_finding_count": len(findings),
        "provenance_findings": findings,
        "attention": _attention(),
    }
