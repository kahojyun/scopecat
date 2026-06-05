"""Derived local receiving review-state projection for handoff packages."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import validate_public_identifier, validate_relative_path
from scopecat.handoff.durable_import import (
    HandoffDurableImportReceiptSummary,
    HandoffDurableImportRetryReview,
)
from scopecat.handoff.errors import HandoffErrorDiagnostic, promote_handoff_contract_error
from scopecat.handoff.import_plan import HandoffImportPlanRun
from scopecat.handoff.receiving import HandoffReceivingGateRun

RECEIVING_REVIEW_STATE_RECEIPT_SCHEMA = "scopecat.handoff_receiving_review_state_receipt.v0"


@dataclass(frozen=True)
class HandoffReceivingReviewStateProjection:
    """Read-only DEC-018 projection over local handoff receipts."""

    receiving_gate: HandoffReceivingGateRun | None = None
    import_plan: HandoffImportPlanRun | None = None
    durable_import_summary: HandoffDurableImportReceiptSummary | None = None
    retry_review: HandoffDurableImportRetryReview | None = None
    error_diagnostic: HandoffErrorDiagnostic | None = None

    def __post_init__(self) -> None:
        if (
            self.receiving_gate is None
            and self.import_plan is None
            and self.durable_import_summary is None
            and self.retry_review is None
            and self.error_diagnostic is None
        ):
            raise ValueError("receiving review-state projection requires local review evidence")
        if self.receiving_gate is not None and not isinstance(
            self.receiving_gate,
            HandoffReceivingGateRun,
        ):
            raise ValueError("receiving review-state projection receiving_gate is unsupported")
        if self.import_plan is not None and not isinstance(self.import_plan, HandoffImportPlanRun):
            raise ValueError("receiving review-state projection import_plan is unsupported")
        if self.durable_import_summary is not None and not isinstance(
            self.durable_import_summary,
            HandoffDurableImportReceiptSummary,
        ):
            raise ValueError(
                "receiving review-state projection durable_import_summary is unsupported"
            )
        if self.retry_review is not None and not isinstance(
            self.retry_review,
            HandoffDurableImportRetryReview,
        ):
            raise ValueError("receiving review-state projection retry_review is unsupported")
        if self.error_diagnostic is not None and not isinstance(
            self.error_diagnostic,
            HandoffErrorDiagnostic,
        ):
            raise ValueError("receiving review-state projection error_diagnostic is unsupported")
        _validate_continuity(
            receiving_gate=self.receiving_gate,
            import_plan=self.import_plan,
            durable_import_summary=self.durable_import_summary,
            retry_review=self.retry_review,
        )

    @property
    def package_id(self) -> str | None:
        if self.import_plan is not None:
            return self.import_plan.package.package_id
        if self.receiving_gate is not None:
            return self.receiving_gate.package.package_id
        if self.durable_import_summary is not None:
            return self.durable_import_summary.package_id
        if self.retry_review is not None:
            return self.retry_review.previous_summary.package_id
        return None

    @property
    def classification(self) -> str:
        if self.error_diagnostic is not None:
            return "blocked_by_handoff_error_diagnostic"
        if self.retry_review is not None:
            return self.retry_review.classification
        if self.durable_import_summary is not None:
            return self.durable_import_summary.final_state
        if self.import_plan is not None:
            return self.import_plan.classification
        if self.receiving_gate is not None:
            return self.receiving_gate.classification
        return "receiving_review_state_unavailable"

    @property
    def block_reason(self) -> str | None:
        if self.error_diagnostic is not None:
            return "handoff_error_diagnostic_present"
        if self.retry_review is not None:
            if self.retry_review.retry_allowed:
                return None
            if self.retry_review.classification == "retry_not_applicable_after_import":
                return None
            return self.retry_review.classification
        if self.durable_import_summary is not None:
            return self.durable_import_summary.block_reason
        if self.import_plan is not None:
            return self.import_plan.to_dict()["import_plan_review"]["block_reason"]
        if self.receiving_gate is not None:
            return self.receiving_gate.to_dict()["receiving_review"]["block_reason"]
        return "receiving_review_state_unavailable"

    @property
    def next_action(self) -> str:
        if self.error_diagnostic is not None:
            return "review_handoff_error_before_retry"
        if self.retry_review is not None:
            if self.retry_review.retry_allowed:
                return "prepare_fresh_handoff_durable_import_request"
            if self.retry_review.classification == "retry_not_applicable_after_import":
                return "review_imported_measurement_record"
            return "resolve_retry_review_block_before_import"
        if self.durable_import_summary is not None:
            return self.durable_import_summary.next_action
        if self.import_plan is not None:
            return self.import_plan.to_dict()["import_plan_review"]["next_action"]
        if self.receiving_gate is not None:
            return self.receiving_gate.to_dict()["receiving_review"]["next_action"]
        return "collect_local_handoff_review_evidence"

    @property
    def retry_requires(self) -> str | None:
        if self.error_diagnostic is not None:
            return "fresh_valid_handoff_request_or_receipt"
        if self.retry_review is not None:
            if self.retry_review.retry_allowed:
                return "approved_handoff_durable_import_request"
            return self.retry_review.to_dict()["previous"]["retry_requires"]
        if self.durable_import_summary is not None:
            return self.durable_import_summary.retry_requires
        if self.import_plan is not None:
            return self.import_plan.to_dict()["import_plan_review"]["retry_requires"]
        if self.receiving_gate is not None:
            return self.receiving_gate.to_dict()["receiving_review"]["retry_requires"]
        return "local_handoff_review_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_receiving_review_state_projection",
            "classification": self.classification,
            "package": _package_summary(self.receiving_gate, self.import_plan, self.package_id),
            "integrity": _integrity_summary(self.receiving_gate, self.import_plan),
            "receiving_gate": _receiving_gate_summary(self.receiving_gate, self.import_plan),
            "import_plan": _import_plan_summary(self.import_plan),
            "linked_context": _linked_context_summary(self.import_plan),
            "durable_import": _durable_import_summary(self.durable_import_summary),
            "retry_review": _retry_review_summary(self.retry_review),
            "error_diagnostic": _diagnostic_summary(self.error_diagnostic),
            "review_state": {
                "block_reason": self.block_reason,
                "next_action": self.next_action,
                "retry_requires": self.retry_requires,
            },
        }


@dataclass(frozen=True)
class HandoffReceivingReviewStateReceiptRequest:
    """Request to persist a local receiving review-state projection receipt."""

    request_id: str
    receipt_path: str
    collision_policy: str = "no_overwrite"

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "receiving review state receipt request_id")
        validate_relative_path(self.receipt_path, "receiving review state receipt_path")
        if not self.receipt_path.endswith(".json"):
            raise ValueError("receiving review state receipt_path must end with .json")
        if self.collision_policy != "no_overwrite":
            raise ValueError("receiving review state receipt collision_policy must be no_overwrite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "receipt_path": self.receipt_path,
            "collision_policy": self.collision_policy,
        }


@dataclass(frozen=True)
class HandoffReceivingReviewStateReceipt:
    """Local receipt that materializes a receiving review-state projection."""

    request: HandoffReceivingReviewStateReceiptRequest
    projection: HandoffReceivingReviewStateProjection
    written: bool

    @property
    def classification(self) -> str:
        return self.projection.classification

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_receiving_review_state_receipt",
            "receipt_schema": RECEIVING_REVIEW_STATE_RECEIPT_SCHEMA,
            "request": self.request.to_dict(),
            "written": self.written,
            "classification": self.classification,
            "package_id": self.projection.package_id,
            "projection": self.projection.to_dict(),
        }


def project_handoff_receiving_review_state(
    *,
    receiving_gate: HandoffReceivingGateRun | None = None,
    import_plan: HandoffImportPlanRun | None = None,
    durable_import_summary: HandoffDurableImportReceiptSummary | None = None,
    retry_review: HandoffDurableImportRetryReview | None = None,
    error_diagnostic: HandoffErrorDiagnostic | None = None,
) -> HandoffReceivingReviewStateProjection:
    """Project DEC-018 local receiving review state without mutation or persistence."""

    try:
        return HandoffReceivingReviewStateProjection(
            receiving_gate=receiving_gate,
            import_plan=import_plan,
            durable_import_summary=durable_import_summary,
            retry_review=retry_review,
            error_diagnostic=error_diagnostic,
        )
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="project_handoff_receiving_review_state",
        ) from exc


def write_handoff_receiving_review_state_receipt(
    request: HandoffReceivingReviewStateReceiptRequest,
    *,
    projection: HandoffReceivingReviewStateProjection,
    state_root: str | Path,
) -> HandoffReceivingReviewStateReceipt:
    """Persist a local DEC-023 receiving review-state receipt without mutation authority."""

    try:
        if not isinstance(request, HandoffReceivingReviewStateReceiptRequest):
            raise ValueError("receiving review state receipt request is unsupported")
        if not isinstance(projection, HandoffReceivingReviewStateProjection):
            raise ValueError("receiving review state receipt projection is unsupported")
        receipt = HandoffReceivingReviewStateReceipt(
            request=request,
            projection=projection,
            written=True,
        )
        root = _existing_directory(Path(state_root), "receiving review state root")
        target = _target_under(root, request.receipt_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise ValueError("receiving review state receipt collision")
        with target.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n")
        return receipt
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="write_handoff_receiving_review_state_receipt",
        ) from exc
    except OSError as exc:
        raise promote_handoff_contract_error(
            ValueError(f"receiving review state receipt write failed: {exc}"),
            operation="write_handoff_receiving_review_state_receipt",
        ) from exc


def _validate_continuity(
    *,
    receiving_gate: HandoffReceivingGateRun | None,
    import_plan: HandoffImportPlanRun | None,
    durable_import_summary: HandoffDurableImportReceiptSummary | None,
    retry_review: HandoffDurableImportRetryReview | None,
) -> None:
    package_id = None
    if receiving_gate is not None:
        package_id = receiving_gate.package.package_id
    if import_plan is not None:
        if receiving_gate is not None and import_plan.receiving_gate != receiving_gate:
            raise ValueError("receiving review-state projection receiving gate is inconsistent")
        package_id = import_plan.package.package_id
    if durable_import_summary is not None:
        if package_id is not None and durable_import_summary.package_id != package_id:
            raise ValueError("receiving review-state projection package id is inconsistent")
        package_id = durable_import_summary.package_id
    if retry_review is not None:
        retry_package_id = retry_review.previous_summary.package_id
        if package_id is not None and retry_package_id != package_id:
            raise ValueError("receiving review-state projection package id is inconsistent")
        if (
            durable_import_summary is not None
            and retry_review.previous_summary != durable_import_summary
        ):
            raise ValueError("receiving review-state projection retry summary is inconsistent")
        if import_plan is not None and retry_review.import_plan != import_plan:
            raise ValueError("receiving review-state projection retry import plan is inconsistent")


def _existing_directory(path: Path, owner: str) -> Path:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    if resolved.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    return resolved


def _target_under(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    if root != target and root not in target.parents:
        raise ValueError("receiving review state receipt_path must stay under state root")
    return target


def _package_summary(
    receiving_gate: HandoffReceivingGateRun | None,
    import_plan: HandoffImportPlanRun | None,
    package_id: str | None,
) -> dict[str, Any] | None:
    package = None
    if import_plan is not None:
        package = import_plan.package
    elif receiving_gate is not None:
        package = receiving_gate.package
    if package is None:
        if package_id is None:
            return None
        return {"package_id": package_id}
    return {
        "package_id": package.package_id,
        "display_name": package.display_name,
        "preview_classification": package.preview_classification,
        "measurement_ids": list(package.measurement_ids),
    }


def _integrity_summary(
    receiving_gate: HandoffReceivingGateRun | None,
    import_plan: HandoffImportPlanRun | None,
) -> dict[str, Any] | None:
    gate = receiving_gate or (None if import_plan is None else import_plan.receiving_gate)
    if gate is None:
        return None
    return {
        "classification": gate.integrity_report.classification,
        "member_count": gate.integrity_report.member_count,
        "finding_count": len(gate.integrity_report.integrity_findings),
    }


def _receiving_gate_summary(
    receiving_gate: HandoffReceivingGateRun | None,
    import_plan: HandoffImportPlanRun | None,
) -> dict[str, Any] | None:
    gate = receiving_gate or (None if import_plan is None else import_plan.receiving_gate)
    if gate is None:
        return None
    review = gate.to_dict()["receiving_review"]
    return {
        "classification": gate.classification,
        "acceptance_allowed": gate.acceptance_allowed,
        "review": copy.deepcopy(review),
    }


def _import_plan_summary(import_plan: HandoffImportPlanRun | None) -> dict[str, Any] | None:
    if import_plan is None:
        return None
    receipt = import_plan.to_dict()
    return {
        "classification": import_plan.classification,
        "allowed": import_plan.import_plan_allowed,
        "planned_measurement_ids": [
            plan.measurement.measurement_record_id for plan in import_plan.measurement_plans
        ],
        "review": copy.deepcopy(receipt["import_plan_review"]),
    }


def _linked_context_summary(import_plan: HandoffImportPlanRun | None) -> dict[str, Any]:
    if import_plan is None:
        return {
            "handling": "unavailable_until_import_plan",
            "plans": [],
        }
    return {
        "handling": "keep_reference_only",
        "plans": [plan.to_dict() for plan in import_plan.linked_context_plans],
    }


def _durable_import_summary(
    summary: HandoffDurableImportReceiptSummary | None,
) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "package_id": summary.package_id,
        "measurement_record_id": summary.measurement_record_id,
        "destination_record_id": summary.destination_record_id,
        "final_state": summary.final_state,
        "durable_import_performed": summary.durable_import_performed,
        "durable_import_classification": summary.durable_import_classification,
        "rollback_performed": summary.rollback_performed,
        "partial_commit": summary.partial_commit,
        "import_error": summary.import_error,
        "block_reason": summary.block_reason,
        "next_action": summary.next_action,
        "retry_requires": summary.retry_requires,
    }


def _retry_review_summary(review: HandoffDurableImportRetryReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "classification": review.classification,
        "retry_allowed": review.retry_allowed,
        "package_id": review.previous_summary.package_id,
        "measurement_record_id": review.previous_summary.measurement_record_id,
        "fresh_import_plan": {
            "classification": review.import_plan.classification,
            "allowed": review.import_plan.import_plan_allowed,
            "planned_measurement_ids": [
                plan.measurement.measurement_record_id
                for plan in review.import_plan.measurement_plans
            ],
        },
    }


def _diagnostic_summary(diagnostic: HandoffErrorDiagnostic | None) -> dict[str, Any] | None:
    if diagnostic is None:
        return None
    return diagnostic.to_dict()["error"]
