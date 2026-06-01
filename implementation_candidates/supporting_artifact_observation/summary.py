"""File-level observation for supporting artifact references."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import (
    relative_path_parts as _relative_parts,
)
from implementation_candidates.contract_primitives import (
    validate_non_negative_integer as _validate_nonnegative_int,
)
from implementation_candidates.contract_primitives import (
    validate_relative_path as _validate_relative_path,
)
from implementation_candidates.contract_primitives import validate_sha256_digest

_OBSERVATION_SCHEMA = "scopecat.supporting_artifact_observation.v0"

_EXPECTED_POLICY = {
    "observation_authority": "explicit_supporting_artifact_observation_request",
    "input_source": "supporting_artifact_provenance_summary",
    "artifact_root_authority": "caller_provided_artifact_root",
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
    "gui_workflow": "not_defined",
    "shared_artifact_schema": "not_defined",
}

_PROVENANCE_POLICY_REQUIREMENTS = {
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

_REQUEST_FIELDS = {
    "request_id",
    "artifact_id",
    "artifact_root_label",
    "artifact_path",
    "expected_digest",
    "expected_size_bytes",
}


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("supporting artifact observation root must not be a symlink")
    if not root.is_dir():
        raise ValueError("supporting artifact observation root must be an existing directory")
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("supporting artifact observation parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("supporting artifact observation parent is not a directory")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["artifact_observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("supporting artifact observation policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"supporting artifact observation policy {key} must be {expected}")


def _validate_provenance_summary(source: dict[str, Any]) -> None:
    summary = source["supporting_artifact_provenance_summary"]
    policy = summary["artifact_provenance_policy"]
    for key, expected in _PROVENANCE_POLICY_REQUIREMENTS.items():
        if policy[key] != expected:
            raise ValueError(f"artifact provenance policy {key} must be {expected}")
    artifact = summary["artifact"]
    reference = artifact["declared_reference"]
    if reference["reference_state"] != "declared_available":
        raise ValueError("supporting artifact observation requires declared available artifact")
    if reference["kind"] not in {"package_relative_path", "workspace_relative_path"}:
        raise ValueError("supporting artifact observation requires relative artifact reference")
    _validate_relative_path(reference["value"], "supporting artifact reference")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["observation_request"]
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("supporting artifact observation request must match expected shape")
    _validate_relative_path(request["artifact_path"], "observation request artifact_path")
    if request["expected_digest"] is not None:
        validate_sha256_digest(request["expected_digest"], "expected artifact digest")
    if request["expected_size_bytes"] is not None:
        _validate_nonnegative_int(request["expected_size_bytes"], "expected_size_bytes")

    artifact = source["supporting_artifact_provenance_summary"]["artifact"]
    reference = artifact["declared_reference"]
    if request["artifact_id"] != artifact["artifact_id"]:
        raise ValueError("observation request artifact_id must match provenance artifact")
    if request["artifact_path"] != reference["value"]:
        raise ValueError("observation request artifact_path must match provenance artifact")


def _validate_source(source: dict[str, Any]) -> None:
    if source["artifact_observation_schema"] != _OBSERVATION_SCHEMA:
        raise ValueError(f"artifact_observation_schema must be {_OBSERVATION_SCHEMA}")
    _validate_policy(source)
    _validate_provenance_summary(source)
    _validate_request(source)


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _observe(source: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    request = source["observation_request"]
    artifact_path = request["artifact_path"]
    _ensure_no_symlink_parents(artifact_root, artifact_path)
    target = _path_under(artifact_root, artifact_path)
    if target.is_symlink():
        raise ValueError("supporting artifact observation target is a symlink")
    if not target.is_file():
        return {
            "artifact_id": request["artifact_id"],
            "path": artifact_path,
            "status": "unavailable",
            "observation_level": "file_level",
            "expected_digest": request["expected_digest"],
            "observed_digest": None,
            "expected_size_bytes": request["expected_size_bytes"],
            "observed_size_bytes": None,
            "payload_import": "not_performed",
            "artifact_parsing": "not_performed",
            "preview_generation": "not_performed",
        }

    return {
        "artifact_id": request["artifact_id"],
        "path": artifact_path,
        "status": "observed",
        "observation_level": "file_level",
        "expected_digest": request["expected_digest"],
        "observed_digest": _sha256_digest(target),
        "expected_size_bytes": request["expected_size_bytes"],
        "observed_size_bytes": target.stat().st_size,
        "payload_import": "not_performed",
        "artifact_parsing": "not_performed",
        "preview_generation": "not_performed",
    }


def _finding(code: str, basis: str, does_not_claim: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "basis": basis,
        "does_not_claim": does_not_claim,
    }


def _findings(observed: dict[str, Any]) -> list[dict[str, str]]:
    if observed["status"] == "unavailable":
        return [
            _finding(
                "supporting_artifact_unavailable",
                "The referenced supporting artifact could not be observed under the caller root.",
                "artifact_invalid_or_moved_reference_discovery",
            )
        ]

    findings = []
    if (
        observed["expected_digest"] is not None
        and observed["observed_digest"] != observed["expected_digest"]
    ):
        findings.append(
            _finding(
                "supporting_artifact_digest_mismatch",
                "Observed sha256 digest differs from the declared supporting artifact digest.",
                "artifact_payload_parsing_or_cause_attribution",
            )
        )
    if (
        observed["expected_size_bytes"] is not None
        and observed["observed_size_bytes"] != observed["expected_size_bytes"]
    ):
        findings.append(
            _finding(
                "supporting_artifact_size_mismatch",
                "Observed byte size differs from the declared supporting artifact size.",
                "artifact_payload_parsing_or_cause_attribution",
            )
        )
    return findings


def _classification(observed: dict[str, Any], findings: list[dict[str, str]]) -> str:
    if observed["status"] == "unavailable":
        return "supporting_artifact_unavailable_for_review"
    if findings:
        return "supporting_artifact_observed_with_file_fact_mismatch"
    if observed["expected_digest"] is None and observed["expected_size_bytes"] is None:
        return "supporting_artifact_observed_without_declared_file_facts"
    return "supporting_artifact_observed_matches_declared_file_facts"


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "file_level_observation_only",
            "severity": "review",
            "basis": "Only file availability, sha256, and byte size are observed for the supporting artifact.",
            "does_not_claim": "artifact_payload_parsing_or_preview",
        },
        {
            "code": "source_payloads_not_observed",
            "severity": "review",
            "basis": "Artifact source links remain declared provenance; source payloads are not opened.",
            "does_not_claim": "source_payload_or_integrity_verified",
        },
        {
            "code": "artifact_not_generated",
            "severity": "review",
            "basis": "Unavailable or mismatched artifact facts remain review findings.",
            "does_not_claim": "artifact_generation_or_repair",
        },
        {
            "code": "validity_not_claimed",
            "severity": "review",
            "basis": "File-level observation does not judge artifact correctness, fit quality, or measurement validity.",
            "does_not_claim": "artifact_or_measurement_validity",
        },
    ]


def observe_supporting_artifact(
    source: dict[str, Any],
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    """Observe one supporting artifact reference under a caller-provided root."""
    _validate_source(source)
    artifact_root_resolved = _existing_root(artifact_root)
    observed = _observe(source, artifact_root_resolved)
    findings = _findings(observed)

    provenance = source["supporting_artifact_provenance_summary"]
    artifact = provenance["artifact"]
    request = source["observation_request"]
    return {
        "artifact_observation_schema": source["artifact_observation_schema"],
        "artifact_observation_policy": copy.deepcopy(source["artifact_observation_policy"]),
        "artifact": {
            "artifact_id": artifact["artifact_id"],
            "label": artifact["label"],
            "content_kind": artifact["content_kind"],
            "purpose": artifact["purpose"],
            "lifecycle_stage": artifact["lifecycle_stage"],
            "declared_reference": copy.deepcopy(artifact["declared_reference"]),
            "prior_provenance_classification": provenance["classification"],
            "classification": _classification(observed, findings),
        },
        "observation_request": {
            "request_id": request["request_id"],
            "artifact_id": request["artifact_id"],
            "artifact_root_label": request["artifact_root_label"],
            "artifact_path": request["artifact_path"],
            "expected_digest": request["expected_digest"],
            "expected_size_bytes": request["expected_size_bytes"],
        },
        "observed_artifact": observed,
        "review_findings": findings,
        "source_link_count": provenance["source_link_count"],
        "source_state_counts": copy.deepcopy(provenance["source_state_counts"]),
        "source_payload_observation": "not_performed",
        "storage_mutation": "not_performed",
        "artifact_generation": "not_performed",
        "attention": _attention(),
    }
