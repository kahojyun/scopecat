"""Structured summary builder for derived artifact source links.

This module validates an explicit artifact-link manifest. It does not read
artifact files, observe source measurements, calculate checksums, write
storage, infer schemas, traverse relation graphs, infer analysis DAGs, judge
scientific validity, or define GUI behavior.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "link_authority": "explicit_artifact_manifest",
    "artifact_observation": "not_performed",
    "source_observation": "not_performed",
    "storage_mutation": "not_performed",
    "checksum_validation": "not_performed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "analysis_dag_inference": "not_performed",
    "scientific_validity": "not_claimed",
    "gui_workflow": "not_defined",
    "shared_measurement_schema": "not_defined",
}

_AUTHORITY = "explicit_artifact_manifest"
_ARTIFACT_KINDS = {"analysis_summary", "fit_preview", "figure", "report"}
_ARTIFACT_STATES = {"declared_available", "unavailable", "redacted"}
_SOURCE_STATES = {"declared_available", "unavailable", "redacted", "unlinked"}
_SOURCE_ROLES = {"primary_input", "comparison_reference", "calibration_context"}
_RELATIONS = {"derived_from_measurement", "compares_against", "documents_measurement"}
_PRIMARY_DATA_REFERENCE_KEYS = {"path", "authority"}


def _path_is_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
    )


def _validate_relative_path(path: str, owner: str) -> None:
    if not _path_is_relative(path):
        raise ValueError(f"{owner} path must be relative")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["artifact_link_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("artifact link policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"artifact link policy {key} must be {expected}")


def _validate_artifact(artifact: dict[str, Any]) -> None:
    expected_keys = {
        "artifact_id",
        "label",
        "kind",
        "path",
        "authority",
        "reference_state",
        "reason",
    }
    if set(artifact) != expected_keys:
        raise ValueError("artifact must match expected shape")
    if artifact["kind"] not in _ARTIFACT_KINDS:
        raise ValueError("artifact kind is unsupported")
    if artifact["authority"] != _AUTHORITY:
        raise ValueError("artifact authority must stay explicit_artifact_manifest")
    _validate_relative_path(artifact["path"], "artifact")
    if artifact["reference_state"] not in _ARTIFACT_STATES:
        raise ValueError("artifact reference_state is unsupported")
    if artifact["reference_state"] != "declared_available" and not artifact.get("reason"):
        raise ValueError("unavailable or redacted artifact requires reason")
    if artifact["reference_state"] == "declared_available" and artifact.get("reason"):
        raise ValueError("available artifact must not carry reason")


def _validate_source_link(link: dict[str, Any]) -> None:
    expected_keys = {
        "measurement_id",
        "label",
        "source_role",
        "relation",
        "authority",
        "record_state",
        "primary_data_reference",
        "reason",
    }
    if set(link) != expected_keys:
        raise ValueError("source measurement link must match expected shape")
    if link["source_role"] not in _SOURCE_ROLES:
        raise ValueError("source_role is unsupported")
    if link["relation"] not in _RELATIONS:
        raise ValueError("source relation is unsupported")
    if link["authority"] != _AUTHORITY:
        raise ValueError("source link authority must stay explicit_artifact_manifest")
    if link["record_state"] not in _SOURCE_STATES:
        raise ValueError("source record_state is unsupported")
    if set(link["primary_data_reference"]) != _PRIMARY_DATA_REFERENCE_KEYS:
        raise ValueError("primary data reference must match expected shape")
    _validate_relative_path(link["primary_data_reference"]["path"], "primary data reference")
    if link["primary_data_reference"]["authority"] != _AUTHORITY:
        raise ValueError("primary data reference authority must stay explicit_artifact_manifest")
    if link["record_state"] != "declared_available" and not link.get("reason"):
        raise ValueError("unavailable, redacted, or unlinked source requires reason")
    if link["record_state"] == "declared_available" and link.get("reason"):
        raise ValueError("available source must not carry reason")


def _validate_source_links(source_links: list[dict[str, Any]]) -> None:
    seen = set()
    for link in source_links:
        measurement_id = link["measurement_id"]
        if measurement_id in seen:
            raise ValueError(f"duplicate measurement_id: {measurement_id}")
        seen.add(measurement_id)
        _validate_source_link(link)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_artifact(source["artifact"])
    _validate_source_links(source["source_measurements"])


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(artifact: dict[str, Any], source_links: list[dict[str, Any]]) -> str:
    if artifact["reference_state"] == "unavailable":
        return "needs_artifact_review"
    if artifact["reference_state"] == "redacted":
        return "needs_artifact_review"
    if any(link["record_state"] == "unavailable" for link in source_links):
        return "needs_source_review"
    if any(link["record_state"] in {"redacted", "unlinked"} for link in source_links):
        return "needs_link_review"
    return "ready_for_artifact_review"


def _source_link_summary(artifact: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "measurement_id": link["measurement_id"],
        "label": link["label"],
        "source_role": link["source_role"],
        "relation": link["relation"],
        "authority": link["authority"],
        "record_state": link["record_state"],
        "primary_data_reference": copy.deepcopy(link["primary_data_reference"]),
        "reason": link.get("reason"),
    }


def _findings(artifact: dict[str, Any], source_links: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    if artifact["reference_state"] != "declared_available":
        findings.append(
            {
                "artifact_id": artifact["artifact_id"],
                "subject_type": "artifact",
                "subject_id": artifact["path"],
                "severity": "review",
                "finding": f"artifact_{artifact['reference_state']}",
                "basis": artifact["reason"],
                "does_not_claim": "artifact_permanently_missing_or_invalid",
            }
        )

    for link in source_links:
        if link["record_state"] == "declared_available":
            continue
        findings.append(
            {
                "artifact_id": artifact["artifact_id"],
                "subject_type": "source_measurement",
                "subject_id": link["measurement_id"],
                "severity": "review",
                "finding": f"source_measurement_{link['record_state']}",
                "basis": link["reason"],
                "does_not_claim": "analysis_lineage_invalid_or_complete",
            }
        )
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "explicit_links_only",
            "severity": "info",
            "basis": "Derived artifact source links come from an explicit artifact manifest.",
            "does_not_claim": "complete_analysis_provenance",
        },
        {
            "code": "artifact_not_read",
            "severity": "review",
            "basis": "The artifact path is a declared reference and is not opened or parsed.",
            "does_not_claim": "artifact_contents_verified",
        },
        {
            "code": "source_measurements_not_observed",
            "severity": "review",
            "basis": "Source measurement references are not opened, checksummed, or schema-inferred.",
            "does_not_claim": "source_file_integrity_verified",
        },
        {
            "code": "analysis_dag_not_inferred",
            "severity": "review",
            "basis": "Only directly listed source measurements are summarized.",
            "does_not_claim": "recursive_analysis_dag",
        },
        {
            "code": "scientific_validity_not_claimed",
            "severity": "review",
            "basis": "Links explain declared source relationships but do not judge artifact correctness.",
            "does_not_claim": "artifact_scientifically_valid",
        },
    ]


def build_derived_artifact_source_link_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit derived-artifact links."""
    _validate_references(source)
    artifact = source["artifact"]
    source_links = source["source_measurements"]
    return {
        "artifact_link_policy": copy.deepcopy(source["artifact_link_policy"]),
        "artifact": copy.deepcopy(artifact),
        "source_measurement_count": len(source_links),
        "source_state_counts": _state_counts(source_links, "record_state"),
        "source_role_counts": _state_counts(source_links, "source_role"),
        "classification": _classification(artifact, source_links),
        "source_links": [_source_link_summary(artifact, link) for link in source_links],
        "link_findings": _findings(artifact, source_links),
        "attention": _attention(),
    }
