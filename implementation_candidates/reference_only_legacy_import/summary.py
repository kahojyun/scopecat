"""Reference-only acceptance summary for adapter-authored legacy imports.

This module validates an approved reference-only acceptance request for a
normalized adapter manifest. It preserves a lab-managed external primary-data
reference without copying files, reading source data, writing storage, parsing
legacy formats, inferring schemas, importing linked context payloads, or
defining a stable public API.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from implementation_candidates.adapter_authored_legacy_import import (
    build_adapter_authored_legacy_import_summary,
)

_REFERENCE_ONLY_SCHEMA = "scopecat.reference_only_legacy_import.v0"

_EXPECTED_POLICY = {
    "acceptance_authority": "approved_reference_only_import_request",
    "manifest_authority": "adapter_authored",
    "legacy_source_parsing": "not_performed_by_scopecat",
    "source_observation": "not_performed",
    "storage_mutation": "not_performed",
    "copy_behavior": "not_performed",
    "primary_data_materialization": "external_reference_only",
    "current_reference_authority": "adapter_declared",
    "openability_check": "not_performed",
    "checksum_verification": "not_performed",
    "linked_context_materialization": "reference_only",
    "schema_inference": "not_performed",
    "package_acceptance": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}

_REFERENCE_KIND = "lab_managed_shared_storage"
_CURRENT_REFERENCE_FIELDS = {
    "reference_id",
    "reference_kind",
    "external_root_label",
    "display_path",
    "adapter_primary_data_path",
    "authority",
    "reference_state",
    "openability",
    "verification_state",
    "digest",
    "size_bytes",
    "reason",
}
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in ("users", "private", "home"))
_PRIVATE_TOKEN_MARKERS = {"users", "private"}


def _validate_public_safe_token(value: str, owner: str, *, requires_redacted: bool) -> None:
    if (
        not value
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(marker in value.lower() for marker in _PRIVATE_TOKEN_MARKERS)
        or (requires_redacted and "redacted" not in value.lower())
    ):
        raise ValueError(f"{owner} must be public-safe")


def _validate_redacted_display_path(path: str) -> None:
    if (
        not path
        or not path.startswith("LEGACY_SOURCE:/redacted")
        or path.startswith(("/", "~"))
        or "\\" in path
        or re.match(r"^[A-Za-z]:[\\/]", path)
        or any(marker in path.lower() for marker in _PRIVATE_PATH_MARKERS)
        or not re.fullmatch(r"LEGACY_SOURCE:/[A-Za-z0-9._/-]+", path)
    ):
        raise ValueError("current reference display_path must be public-safe and redacted")


def _validate_policy(source: dict[str, Any]) -> None:
    policy = source["reference_only_policy"]
    if set(policy) != set(_EXPECTED_POLICY):
        raise ValueError("reference-only legacy import policy must match expected shape")
    for key, expected in _EXPECTED_POLICY.items():
        if policy[key] != expected:
            raise ValueError(f"reference-only legacy import policy {key} must be {expected}")


def _validate_materialization(request: dict[str, Any]) -> None:
    materialization = request["materialization"]
    expected = {
        "primary_data": "external_reference_only",
        "linked_context": "reference_only",
        "source_identity": "preserve_external_reference",
    }
    if materialization != expected:
        raise ValueError("reference-only materialization plan must match expected shape")


def _validate_current_reference(request: dict[str, Any], adapter_manifest: dict[str, Any]) -> None:
    current_reference = request["current_primary_data_reference"]
    if set(current_reference) != _CURRENT_REFERENCE_FIELDS:
        raise ValueError("current primary data reference must match expected shape")
    _validate_public_safe_token(
        current_reference["reference_id"], "current reference_id", requires_redacted=False
    )
    _validate_public_safe_token(
        current_reference["external_root_label"],
        "current external_root_label",
        requires_redacted=True,
    )
    _validate_redacted_display_path(current_reference["display_path"])

    if current_reference["reference_kind"] != _REFERENCE_KIND:
        raise ValueError(f"current reference_kind must be {_REFERENCE_KIND}")
    if current_reference["authority"] != "adapter_declared":
        raise ValueError("current reference authority must stay adapter_declared")
    if current_reference["reference_state"] != "adapter_declared_available":
        raise ValueError("current reference_state must be adapter_declared_available")
    if current_reference["adapter_primary_data_path"] != adapter_manifest["primary_data"]["path"]:
        raise ValueError("current reference must point back to adapter primary data path")
    if current_reference["digest"] is not None:
        raise ValueError("reference-only import must not claim source digest observation")
    if current_reference["size_bytes"] is not None:
        raise ValueError("reference-only import must not claim source size observation")
    if current_reference["openability"] != "not_checked":
        raise ValueError("reference-only import must not claim source openability")
    if current_reference["verification_state"] != "unobserved":
        raise ValueError("reference-only import verification_state must stay unobserved")
    if current_reference.get("reason"):
        raise ValueError("available current reference must not carry reason")


def _validate_request(source: dict[str, Any], adapter_summary: dict[str, Any]) -> None:
    request = source["reference_only_request"]
    review = request["review"]
    if review["approval_state"] != "approved":
        raise ValueError("reference-only legacy import request must be approved")
    if review["reviewed_manifest_classification"] != adapter_summary["classification"]:
        raise ValueError("reviewed manifest classification must match adapter summary")
    if adapter_summary["classification"] != "adapter_manifest_ready_for_review":
        raise ValueError("reference-only import requires a ready adapter manifest")
    _validate_materialization(request)
    _validate_current_reference(request, source["adapter_manifest"])


def _validate_references(source: dict[str, Any]) -> dict[str, Any]:
    if source["reference_only_schema"] != _REFERENCE_ONLY_SCHEMA:
        raise ValueError(f"reference_only_schema must be {_REFERENCE_ONLY_SCHEMA}")
    _validate_policy(source)
    adapter_summary = build_adapter_authored_legacy_import_summary(source["adapter_manifest"])
    _validate_request(source, adapter_summary)
    return adapter_summary


def _attention() -> list[dict[str, str]]:
    return [
        {
            "code": "reference_only_import_accepted",
            "severity": "review",
            "basis": "An approved request preserves the adapter-declared primary data as a lab-managed external reference.",
            "does_not_claim": "copied_or_observed_primary_data",
        },
        {
            "code": "legacy_parser_not_in_core",
            "severity": "review",
            "basis": "The embedded adapter manifest is validated, but Scopecat does not parse the legacy source format.",
            "does_not_claim": "labrad_datavault_labber_reader",
        },
        {
            "code": "external_reference_unobserved",
            "severity": "review",
            "basis": "The current primary-data reference is adapter-declared and is not opened, checksummed, sized, copied, or repaired.",
            "does_not_claim": "openability_or_integrity",
        },
        {
            "code": "linked_context_reference_only",
            "severity": "review",
            "basis": "Linked context references are preserved from the adapter manifest but their payloads are not imported.",
            "does_not_claim": "recursive_context_import",
        },
        {
            "code": "package_acceptance_not_performed",
            "severity": "review",
            "basis": "This accepts one adapter-authored legacy reference, not a Scopecat export or handoff package.",
            "does_not_claim": "export_package_import",
        },
    ]


def build_reference_only_legacy_import_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Build a structured summary for one reference-only legacy import request."""
    adapter_summary = _validate_references(source)
    request = source["reference_only_request"]
    return {
        "reference_only_schema": source["reference_only_schema"],
        "reference_only_policy": copy.deepcopy(source["reference_only_policy"]),
        "adapter_manifest_classification": adapter_summary["classification"],
        "measurement_record": {
            "measurement_record_id": adapter_summary["measurement"]["measurement_record_id"],
            "label": adapter_summary["measurement"]["label"],
            "experiment_type": adapter_summary["measurement"]["experiment_type"],
            "source_kind": "adapter_authored_legacy_reference",
            "classification": "reference_only_import_ready_for_review",
        },
        "adapter": adapter_summary["adapter"],
        "source_identity": adapter_summary["source_identity"],
        "reference_only_request": {
            "request_id": request["request_id"],
            "approval_state": request["review"]["approval_state"],
            "reviewed_manifest_classification": request["review"][
                "reviewed_manifest_classification"
            ],
            "materialization": copy.deepcopy(request["materialization"]),
        },
        "current_primary_data_reference": copy.deepcopy(request["current_primary_data_reference"]),
        "storage_mutation": "not_performed",
        "copy_result": "not_copied",
        "preview": adapter_summary["preview"],
        "linked_context": adapter_summary["linked_context"],
        "attention": _attention(),
    }
