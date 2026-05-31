"""File-level observation for one selected legacy file-backed locator.

This module observes one explicitly selected `legacy_path` locator from a
legacy sidecar post-run review. It checks only file availability and optional
sha256/byte-size facts under a caller-provided external root. It does not
parse legacy data, verify previews, import data, query legacy backends, mutate
storage, repair references, write parameters, decide measurement validity, or
define GUI behavior.
"""

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
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
)

_OBSERVATION_SCHEMA = "scopecat.legacy_file_backed_locator_observation.v0"

_EXPECTED_POLICY = {
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

_REQUEST_FIELDS = {
    "request_id",
    "measurement_id",
    "target_id",
    "locator_id",
    "external_root_label",
    "source_path",
    "expected_digest",
    "expected_size_bytes",
}


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("legacy file-backed locator external root must not be a symlink")
    if not root.is_dir():
        raise ValueError("legacy file-backed locator external root must be an existing directory")
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("legacy file-backed locator parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("legacy file-backed locator parent is not a directory")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["locator_observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("legacy file-backed locator observation policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(
                f"legacy file-backed locator observation policy {key} must be {expected}"
            )


def _validate_post_run_review(summary: dict[str, Any]) -> None:
    policy = summary["sidecar_post_run_review_policy"]
    for key, expected in _POST_RUN_POLICY_EXPECTATIONS.items():
        if policy[key] != expected:
            raise ValueError(f"sidecar post-run review policy {key} must be {expected}")
    if not summary["source_sidecar"]["measurement_id"]:
        raise ValueError("source sidecar measurement_id is required")
    if "review_sections" not in summary:
        raise ValueError("sidecar post-run review sections are required")
    sections = summary["review_sections"]
    for section in ("lifecycle", "legacy_locators", "primary_data"):
        if section not in sections:
            raise ValueError(f"sidecar post-run review missing {section} section")
    if sections["lifecycle"]["measurement_id"] != summary["source_sidecar"]["measurement_id"]:
        raise ValueError("lifecycle measurement_id must match source sidecar")


def _validate_optional_digest(value: Any) -> str | None:
    if value is None:
        return None
    return validate_sha256_digest(value, "expected locator digest")


def _validate_optional_size(value: Any) -> int | None:
    if value is None:
        return None
    return _validate_nonnegative_int(value, "expected_size_bytes")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["observation_request"]
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("legacy file-backed locator observation request must match expected shape")
    validate_public_identifier(request["request_id"], "request_id")
    validate_public_identifier(request["measurement_id"], "measurement_id")
    validate_public_identifier(request["target_id"], "target_id")
    validate_public_identifier(request["locator_id"], "locator_id")
    validate_public_identifier(request["external_root_label"], "external_root_label")
    validate_relative_path(request["source_path"], "observation request source_path")
    _validate_optional_digest(request["expected_digest"])
    _validate_optional_size(request["expected_size_bytes"])


def _locator_targets(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return summary["review_sections"]["legacy_locators"]["targets"]


def _selected_target_and_locator(
    summary: dict[str, Any], request: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    measurement_id = summary["source_sidecar"]["measurement_id"]
    if request["measurement_id"] != measurement_id:
        raise ValueError("observation request measurement_id must match source sidecar")

    for target in _locator_targets(summary):
        if target["target_id"] != request["target_id"]:
            continue
        for locator in target["locators"]:
            if locator["locator_id"] == request["locator_id"]:
                return target, locator
        raise ValueError("observation request locator_id must match a locator on target")
    raise ValueError("observation request target_id must match a locator target")


def _validate_selected_locator(target: dict[str, Any], locator: dict[str, Any]) -> None:
    if locator["kind"] != "legacy_path":
        raise ValueError("legacy file-backed locator observation requires a legacy_path locator")
    if locator["reference_state"] != "declared_available":
        raise ValueError("legacy file-backed locator must be declared_available")
    if locator.get("redacted") is not True:
        raise ValueError("legacy_path locator display must stay redacted")
    if target["classification"] == "locator_unavailable_for_review":
        raise ValueError("legacy file-backed locator target must not be unavailable for review")


def _validate_source(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if source["locator_observation_schema"] != _OBSERVATION_SCHEMA:
        raise ValueError(f"locator_observation_schema must be {_OBSERVATION_SCHEMA}")
    _validate_policy(source)
    _validate_request(source)
    summary = source["legacy_sidecar_post_run_review_summary"]
    _validate_post_run_review(summary)
    target, locator = _selected_target_and_locator(summary, source["observation_request"])
    _validate_selected_locator(target, locator)
    return target, locator


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _observe(request: dict[str, Any], external_root: Path) -> dict[str, Any]:
    source_path = request["source_path"]
    _ensure_no_symlink_parents(external_root, source_path)
    target = _path_under(external_root, source_path)
    if target.is_symlink():
        raise ValueError("legacy file-backed locator target is a symlink")
    if not target.is_file():
        return {
            "locator_id": request["locator_id"],
            "path": source_path,
            "status": "unavailable",
            "observation_level": "file_level",
            "expected_digest": request["expected_digest"],
            "observed_digest": None,
            "expected_size_bytes": request["expected_size_bytes"],
            "observed_size_bytes": None,
            "data_observation": "not_performed",
            "preview_verification": "not_performed",
        }

    return {
        "locator_id": request["locator_id"],
        "path": source_path,
        "status": "observed",
        "observation_level": "file_level",
        "expected_digest": request["expected_digest"],
        "observed_digest": _sha256_digest(target),
        "expected_size_bytes": request["expected_size_bytes"],
        "observed_size_bytes": target.stat().st_size,
        "data_observation": "not_performed",
        "preview_verification": "not_performed",
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
                "legacy_locator_source_unavailable",
                "The selected legacy_path locator could not be observed under the caller root.",
                "reference_repair_or_moved_reference_discovery",
            )
        ]

    findings = []
    if (
        observed["expected_digest"] is not None
        and observed["observed_digest"] != observed["expected_digest"]
    ):
        findings.append(
            _finding(
                "legacy_locator_source_digest_mismatch",
                "Observed sha256 digest differs from the declared legacy locator digest.",
                "cause_attribution_or_data_parsing",
            )
        )
    if (
        observed["expected_size_bytes"] is not None
        and observed["observed_size_bytes"] != observed["expected_size_bytes"]
    ):
        findings.append(
            _finding(
                "legacy_locator_source_size_mismatch",
                "Observed byte size differs from the declared legacy locator size.",
                "cause_attribution_or_data_parsing",
            )
        )
    return findings


def _classification(observed: dict[str, Any], findings: list[dict[str, str]]) -> str:
    if observed["status"] == "unavailable":
        return "legacy_file_backed_locator_unavailable_for_review"
    if findings:
        return "legacy_file_backed_locator_observed_with_file_fact_mismatch"
    return "legacy_file_backed_locator_observed"


def _declared_preview_assertion(summary: dict[str, Any], target_id: str) -> dict[str, Any] | None:
    primary_refs = summary["review_sections"]["primary_data"]["primary_data_refs"]
    for ref in primary_refs:
        if ref["data_id"] == target_id and "declared_preview" in ref:
            return {
                "data_id": ref["data_id"],
                "status": ref["declared_preview"]["status"],
                "basis": ref["declared_preview"]["basis"],
                "verification_state": "not_verified_by_file_level_observation",
                "does_not_claim": "previewability_or_schema_validation",
            }
    return None


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "file_level_locator_observation_only",
            "severity": "review",
            "basis": "Only file availability, sha256, and byte size are observed for the selected legacy_path locator.",
            "does_not_claim": "row_count_schema_preview_or_data_validation",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "The selected locator may point at a legacy-formatted file; Scopecat does not parse it in this slice.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "reference_repair_not_performed",
            "severity": "review",
            "basis": "Unavailable or mismatched file facts remain review findings.",
            "does_not_claim": "moved_reference_discovery_or_repair",
        },
        {
            "code": "storage_mutation_not_performed",
            "severity": "review",
            "basis": "The observer does not copy, import, write, or organize the legacy source.",
            "does_not_claim": "storage_acceptance_or_materialization",
        },
    ]


def observe_legacy_file_backed_locator(
    source: dict[str, Any], *, external_root: Path
) -> dict[str, Any]:
    """Observe one selected legacy_path locator under a caller-provided root."""
    target, locator = _validate_source(source)
    request = source["observation_request"]
    summary = source["legacy_sidecar_post_run_review_summary"]
    external_root_resolved = _existing_root(external_root)
    observed = _observe(request, external_root_resolved)
    findings = _findings(observed)
    return {
        "locator_observation_schema": source["locator_observation_schema"],
        "locator_observation_policy": copy.deepcopy(source["locator_observation_policy"]),
        "classification": _classification(observed, findings),
        "source_review": {
            "measurement_id": summary["source_sidecar"]["measurement_id"],
            "post_run_classification": summary["classification"],
            "locator_review_classification": summary["source_sidecar"][
                "locator_review_classification"
            ],
        },
        "selected_locator": {
            "target_type": target["target_type"],
            "target_id": target["target_id"],
            "target_label": target["label"],
            "target_classification": target["classification"],
            "locator_id": locator["locator_id"],
            "kind": locator["kind"],
            "display": locator["display"],
            "authority": locator["authority"],
            "reference_state": locator["reference_state"],
            "redacted": locator["redacted"],
        },
        "observation_request": copy.deepcopy(request),
        "observed_legacy_source": observed,
        "review_findings": findings,
        "declared_preview_assertion": _declared_preview_assertion(summary, target["target_id"]),
        "observation_effects": {
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
        },
        "attention": _attention(),
    }
