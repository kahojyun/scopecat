"""Read-only receiving gate for handoff package import decisions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.errors import promote_handoff_contract_error
from scopecat.handoff.integrity import HandoffPackageIntegrityReport, observe_package_integrity
from scopecat.handoff.package import HandoffPackage
from scopecat.handoff.read_only import open_package

_EXPECTED_SCHEMA = "scopecat.handoff_receiving_gate.v0"
_EXPECTED_POLICY = {
    "workflow_authority": "approved_receiving_review_request",
    "package_open": "read_only_declared_preview",
    "integrity_observation": "read_only_package_local_member_observation",
    "acceptance_gate": "require_approved_review_and_declared_integrity_verified",
    "storage_mutation": "not_performed",
    "import_acceptance": "not_performed",
    "archive_handling": "not_performed",
    "external_authenticity_validation": "not_performed",
    "package_root_concurrency": "not_supported",
    "schema_inference": "not_performed",
    "dataframe_adapter": "not_defined",
    "interactive_gui": "not_defined",
    "shared_measurement_schema": "not_defined",
}


@dataclass(frozen=True)
class HandoffReceivingReviewRequest:
    """Approved review facts supplied before any receiving-side mutation."""

    request_id: str
    reviewed_package_id: str
    reviewed_preview_classification: str
    reviewed_integrity_classification: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "receiving_review_request.request_id")
        validate_public_identifier(
            self.reviewed_package_id,
            "receiving_review_request.review.reviewed_package_id",
        )
        validate_public_identifier(
            self.reviewed_preview_classification,
            "receiving_review_request.review.reviewed_preview_classification",
        )
        validate_public_identifier(
            self.reviewed_integrity_classification,
            "receiving_review_request.review.reviewed_integrity_classification",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "approval_state": "approved",
            "reviewed_package_id": self.reviewed_package_id,
            "reviewed_preview_classification": self.reviewed_preview_classification,
            "reviewed_integrity_classification": self.reviewed_integrity_classification,
        }


@dataclass(frozen=True)
class HandoffReceivingGateRun:
    """Read-only receiving gate result for a reviewed package."""

    request: HandoffReceivingReviewRequest
    package: HandoffPackage
    integrity_report: HandoffPackageIntegrityReport
    package_dir: str
    package_open_error: str | None = None

    @property
    def acceptance_allowed(self) -> bool:
        return (
            self.package_open_error is None
            and self.integrity_report.classification == "declared_integrity_verified"
        )

    @property
    def classification(self) -> str:
        if self.acceptance_allowed:
            return "ready_for_acceptance_mutation"
        return "blocked_before_acceptance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_receiving_gate_receipt",
            "receiving_gate_policy": copy.deepcopy(_EXPECTED_POLICY),
            "workflow_classification": self.classification,
            "request": self.request.to_dict(),
            "package": {
                "package_id": self.package.package_id,
                "display_name": self.package.display_name,
                "preview_classification": self.package.preview_classification,
                "integrity_classification": self.integrity_report.classification,
                "measurement_ids": list(self.package.measurement_ids),
                "open_error": self.package_open_error,
            },
            "integrity_observation": {
                "performed": True,
                "classification": self.integrity_report.classification,
                "member_count": self.integrity_report.member_count,
                "finding_count": len(self.integrity_report.integrity_findings),
            },
            "acceptance_gate": {
                "required_integrity_classification": "declared_integrity_verified",
                "allowed": self.acceptance_allowed,
                "basis": (
                    "Approved review facts match package and integrity observations."
                    if self.acceptance_allowed
                    else "Integrity observation must be reviewed before acceptance mutation."
                ),
            },
            "receiving_review": _receiving_review(
                classification=self.classification,
                acceptance_allowed=self.acceptance_allowed,
                integrity_classification=self.integrity_report.classification,
            ),
            "does_not_claim": [
                "storage_mutation",
                "package_import_or_acceptance",
                "archive_extraction",
                "external_authenticity_or_trust_validation",
                "final_storage_schema",
            ],
        }


def run_receiving_gate(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
) -> HandoffReceivingGateRun:
    """Open, integrity-observe, and gate a reviewed package without mutation."""

    try:
        request = _parse_request(source)
        return _run_receiving_gate_from_request(request, package_dir=package_dir)
    except ValueError as exc:
        raise promote_handoff_contract_error(exc, operation="run_receiving_gate") from exc


def run_receiving_gate_from_request(
    request: HandoffReceivingReviewRequest,
    *,
    package_dir: str | Path,
) -> HandoffReceivingGateRun:
    """Run the receiving gate from an already parsed route-local request."""

    try:
        return _run_receiving_gate_from_request(request, package_dir=package_dir)
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="run_receiving_gate_from_request",
        ) from exc


def _run_receiving_gate_from_request(
    request: HandoffReceivingReviewRequest,
    *,
    package_dir: str | Path,
) -> HandoffReceivingGateRun:
    integrity_report = observe_package_integrity(package_dir)
    try:
        package = open_package(package_dir)
        package_open_error = None
    except ValueError as exc:
        if integrity_report.classification == "declared_integrity_verified":
            raise
        package = _review_only_package(integrity_report)
        package_open_error = str(exc)
    resolved_package_dir = str(Path(package_dir).resolve())
    _validate_reviewed_facts(
        request=request,
        package=package,
        integrity_report=integrity_report,
    )
    return HandoffReceivingGateRun(
        request=request,
        package=package,
        integrity_report=integrity_report,
        package_dir=resolved_package_dir,
        package_open_error=package_open_error,
    )


def _review_only_package(integrity_report: HandoffPackageIntegrityReport) -> HandoffPackage:
    return HandoffPackage(
        package_id=integrity_report.package_id,
        display_name=integrity_report.display_name,
        created_by="unavailable_until_package_open",
        source_export_summary_id="unavailable_until_package_open",
        preview_classification=integrity_report.preview_classification,
        measurements=(),
        linked_context=(),
        findings=(),
        classification="blocked_before_declared_preview_open",
    )


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _parse_request(source: dict[str, Any]) -> HandoffReceivingReviewRequest:
    source = _require_mapping(source, "handoff receiving gate source")
    _require_keys(
        source,
        {"receiving_gate_schema", "receiving_gate_policy", "receiving_review_request"},
        "handoff receiving gate source",
    )
    if source["receiving_gate_schema"] != _EXPECTED_SCHEMA:
        raise ValueError("receiving_gate_schema is unsupported")
    if source["receiving_gate_policy"] != _EXPECTED_POLICY:
        raise ValueError("receiving_gate_policy is unsupported")

    request = _require_mapping(source["receiving_review_request"], "receiving_review_request")
    _require_keys(request, {"request_id", "review"}, "receiving_review_request")
    request_id = validate_public_identifier(
        request["request_id"],
        "receiving_review_request.request_id",
    )
    review = _require_mapping(request["review"], "receiving_review_request.review")
    _require_keys(
        review,
        {
            "approval_state",
            "reviewed_package_id",
            "reviewed_preview_classification",
            "reviewed_integrity_classification",
        },
        "receiving_review_request.review",
    )
    if review["approval_state"] != "approved":
        raise ValueError("handoff receiving gate requires approved review")
    return HandoffReceivingReviewRequest(
        request_id=request_id,
        reviewed_package_id=validate_public_identifier(
            review["reviewed_package_id"],
            "receiving_review_request.review.reviewed_package_id",
        ),
        reviewed_preview_classification=validate_public_identifier(
            review["reviewed_preview_classification"],
            "receiving_review_request.review.reviewed_preview_classification",
        ),
        reviewed_integrity_classification=validate_public_identifier(
            review["reviewed_integrity_classification"],
            "receiving_review_request.review.reviewed_integrity_classification",
        ),
    )


def _validate_reviewed_facts(
    *,
    request: HandoffReceivingReviewRequest,
    package: HandoffPackage,
    integrity_report: HandoffPackageIntegrityReport,
) -> None:
    if request.reviewed_package_id != package.package_id:
        raise ValueError("reviewed package id must match opened package")
    if request.reviewed_preview_classification != package.preview_classification:
        raise ValueError("reviewed preview classification must match opened package")
    if request.reviewed_package_id != integrity_report.package_id:
        raise ValueError("integrity package id must match opened package")
    if request.reviewed_integrity_classification != integrity_report.classification:
        raise ValueError("reviewed integrity classification must match observed integrity")


def _receiving_review(
    *,
    classification: str,
    acceptance_allowed: bool,
    integrity_classification: str,
) -> dict[str, str | None | bool]:
    block_reason = _receiving_block_reason(
        acceptance_allowed=acceptance_allowed,
        integrity_classification=integrity_classification,
    )
    return {
        "classification": classification,
        "acceptance_allowed": acceptance_allowed,
        "block_reason": block_reason,
        "next_action": _receiving_next_action(block_reason),
        "retry_requires": _receiving_retry_requirement(block_reason),
    }


def _receiving_block_reason(
    *,
    acceptance_allowed: bool,
    integrity_classification: str,
) -> str | None:
    if acceptance_allowed:
        return None
    if integrity_classification == "integrity_review_required":
        return "package_integrity_review_required"
    if integrity_classification == "integrity_observed_with_undeclared_members":
        return "undeclared_package_members_review_required"
    return "receiving_gate_not_ready"


def _receiving_next_action(block_reason: str | None) -> str:
    if block_reason is None:
        return "build_import_plan_for_reviewed_package"
    if block_reason in {
        "package_integrity_review_required",
        "undeclared_package_members_review_required",
    }:
        return "review_package_integrity_before_import_planning"
    return "review_receiving_gate_before_import_planning"


def _receiving_retry_requirement(block_reason: str | None) -> str | None:
    if block_reason is None:
        return None
    if block_reason in {
        "package_integrity_review_required",
        "undeclared_package_members_review_required",
    }:
        return "fresh_matching_package_open_and_integrity_observation"
    return "fresh_receiving_review_request"
