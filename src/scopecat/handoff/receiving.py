"""Read-only receiving gate for handoff package import decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier
from scopecat.handoff.errors import promote_handoff_contract_error
from scopecat.handoff.integrity import HandoffPackageIntegrityReport, observe_package_integrity
from scopecat.handoff.package import HandoffPackage
from scopecat.handoff.read_only import open_package


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

    @property
    def block_reason(self) -> str | None:
        return _receiving_block_reason(
            acceptance_allowed=self.acceptance_allowed,
            integrity_classification=self.integrity_report.classification,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_receiving_gate_receipt",
            "classification": self.classification,
            "block_reason": self.block_reason,
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
            },
        }


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
