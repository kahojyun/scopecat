"""Structured summary builder for reference-only supporting artifacts.

This module validates explicit supporting-artifact references. It does not
open artifact files, import payloads, calculate checksums, write storage,
generate previews, traverse relation graphs, decide measurement validity, or
define GUI behavior.
"""

from __future__ import annotations

import copy
import re
from pathlib import PurePosixPath
from typing import Any

_EXPECTED_POLICY = {
    "reference_authority": "explicit_supporting_artifact_manifest",
    "artifact_posture": "supporting_artifact_reference",
    "artifact_context_role": "supporting_evidence_not_canonical_context",
    "payload_import": "not_performed",
    "file_observation": "not_performed",
    "artifact_parsing": "not_performed",
    "checksum_validation": "not_performed",
    "storage_mutation": "not_performed",
    "preview_generation": "not_performed",
    "external_file_authority": "not_claimed",
    "recursive_relation_traversal": "not_performed",
    "measurement_validity": "not_claimed",
    "portable_public_export": "not_declared",
    "gui_workflow": "not_defined",
    "shared_attachment_schema": "not_defined",
}

_AUTHORITY = "explicit_supporting_artifact_manifest"
_ARTIFACT_KINDS = {
    "adapter_diagnostic",
    "debug_log",
    "operator_note",
    "compatibility_file",
    "review_bundle",
}
_PURPOSES = {"debug", "audit", "handoff", "review_evidence"}
_REFERENCE_KINDS = {"workspace_relative_path", "package_relative_path", "opaque_uri"}
_REFERENCE_STATES = {"declared_available", "unavailable", "redacted"}
_TARGET_TYPES = {
    "measurement",
    "prepared_run",
    "operator_approval",
    "parameter_state",
    "calibration_step",
}
_TARGET_STATES = {"resolved", "unavailable", "missing", "redacted"}
_RELATIONS = {
    "associated_with",
    "debugs_preparation",
    "documents_decision",
    "supports_handoff",
    "supports_review_of",
}


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


def _validate_declared_reference(reference: dict[str, Any]) -> None:
    expected_keys = {"kind", "value", "authority", "reference_state", "reason"}
    if set(reference) != expected_keys:
        raise ValueError("artifact declared reference must match expected shape")
    if reference["kind"] not in _REFERENCE_KINDS:
        raise ValueError("artifact reference kind is unsupported")
    if reference["authority"] != _AUTHORITY:
        raise ValueError("artifact reference authority must stay explicit")
    if reference["reference_state"] not in _REFERENCE_STATES:
        raise ValueError("artifact reference_state is unsupported")

    value = reference["value"]
    if reference["kind"] in {"workspace_relative_path", "package_relative_path"}:
        if not _path_is_relative(value):
            raise ValueError("artifact reference path must be relative")
    elif not value:
        raise ValueError("artifact opaque reference must be non-empty")

    if reference["reference_state"] != "declared_available" and not reference.get("reason"):
        raise ValueError("unavailable or redacted artifact reference requires reason")
    if reference["reference_state"] == "declared_available" and reference.get("reason"):
        raise ValueError("available artifact reference must not carry reason")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["supporting_artifact_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("supporting artifact policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"supporting artifact policy {key} must be {expected}")


def _validate_artifact(artifact: dict[str, Any]) -> None:
    expected_keys = {
        "artifact_id",
        "label",
        "kind",
        "purpose",
        "supplied_by",
        "declared_reference",
        "notes",
    }
    if set(artifact) != expected_keys:
        raise ValueError("supporting artifact must match expected shape")
    if artifact["kind"] not in _ARTIFACT_KINDS:
        raise ValueError("supporting artifact kind is unsupported")
    if artifact["purpose"] not in _PURPOSES:
        raise ValueError("supporting artifact purpose is unsupported")
    if artifact["supplied_by"] != "user_supplied":
        raise ValueError("supporting artifact must remain user supplied")
    _validate_declared_reference(artifact["declared_reference"])


def _validate_target(target: dict[str, Any]) -> None:
    expected_keys = {
        "target_type",
        "target_id",
        "label",
        "relation",
        "authority",
        "target_state",
        "reason",
    }
    if set(target) != expected_keys:
        raise ValueError("supporting artifact target must match expected shape")
    if target["target_type"] not in _TARGET_TYPES:
        raise ValueError("supporting artifact target_type is unsupported")
    if not target["target_id"]:
        raise ValueError("supporting artifact target_id must be non-empty")
    if target["relation"] not in _RELATIONS:
        raise ValueError("supporting artifact relation is unsupported")
    if target["authority"] != _AUTHORITY:
        raise ValueError("supporting artifact target authority must stay explicit")
    if target["target_state"] not in _TARGET_STATES:
        raise ValueError("supporting artifact target_state is unsupported")
    if target["target_state"] != "resolved" and not target.get("reason"):
        raise ValueError("unavailable, missing, or redacted target requires reason")
    if target["target_state"] == "resolved" and target.get("reason"):
        raise ValueError("resolved target must not carry reason")


def _validate_targets(targets: list[dict[str, Any]]) -> None:
    seen = set()
    for target in targets:
        key = (target["target_type"], target["target_id"], target["relation"])
        if key in seen:
            raise ValueError(f"duplicate supporting artifact target: {target['target_id']}")
        seen.add(key)
        _validate_target(target)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_artifact(source["artifact"])
    _validate_targets(source["related_targets"])
    if "payload" in source["artifact"]:
        raise ValueError("supporting artifact payload must not be supplied")


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(artifact: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    if artifact["declared_reference"]["reference_state"] != "declared_available":
        return "needs_artifact_reference_review"
    if any(target["target_state"] != "resolved" for target in targets):
        return "needs_related_target_review"
    return "ready_for_supporting_artifact_review"


def _supporting_link_summary(
    artifact: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_purpose": artifact["purpose"],
        "target_type": target["target_type"],
        "target_id": target["target_id"],
        "label": target["label"],
        "relation": target["relation"],
        "authority": target["authority"],
        "target_state": target["target_state"],
        "reason": target.get("reason"),
    }


def _findings(artifact: dict[str, Any], targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    reference = artifact["declared_reference"]
    if reference["reference_state"] != "declared_available":
        findings.append(
            {
                "artifact_id": artifact["artifact_id"],
                "subject_type": "supporting_artifact",
                "subject_id": reference["value"],
                "severity": "review",
                "finding": f"artifact_reference_{reference['reference_state']}",
                "basis": reference["reason"],
                "does_not_claim": "artifact_payload_missing_or_invalid",
            }
        )

    for target in targets:
        if target["target_state"] == "resolved":
            continue
        findings.append(
            {
                "artifact_id": artifact["artifact_id"],
                "subject_type": target["target_type"],
                "subject_id": target["target_id"],
                "severity": "review",
                "finding": f"related_target_{target['target_state']}",
                "basis": target["reason"],
                "does_not_claim": "measurement_or_context_invalid",
            }
        )
    return findings


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "explicit_supporting_reference_only",
            "severity": "info",
            "basis": "Supporting artifacts come from an explicit user-supplied manifest.",
            "does_not_claim": "automatic_artifact_discovery",
        },
        {
            "code": "artifact_not_canonical_context",
            "severity": "review",
            "basis": "The artifact supports review but does not replace selected context records.",
            "does_not_claim": "parameter_or_measurement_context_authority",
        },
        {
            "code": "payload_not_imported",
            "severity": "review",
            "basis": "The artifact payload is not imported, copied, parsed, or normalized.",
            "does_not_claim": "artifact_contents_verified",
        },
        {
            "code": "file_not_observed",
            "severity": "review",
            "basis": "Declared artifact references are not opened, checksummed, or statted.",
            "does_not_claim": "external_file_authority",
        },
        {
            "code": "measurement_validity_not_claimed",
            "severity": "review",
            "basis": "Supporting evidence does not decide primary measurement-record validity.",
            "does_not_claim": "measurement_validity",
        },
    ]


def build_supporting_artifact_reference_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary from explicit supporting-artifact references."""
    _validate_references(source)
    artifact = source["artifact"]
    targets = source["related_targets"]
    return {
        "supporting_artifact_policy": copy.deepcopy(source["supporting_artifact_policy"]),
        "artifact": copy.deepcopy(artifact),
        "related_target_count": len(targets),
        "target_type_counts": _state_counts(targets, "target_type"),
        "target_state_counts": _state_counts(targets, "target_state"),
        "classification": _classification(artifact, targets),
        "supporting_links": [_supporting_link_summary(artifact, target) for target in targets],
        "reference_findings": _findings(artifact, targets),
        "attention": _attention(),
    }
