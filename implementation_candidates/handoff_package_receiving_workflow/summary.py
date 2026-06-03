"""Receiving-side composition workflow for handoff packages.

This candidate composes existing inspection, integrity observation, and
acceptance candidates. It keeps inspection and integrity read-only, then gates
the existing storage acceptance step on explicit approval and reviewed
continuity facts.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from implementation_candidates.contract_primitives import validate_public_identifier
from implementation_candidates.handoff_package_acceptance import accept_handoff_package
from implementation_candidates.handoff_package_contracts import (
    validate_handoff_receiving_roots,
    validate_handoff_reviewed_package_continuity,
)
from implementation_candidates.handoff_package_inspection_workflow import (
    build_handoff_package_inspection_summary,
)
from implementation_candidates.handoff_package_integrity_observation import (
    observe_handoff_package_integrity,
)
from implementation_candidates.handoff_package_visual_artifact import (
    HANDOFF_PACKAGE_VISUAL_REVIEW_ARTIFACT_NAME,
)

_EXPECTED_SCHEMA = "scopecat.handoff_package_receiving_workflow.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "approved_receiving_workflow_request",
    "package_inspection": "read_only_visual_inspection_workflow",
    "integrity_observation": "read_only_package_local_member_observation",
    "integrity_gate": "require_declared_integrity_verified",
    "acceptance_authority": "delegate_to_handoff_package_acceptance",
    "storage_mutation": "acceptance_candidate_only_after_gate",
    "archive_handling": "not_performed",
    "external_authenticity_validation": "not_performed",
    "package_root_concurrency": "not_supported",
    "schema_inference": "not_performed",
    "dataframe_adapter": "not_defined",
    "interactive_gui": "not_defined",
    "shared_measurement_schema": "not_defined",
}
_ACCEPTANCE_POLICY = {
    "acceptance_authority": "approved_handoff_package_acceptance_request",
    "package_authority": "directory_shaped_handoff_package",
    "package_open": "read_only_declared_preview",
    "storage_mutation": "copy_package_primary_data_and_write_record_manifests",
    "copy_behavior": "copy_into_new_records",
    "linked_context_materialization": "reference_only",
    "overwrite_behavior": "no_overwrite",
    "archive_handling": "not_performed",
    "package_integrity": "not_claimed",
    "checksum_validation": "not_performed",
    "package_root_concurrency": "not_supported",
    "schema_inference": "not_performed",
    "dataframe_adapter": "not_defined",
    "gui_workflow": "not_defined",
    "stable_public_api": "not_defined",
}


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _validate_source(source: dict[str, Any]) -> dict[str, Any]:
    source = _require_mapping(source, "handoff package receiving workflow source")
    _require_keys(
        source,
        {"receiving_schema", "receiving_policy", "receiving_request"},
        "handoff package receiving workflow source",
    )
    if source["receiving_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("receiving_schema is unsupported")
    if source["receiving_policy"] != _EXPECTED_POLICY:
        raise ValueError("receiving_policy is unsupported")

    request = _require_mapping(source["receiving_request"], "receiving_request")
    _require_keys(
        request,
        {"request_id", "review", "acceptance"},
        "receiving_request",
    )
    request_id = validate_public_identifier(request["request_id"], "receiving_request.request_id")
    review = _require_mapping(request["review"], "receiving_request.review")
    _require_keys(
        review,
        {
            "approval_state",
            "reviewed_package_id",
            "reviewed_preview_classification",
            "reviewed_integrity_classification",
        },
        "receiving_request.review",
    )
    if review["approval_state"] != "approved":
        raise ValueError("handoff package receiving workflow requires approved review")
    validate_public_identifier(
        review["reviewed_package_id"],
        "receiving_request.review.reviewed_package_id",
    )
    validate_public_identifier(
        review["reviewed_preview_classification"],
        "receiving_request.review.reviewed_preview_classification",
    )
    validate_public_identifier(
        review["reviewed_integrity_classification"],
        "receiving_request.review.reviewed_integrity_classification",
    )

    acceptance = _require_mapping(request["acceptance"], "receiving_request.acceptance")
    _require_keys(
        acceptance,
        {"destination", "materialization", "selected_measurements"},
        "receiving_request.acceptance",
    )
    return {
        "request_id": request_id,
        "review": review,
        "acceptance": acceptance,
    }


def _validate_reviewed_facts(
    *,
    review: dict[str, str],
    inspection: dict[str, Any],
    integrity: dict[str, Any],
) -> None:
    validate_handoff_reviewed_package_continuity(
        reviewed_package_id=review["reviewed_package_id"],
        reviewed_preview_classification=review["reviewed_preview_classification"],
        reviewed_integrity_classification=review["reviewed_integrity_classification"],
        inspected_package=inspection["package"],
        integrity_package=integrity["package"],
        integrity_classification=integrity["classification"],
    )


def _acceptance_source(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptance_schema": "scopecat.handoff_package_acceptance.v0",
        "acceptance_policy": copy.deepcopy(_ACCEPTANCE_POLICY),
        "acceptance_request": {
            "request_id": request["request_id"],
            "review": {
                "approval_state": request["review"]["approval_state"],
                "reviewed_package_id": request["review"]["reviewed_package_id"],
                "reviewed_preview_classification": request["review"][
                    "reviewed_preview_classification"
                ],
            },
            "destination": copy.deepcopy(request["acceptance"]["destination"]),
            "materialization": copy.deepcopy(request["acceptance"]["materialization"]),
            "selected_measurements": copy.deepcopy(request["acceptance"]["selected_measurements"]),
        },
    }


def _integrity_gate(integrity: dict[str, Any]) -> dict[str, Any]:
    allowed = integrity["classification"] == "declared_integrity_verified"
    return {
        "required_classification": "declared_integrity_verified",
        "observed_classification": integrity["classification"],
        "allowed": allowed,
        "basis": (
            "All declared package members with paired integrity facts matched observed bytes."
            if allowed
            else "Package integrity observation requires review before storage acceptance."
        ),
        "finding_count": len(integrity["integrity_findings"]),
    }


def _attention(accepted: bool) -> list[dict[str, str]]:
    if accepted:
        return [
            {
                "code": "receiving_workflow_completed",
                "severity": "info",
                "basis": "The package was inspected, integrity-observed, approved, and accepted into local storage through existing candidates.",
                "does_not_claim": "final_import_api_or_gui_workflow",
            },
            {
                "code": "composition_does_not_verify_authenticity",
                "severity": "review",
                "basis": "Integrity observation compares local bytes to manifest facts only; external provenance trust remains outside this workflow.",
                "does_not_claim": "external_authenticity_or_trust_validation",
            },
        ]
    return [
        {
            "code": "receiving_workflow_blocked_before_acceptance",
            "severity": "review",
            "basis": "The package was inspected and integrity-observed, but the integrity gate did not allow storage acceptance.",
            "does_not_claim": "record_written_to_storage",
        },
        {
            "code": "composition_does_not_repair_packages",
            "severity": "review",
            "basis": "The workflow reports the blocked state without modifying package contents or storage.",
            "does_not_claim": "package_repair_or_import_acceptance",
        },
    ]


def run_handoff_package_receiving_workflow(
    source: dict[str, Any],
    *,
    package_dir: Path,
    artifact_output_dir: Path,
    storage_root: Path,
    overwrite_artifact: bool = False,
) -> dict[str, Any]:
    """Run the local receiving workflow for a handoff package."""

    request = _validate_source(source)
    validate_handoff_receiving_roots(
        package_dir=package_dir,
        artifact_output_dir=artifact_output_dir,
        storage_root=storage_root,
        artifact_output_filenames=(HANDOFF_PACKAGE_VISUAL_REVIEW_ARTIFACT_NAME,),
        allow_existing_artifact_targets=overwrite_artifact,
    )
    inspection = build_handoff_package_inspection_summary(
        package_dir,
        artifact_output_dir=artifact_output_dir,
        overwrite_artifact=overwrite_artifact,
    )
    integrity = observe_handoff_package_integrity(package_dir)
    _validate_reviewed_facts(
        review=request["review"],
        inspection=inspection,
        integrity=integrity,
    )

    gate = _integrity_gate(integrity)
    package = {
        "package_id": inspection["package"]["package_id"],
        "display_name": inspection["package"]["display_name"],
        "package_directory_name": inspection["package"]["package_directory_name"],
        "preview_classification": inspection["package"]["preview_classification"],
        "integrity_classification": integrity["classification"],
        "measurement_count": inspection["package"]["measurement_count"],
    }
    if not gate["allowed"]:
        return {
            "artifact_posture": "local_receiving_workflow_receipt",
            "workflow_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow_classification": "blocked_before_acceptance",
            "package": package,
            "receiving_request": {
                "request_id": request["request_id"],
                "approval_state": request["review"]["approval_state"],
            },
            "inspection": {
                "performed": True,
                "local_visual_artifact": copy.deepcopy(inspection["local_visual_artifact"]),
            },
            "integrity_observation": {
                "performed": True,
                "classification": integrity["classification"],
                "finding_count": len(integrity["integrity_findings"]),
            },
            "acceptance_gate": gate,
            "acceptance": {
                "performed": False,
                "storage_mutation": "not_performed",
            },
            "attention": _attention(False),
        }

    acceptance_receipt = accept_handoff_package(
        _acceptance_source(request),
        package_dir=package_dir,
        storage_root=storage_root,
    )
    return {
        "artifact_posture": "local_receiving_workflow_receipt",
        "workflow_policy": copy.deepcopy(_EXPECTED_POLICY),
        "workflow_classification": "accepted_into_storage",
        "package": package,
        "receiving_request": {
            "request_id": request["request_id"],
            "approval_state": request["review"]["approval_state"],
        },
        "inspection": {
            "performed": True,
            "local_visual_artifact": copy.deepcopy(inspection["local_visual_artifact"]),
        },
        "integrity_observation": {
            "performed": True,
            "classification": integrity["classification"],
            "member_count": integrity["member_count"],
            "finding_count": len(integrity["integrity_findings"]),
        },
        "acceptance_gate": gate,
        "acceptance": {
            "performed": True,
            "artifact_posture": acceptance_receipt["artifact_posture"],
            "storage_write": copy.deepcopy(acceptance_receipt["storage_write"]),
            "accepted_measurements": copy.deepcopy(acceptance_receipt["accepted_measurements"]),
        },
        "attention": _attention(True),
    }
