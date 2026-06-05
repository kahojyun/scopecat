"""Read-only operator smoke summary for the JNY-001 handoff path."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff.archive_materialization import (
    HandoffArchiveCreationRun,
    HandoffArchiveMaterializationRun,
)
from scopecat.handoff.durable_import import (
    HandoffDurableImportRun,
    summarize_handoff_durable_import_receipt,
)
from scopecat.handoff.import_plan import HandoffImportPlanRun
from scopecat.handoff.receiving import HandoffReceivingGateRun
from scopecat.handoff.review_state import HandoffReceivingReviewStateReceipt
from scopecat.handoff.selected_record_export import SelectedMeasurementRecordExportRun


@dataclass(frozen=True)
class HandoffJny001OperatorSmokeSummary:
    """Compact read-only summary of one completed JNY-001 handoff smoke path."""

    selected_export: SelectedMeasurementRecordExportRun
    archive_creation: HandoffArchiveCreationRun
    archive_materialization: HandoffArchiveMaterializationRun
    receiving_gate: HandoffReceivingGateRun
    import_plan: HandoffImportPlanRun
    receiving_review_state_receipt: HandoffReceivingReviewStateReceipt
    durable_import: HandoffDurableImportRun

    def __post_init__(self) -> None:
        _validate_type(
            self.selected_export,
            SelectedMeasurementRecordExportRun,
            "operator smoke selected_export",
        )
        _validate_type(
            self.archive_creation,
            HandoffArchiveCreationRun,
            "operator smoke archive_creation",
        )
        _validate_type(
            self.archive_materialization,
            HandoffArchiveMaterializationRun,
            "operator smoke archive_materialization",
        )
        _validate_type(
            self.receiving_gate, HandoffReceivingGateRun, "operator smoke receiving_gate"
        )
        _validate_type(self.import_plan, HandoffImportPlanRun, "operator smoke import_plan")
        _validate_type(
            self.receiving_review_state_receipt,
            HandoffReceivingReviewStateReceipt,
            "operator smoke receiving_review_state_receipt",
        )
        _validate_type(
            self.durable_import,
            HandoffDurableImportRun,
            "operator smoke durable_import",
        )
        if self.archive_creation.request.package_dir != self.package_id:
            raise ValueError("operator smoke archive creation package id is inconsistent")
        if self.archive_materialization.request.package_dir != self.package_id:
            raise ValueError("operator smoke archive materialization package id is inconsistent")
        if self.receiving_gate.package.package_id != self.package_id:
            raise ValueError("operator smoke receiving package id is inconsistent")
        if self.import_plan.package.package_id != self.package_id:
            raise ValueError("operator smoke import plan package id is inconsistent")
        if self.receiving_review_state_receipt.projection.package_id != self.package_id:
            raise ValueError("operator smoke receiving review state package id is inconsistent")
        durable_summary = self.durable_import_summary
        if durable_summary.package_id != self.package_id:
            raise ValueError("operator smoke durable import package id is inconsistent")
        if durable_summary.measurement_record_id != self.source_record_id:
            raise ValueError("operator smoke durable import measurement id is inconsistent")

    @property
    def package_id(self) -> str:
        return self.selected_export.request.package_id

    @property
    def source_record_id(self) -> str:
        return self.selected_export.request.record_id

    @property
    def durable_import_summary(self):
        return summarize_handoff_durable_import_receipt(self.durable_import.to_dict())

    @property
    def completed(self) -> bool:
        return all(
            (
                self.selected_export.exported,
                self.archive_creation.created,
                self.archive_materialization.materialized,
                self.receiving_gate.acceptance_allowed,
                self.import_plan.import_plan_allowed,
                self.receiving_review_state_receipt.written,
                self.durable_import.imported,
            )
        )

    @property
    def classification(self) -> str:
        if self.completed:
            return "completed_jny001_operator_smoke"
        return "blocked_jny001_operator_smoke"

    def to_dict(self) -> dict[str, Any]:
        durable_summary = self.durable_import_summary
        durable_result = self.durable_import.to_dict()["durable_import_result"]
        return {
            "artifact_posture": "local_jny001_operator_smoke_summary",
            "journey_id": "JNY-001",
            "workflow_scope": "jny001_vertical_slice_smoke",
            "use_case_ids": ["UC-006", "UC-004", "UC-002"],
            "classification": self.classification,
            "package_id": self.package_id,
            "source_record_id": self.source_record_id,
            "destination_record_id": durable_summary.destination_record_id,
            "stage_sequence": [
                "selected_record_export",
                "archive_creation",
                "archive_materialization",
                "receiving_review",
                "import_plan",
                "receiving_review_state_receipt",
                "durable_import",
            ],
            "stages": {
                "selected_record_export": self.selected_export.classification,
                "archive_creation": self.archive_creation.classification,
                "archive_materialization": self.archive_materialization.classification,
                "receiving_review": self.receiving_gate.classification,
                "import_plan": self.import_plan.classification,
                "receiving_review_state_receipt": (
                    self.receiving_review_state_receipt.classification
                ),
                "durable_import": self.durable_import.classification,
            },
            "operator_result": {
                "final_state": durable_summary.final_state,
                "next_action": durable_summary.next_action,
                "retry_requires": durable_summary.retry_requires,
                "durable_import_performed": durable_summary.durable_import_performed,
            },
            "boundary": {
                "archive_bytes": (
                    self.archive_creation.to_dict()["artifact_authority"]["archive_bytes"]
                ),
                "package_of_record": (
                    self.archive_materialization.to_dict()["artifact_authority"][
                        "package_of_record"
                    ]
                ),
                "durable_record_creation": (
                    durable_result["pipeline"]["creation"] if durable_result is not None else None
                ),
            },
        }


def summarize_jny001_operator_smoke(
    *,
    selected_export: SelectedMeasurementRecordExportRun,
    archive_creation: HandoffArchiveCreationRun,
    archive_materialization: HandoffArchiveMaterializationRun,
    receiving_gate: HandoffReceivingGateRun,
    import_plan: HandoffImportPlanRun,
    receiving_review_state_receipt: HandoffReceivingReviewStateReceipt,
    durable_import: HandoffDurableImportRun,
) -> HandoffJny001OperatorSmokeSummary:
    """Summarize one local JNY-001 handoff smoke path without running mutations."""

    return HandoffJny001OperatorSmokeSummary(
        selected_export=selected_export,
        archive_creation=archive_creation,
        archive_materialization=archive_materialization,
        receiving_gate=receiving_gate,
        import_plan=import_plan,
        receiving_review_state_receipt=receiving_review_state_receipt,
        durable_import=durable_import,
    )


def summarize_jny001_operator_smoke_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a local JNY-001 operator smoke summary receipt."""

    if receipt.get("artifact_posture") != "local_jny001_operator_smoke_summary":
        raise ValueError("JNY-001 operator smoke receipt posture is unsupported")
    _require_keys(
        receipt,
        {
            "artifact_posture",
            "journey_id",
            "workflow_scope",
            "use_case_ids",
            "classification",
            "package_id",
            "source_record_id",
            "destination_record_id",
            "stage_sequence",
            "stages",
            "operator_result",
            "boundary",
        },
        "JNY-001 operator smoke receipt",
    )
    if receipt["journey_id"] != "JNY-001":
        raise ValueError("JNY-001 operator smoke receipt journey id is unsupported")
    if receipt["workflow_scope"] != "jny001_vertical_slice_smoke":
        raise ValueError("JNY-001 operator smoke receipt workflow scope is unsupported")
    return copy.deepcopy(receipt)


def _validate_type(value: object, expected_type: type, owner: str) -> None:
    if not isinstance(value, expected_type):
        raise ValueError(f"{owner} is unsupported")


def _require_keys(value: dict[str, Any], keys: set[str], owner: str) -> None:
    missing = sorted(keys.difference(value))
    if missing:
        raise ValueError(f"{owner} is missing required keys: {', '.join(missing)}")
