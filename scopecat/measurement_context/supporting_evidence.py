"""Reference-only supporting evidence engineering prototype.

This module summarizes explicit supporting-evidence references only. It does
not open files, import payloads, calculate checksums, write storage, generate
previews, traverse relation graphs, decide measurement validity, validate
artifact provenance, or define GUI behavior.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

SUPPORTING_EVIDENCE_POLICY = {
    "reference_authority": "explicit_supporting_evidence_manifest",
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
    "external_file_authority": "not_claimed",
    "recursive_relation_traversal": "not_performed",
    "measurement_validity": "not_claimed",
    "portable_public_export": "not_declared",
    "gui_workflow": "not_defined",
    "shared_attachment_schema": "not_defined",
}

AUTHORITY = "explicit_supporting_evidence_manifest"
EVIDENCE_KINDS = {"attachment", "artifact", "unspecified"}
CONTENT_KINDS = {
    "adapter_diagnostic",
    "debug_log",
    "operator_note",
    "compatibility_file",
    "review_bundle",
}
PURPOSES = {"debug", "audit", "handoff", "review_evidence"}
LIFECYCLE_STAGES = {"pre_run_preparation", "during_run", "post_run_review", "handoff"}
REFERENCE_KINDS = {"workspace_relative_path", "package_relative_path", "opaque_uri"}
REFERENCE_STATES = {"declared_available", "unavailable", "redacted"}
TARGET_TYPES = {
    "measurement",
    "prepared_run",
    "operator_approval",
    "parameter_state",
    "calibration_step",
    "running_measurement",
}
TARGET_STATES = {"resolved", "unavailable", "missing", "redacted"}
RELATIONS = {
    "associated_with",
    "debugs_preparation",
    "documents_decision",
    "supports_handoff",
    "supports_review_of",
}

_PRIVATE_TOKEN_MARKERS = {"users", "private"}


@dataclass(frozen=True, init=False)
class SupportingEvidenceReferenceRequest:
    """Typed local request for explicit supporting-evidence references."""

    _source: dict[str, Any] = field(repr=False)

    def __init__(self, *, source: dict[str, Any]) -> None:
        _validate_references(source)
        object.__setattr__(self, "_source", copy.deepcopy(source))

    @classmethod
    def from_dict(cls, source: dict[str, Any]) -> SupportingEvidenceReferenceRequest:
        return cls(source=source)

    @property
    def source(self) -> dict[str, Any]:
        return copy.deepcopy(self._source)


@dataclass(frozen=True, init=False)
class SupportingEvidenceReferenceResult:
    """Route-local supporting-evidence reference summary projection."""

    _summary: dict[str, Any] = field(repr=False)

    def __init__(self, *, summary: dict[str, Any]) -> None:
        object.__setattr__(self, "_summary", copy.deepcopy(summary))

    @property
    def classification(self) -> str:
        return str(self._summary["classification"])

    @property
    def supporting_links(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["supporting_links"])

    @property
    def reference_findings(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["reference_findings"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def summarize_supporting_evidence_reference(
    request: SupportingEvidenceReferenceRequest,
) -> SupportingEvidenceReferenceResult:
    """Summarize explicit supporting-evidence references."""

    source = request.source
    evidence = source["evidence"]
    targets = source["related_targets"]
    summary = {
        "supporting_evidence_policy": copy.deepcopy(source["supporting_evidence_policy"]),
        "evidence": copy.deepcopy(evidence),
        "related_target_count": len(targets),
        "target_type_counts": _state_counts(targets, "target_type"),
        "target_state_counts": _state_counts(targets, "target_state"),
        "classification": _classification(evidence, targets),
        "supporting_links": [_supporting_link_summary(evidence, target) for target in targets],
        "reference_findings": _findings(evidence, targets),
        "attention": _attention(),
    }
    return SupportingEvidenceReferenceResult(summary=summary)


def build_supporting_evidence_reference_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Raw-dictionary adapter for explicit supporting-evidence references."""

    request = SupportingEvidenceReferenceRequest.from_dict(source)
    return summarize_supporting_evidence_reference(request).to_dict()


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


def _validate_public_safe_token(value: str, owner: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "\\" in value
        or value.startswith("~")
        or re.match(r"^[A-Za-z]:", value)
        or any(part.lower() in _PRIVATE_TOKEN_MARKERS for part in PurePosixPath(value).parts)
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_declared_reference(reference: dict[str, Any]) -> None:
    expected_keys = {"kind", "value", "authority", "reference_state", "reason"}
    if set(reference) != expected_keys:
        raise ValueError("evidence declared reference must match expected shape")
    if reference["kind"] not in REFERENCE_KINDS:
        raise ValueError("evidence reference kind is unsupported")
    if reference["authority"] != AUTHORITY:
        raise ValueError("evidence reference authority must stay explicit")
    if reference["reference_state"] not in REFERENCE_STATES:
        raise ValueError("evidence reference_state is unsupported")

    value = reference["value"]
    if reference["kind"] in {"workspace_relative_path", "package_relative_path"}:
        if not _path_is_relative(value):
            raise ValueError("evidence reference path must be relative")
    elif not value:
        raise ValueError("evidence opaque reference must be non-empty")

    if reference["reference_state"] != "declared_available" and not reference.get("reason"):
        raise ValueError("unavailable or redacted evidence reference requires reason")
    if reference["reference_state"] == "declared_available" and reference.get("reason"):
        raise ValueError("available evidence reference must not carry reason")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["supporting_evidence_policy"]
    if set(policy) != set(SUPPORTING_EVIDENCE_POLICY):
        raise ValueError("supporting evidence policy must match expected shape")
    for key, expected in SUPPORTING_EVIDENCE_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"supporting evidence policy {key} must be {expected}")


def _validate_evidence(evidence: dict[str, Any]) -> None:
    expected_keys = {
        "evidence_id",
        "label",
        "evidence_kind",
        "content_kind",
        "purpose",
        "lifecycle_stage",
        "supplied_by",
        "declared_reference",
        "notes",
    }
    if set(evidence) != expected_keys:
        raise ValueError("supporting evidence must match expected shape")
    _validate_public_safe_token(evidence["evidence_id"], "supporting evidence id")
    if evidence["evidence_kind"] not in EVIDENCE_KINDS:
        raise ValueError("supporting evidence evidence_kind is unsupported")
    if evidence["content_kind"] not in CONTENT_KINDS:
        raise ValueError("supporting evidence content_kind is unsupported")
    if evidence["purpose"] not in PURPOSES:
        raise ValueError("supporting evidence purpose is unsupported")
    if evidence["lifecycle_stage"] not in LIFECYCLE_STAGES:
        raise ValueError("supporting evidence lifecycle_stage is unsupported")
    if evidence["supplied_by"] != "user_supplied":
        raise ValueError("supporting evidence must remain user supplied")
    _validate_declared_reference(evidence["declared_reference"])


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
        raise ValueError("supporting evidence target must match expected shape")
    if target["target_type"] not in TARGET_TYPES:
        raise ValueError("supporting evidence target_type is unsupported")
    _validate_public_safe_token(target["target_id"], "supporting evidence target id")
    if target["relation"] not in RELATIONS:
        raise ValueError("supporting evidence relation is unsupported")
    if target["authority"] != AUTHORITY:
        raise ValueError("supporting evidence target authority must stay explicit")
    if target["target_state"] not in TARGET_STATES:
        raise ValueError("supporting evidence target_state is unsupported")
    if target["target_state"] != "resolved" and not target.get("reason"):
        raise ValueError("unavailable, missing, or redacted target requires reason")
    if target["target_state"] == "resolved" and target.get("reason"):
        raise ValueError("resolved target must not carry reason")


def _validate_targets(targets: list[dict[str, Any]]) -> None:
    seen = set()
    for target in targets:
        key = (target["target_type"], target["target_id"], target["relation"])
        if key in seen:
            raise ValueError(f"duplicate supporting evidence target: {target['target_id']}")
        seen.add(key)
        _validate_target(target)


def _validate_references(source: dict[str, Any]) -> None:
    _validate_policy(source)
    _validate_evidence(source["evidence"])
    _validate_targets(source["related_targets"])
    if "payload" in source["evidence"]:
        raise ValueError("supporting evidence payload must not be supplied")
    if "provenance" in source["evidence"]:
        raise ValueError("supporting evidence provenance must use a separate slice")


def _state_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        state = item[key]
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _classification(evidence: dict[str, Any], targets: list[dict[str, Any]]) -> str:
    if evidence["declared_reference"]["reference_state"] != "declared_available":
        return "needs_evidence_reference_review"
    if any(target["target_state"] != "resolved" for target in targets):
        return "needs_related_target_review"
    return "ready_for_supporting_evidence_review"


def _supporting_link_summary(
    evidence: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_id": evidence["evidence_id"],
        "evidence_kind": evidence["evidence_kind"],
        "evidence_purpose": evidence["purpose"],
        "evidence_lifecycle_stage": evidence["lifecycle_stage"],
        "target_type": target["target_type"],
        "target_id": target["target_id"],
        "label": target["label"],
        "relation": target["relation"],
        "authority": target["authority"],
        "target_state": target["target_state"],
        "reason": target.get("reason"),
    }


def _findings(evidence: dict[str, Any], targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = []
    reference = evidence["declared_reference"]
    if reference["reference_state"] != "declared_available":
        findings.append(
            {
                "evidence_id": evidence["evidence_id"],
                "subject_type": "supporting_evidence",
                "subject_id": reference["value"],
                "severity": "review",
                "finding": f"evidence_reference_{reference['reference_state']}",
                "basis": reference["reason"],
                "does_not_claim": "evidence_payload_missing_or_invalid",
            }
        )

    for target in targets:
        if target["target_state"] == "resolved":
            continue
        findings.append(
            {
                "evidence_id": evidence["evidence_id"],
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
            "basis": "Supporting evidence comes from an explicit user-supplied manifest.",
            "does_not_claim": "automatic_evidence_discovery",
        },
        {
            "code": "evidence_kind_is_label_only",
            "severity": "info",
            "basis": (
                "Attachment or artifact kind labels do not create attachment payload or "
                "artifact provenance semantics."
            ),
            "does_not_claim": "artifact_provenance_complete",
        },
        {
            "code": "evidence_lifecycle_is_explicit",
            "severity": "info",
            "basis": (
                "Supporting evidence declares whether it belongs to pre-run preparation, "
                "during-run evidence, post-run review, or handoff."
            ),
            "does_not_claim": "run_start_context_requirement",
        },
        {
            "code": "evidence_not_canonical_context",
            "severity": "review",
            "basis": "The evidence supports review but does not replace selected context records.",
            "does_not_claim": "parameter_or_measurement_context_authority",
        },
        {
            "code": "payload_not_imported",
            "severity": "review",
            "basis": "The evidence payload is not imported, copied, parsed, or normalized.",
            "does_not_claim": "evidence_contents_verified",
        },
        {
            "code": "file_not_observed",
            "severity": "review",
            "basis": "Declared evidence references are not opened, checksummed, or statted.",
            "does_not_claim": "external_file_authority",
        },
        {
            "code": "measurement_validity_not_claimed",
            "severity": "review",
            "basis": "Supporting evidence does not decide primary measurement-record validity.",
            "does_not_claim": "measurement_validity",
        },
    ]
