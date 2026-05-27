"""File-level observation for reference-only legacy source references.

This module observes one explicitly declared external source reference from
reviewed reference-only legacy import facts. It checks only file availability,
sha256, and byte size under a caller-provided external root. It does not parse
legacy formats, count rows, verify preview metadata, copy data, mutate storage,
repair references, or define GUI behavior.
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
    validate_relative_path as _validate_relative_path,
)
from implementation_candidates.contract_primitives import validate_sha256_digest

_OBSERVATION_SCHEMA = "scopecat.reference_only_source_observation.v0"

_EXPECTED_POLICY = {
    "observation_authority": "explicit_file_level_observation_request",
    "input_authority": "reference_only_legacy_import_facts",
    "external_root_authority": "caller_provided_external_root",
    "source_observation": "file_level_only",
    "checksum_algorithm": "sha256",
    "data_observation": "not_performed",
    "row_count": "not_performed",
    "schema_inference": "not_performed",
    "preview_verification": "not_performed",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "storage_mutation": "not_performed",
    "copy_behavior": "not_performed",
    "reference_repair": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
}

_REQUEST_FIELDS = {
    "request_id",
    "reference_id",
    "external_root_label",
    "source_path",
    "expected_digest",
    "expected_size_bytes",
}


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_relative_parts(relative_path))


def _existing_root(root: Path) -> Path:
    if root.is_symlink():
        raise ValueError("reference-only source observation external root must not be a symlink")
    if not root.is_dir():
        raise ValueError(
            "reference-only source observation external root must be an existing directory"
        )
    return root.resolve()


def _ensure_no_symlink_parents(root: Path, relative_path: str) -> None:
    current = root
    for part in _relative_parts(relative_path)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("reference-only source observation parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("reference-only source observation parent is not a directory")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["source_observation_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("expected reference-only source observation policy shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"reference-only source observation policy {key} must be {expected}")


def _validate_import_facts(facts: dict[str, Any]) -> None:
    if facts["adapter_manifest_classification"] != "adapter_manifest_ready_for_review":
        raise ValueError("reference-only source observation requires ready adapter manifest facts")
    if facts["measurement_record"]["classification"] != "reference_only_import_ready_for_review":
        raise ValueError("reference-only source observation requires ready reference facts")
    request = facts["reference_only_request"]
    if request["approval_state"] != "approved":
        raise ValueError("reference-only source observation requires approved reference facts")
    if request["reviewed_manifest_classification"] != facts["adapter_manifest_classification"]:
        raise ValueError(
            "reference-only source observation reviewed classification must match adapter facts"
        )
    expected_materialization = {
        "primary_data": "external_reference_only",
        "linked_context": "reference_only",
        "source_identity": "preserve_external_reference",
    }
    if request["materialization"] != expected_materialization:
        raise ValueError(
            "reference-only source observation requires reference-only materialization"
        )
    if facts["storage_mutation"] != "not_performed":
        raise ValueError(
            "reference-only source observation requires storage_mutation not_performed"
        )
    if facts["copy_result"] != "not_copied":
        raise ValueError("reference-only source observation requires copy_result not_copied")

    reference = facts["current_primary_data_reference"]
    if reference["authority"] != "adapter_declared":
        raise ValueError("current reference authority must remain adapter_declared")
    if reference["reference_state"] != "adapter_declared_available":
        raise ValueError("current reference_state must remain adapter_declared_available")
    if reference["openability"] != "not_checked":
        raise ValueError("current reference must not have prior openability checks")
    if reference["verification_state"] != "unobserved":
        raise ValueError("current reference verification_state must remain unobserved")
    if reference["digest"] is not None or reference["size_bytes"] is not None:
        raise ValueError("current reference must not carry prior file observation facts")


def _validate_request(source: dict[str, Any]) -> None:
    request = source["observation_request"]
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("reference-only source observation request must match expected shape")
    _validate_relative_path(request["source_path"], "observation request source_path")
    validate_sha256_digest(request["expected_digest"], "expected source digest")
    _validate_nonnegative_int(request["expected_size_bytes"], "expected_size_bytes")

    reference = source["reference_only_import_facts"]["current_primary_data_reference"]
    if request["reference_id"] != reference["reference_id"]:
        raise ValueError("observation request reference_id must match current reference")
    if request["external_root_label"] != reference["external_root_label"]:
        raise ValueError("observation request external_root_label must match current reference")
    if request["source_path"] != reference["adapter_primary_data_path"]:
        raise ValueError("observation request source_path must match current reference path")


def _validate_source(source: dict[str, Any]) -> None:
    if source["source_observation_schema"] != _OBSERVATION_SCHEMA:
        raise ValueError(f"source_observation_schema must be {_OBSERVATION_SCHEMA}")
    _validate_policy(source)
    _validate_import_facts(source["reference_only_import_facts"])
    _validate_request(source)


def _sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _observe(source: dict[str, Any], external_root: Path) -> dict[str, Any]:
    request = source["observation_request"]
    source_path = request["source_path"]
    _ensure_no_symlink_parents(external_root, source_path)
    target = _path_under(external_root, source_path)
    if target.is_symlink():
        raise ValueError("reference-only source observation target is a symlink")
    if not target.is_file():
        return {
            "reference_id": request["reference_id"],
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
        "reference_id": request["reference_id"],
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
                "external_source_unavailable",
                "The referenced external source file could not be observed under the caller root.",
                "repair_or_moved_reference_discovery",
            )
        ]

    findings = []
    if observed["observed_digest"] != observed["expected_digest"]:
        findings.append(
            _finding(
                "external_source_digest_mismatch",
                "Observed sha256 digest differs from the declared external source digest.",
                "cause_attribution_or_data_parsing",
            )
        )
    if observed["observed_size_bytes"] != observed["expected_size_bytes"]:
        findings.append(
            _finding(
                "external_source_size_mismatch",
                "Observed byte size differs from the declared external source size.",
                "cause_attribution_or_data_parsing",
            )
        )
    return findings


def _classification(observed: dict[str, Any], findings: list[dict[str, str]]) -> str:
    if observed["status"] == "unavailable":
        return "external_source_unavailable_for_review"
    if findings:
        return "external_source_observed_with_file_fact_mismatch"
    return "external_source_observed_matches_declared_file_facts"


def _preview_assertion(summary: dict[str, Any]) -> dict[str, Any]:
    preview = summary["preview"]
    return {
        "status": preview["status"],
        "metadata_authority": preview["metadata_authority"],
        "verification_state": "not_verified_by_file_level_observation",
        "shape_kind": preview["shape_kind"],
        "axis_order": list(preview["axis_order"]),
        "declared_row_count": preview["declared_row_count"],
        "plot_candidates": copy.deepcopy(preview["plot_candidates"]),
        "does_not_claim": "previewability_or_schema_validation",
    }


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "file_level_observation_only",
            "severity": "review",
            "basis": "Only file availability, sha256, and byte size are observed for the external source reference.",
            "does_not_claim": "row_count_schema_or_preview_validation",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "The external source may be legacy-formatted; Scopecat does not parse it in this slice.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "reference_repair_not_performed",
            "severity": "review",
            "basis": "Unavailable or mismatched source facts remain review findings.",
            "does_not_claim": "moved_reference_discovery_or_repair",
        },
        {
            "code": "storage_mutation_not_performed",
            "severity": "review",
            "basis": "The observer does not copy, import, write, or organize the external source.",
            "does_not_claim": "storage_acceptance_or_materialization",
        },
    ]


def observe_reference_only_source(source: dict[str, Any], *, external_root: Path) -> dict[str, Any]:
    """Observe one file-level external source reference under a caller root."""
    _validate_source(source)
    external_root_resolved = _existing_root(external_root)
    observed = _observe(source, external_root_resolved)
    findings = _findings(observed)

    reference_facts = source["reference_only_import_facts"]
    reference = reference_facts["current_primary_data_reference"]
    request = source["observation_request"]
    measurement = reference_facts["measurement_record"]
    return {
        "source_observation_schema": source["source_observation_schema"],
        "source_observation_policy": copy.deepcopy(source["source_observation_policy"]),
        "measurement_record": {
            "measurement_record_id": measurement["measurement_record_id"],
            "label": measurement["label"],
            "experiment_type": measurement["experiment_type"],
            "source_kind": "reference_only_external_source",
            "classification": _classification(observed, findings),
        },
        "reference_only_import": {
            "request_id": reference_facts["reference_only_request"]["request_id"],
            "adapter_manifest_classification": reference_facts["adapter_manifest_classification"],
            "copy_result": reference_facts["copy_result"],
            "storage_mutation": reference_facts["storage_mutation"],
        },
        "external_source_reference": {
            "reference_id": reference["reference_id"],
            "reference_kind": reference["reference_kind"],
            "external_root_label": reference["external_root_label"],
            "display_path": reference["display_path"],
            "adapter_primary_data_path": reference["adapter_primary_data_path"],
            "authority": reference["authority"],
            "prior_verification_state": reference["verification_state"],
        },
        "observation_request": {
            "request_id": request["request_id"],
            "reference_id": request["reference_id"],
            "external_root_label": request["external_root_label"],
            "source_path": request["source_path"],
            "expected_digest": request["expected_digest"],
            "expected_size_bytes": request["expected_size_bytes"],
        },
        "observed_external_source": observed,
        "review_findings": findings,
        "declared_preview_assertion": _preview_assertion(reference_facts),
        "storage_mutation": "not_performed",
        "copy_result": "not_copied",
        "attention": _attention(),
    }
