"""Adapter from a ready handoff import plan to durable measurement-record import."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    validate_non_overlapping_relative_paths,
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_strict_child_path,
)
from scopecat.handoff.errors import promote_handoff_contract_error
from scopecat.handoff.import_plan import HandoffImportPlanRun
from scopecat.handoff.package import HandoffMeasurement
from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordDurableImportRun,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

APPROVAL_STATES = {"approved", "rejected", "needs_review"}


@dataclass(frozen=True)
class HandoffDurableImportDestination:
    """Caller-declared durable destination for one package measurement."""

    record_id: str
    record_dir: str
    primary_data_path: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.record_id, "handoff durable import destination record_id")
        validate_relative_path(self.record_dir, "handoff durable import destination record_dir")
        validate_relative_path(
            self.primary_data_path,
            "handoff durable import destination primary_data_path",
        )
        validate_relative_path(
            self.writer_receipt_path,
            "handoff durable import destination writer_receipt_path",
        )
        validate_relative_path(
            self.finalization_receipt_path,
            "handoff durable import destination finalization_receipt_path",
        )
        validate_relative_path(
            self.read_model_path,
            "handoff durable import destination read_model_path",
        )
        validate_strict_child_path(
            self.primary_data_path,
            self.record_dir,
            "handoff durable import destination primary_data_path",
        )
        validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "handoff durable import destination writer_receipt_path",
        )
        validate_strict_child_path(
            self.finalization_receipt_path,
            self.record_dir,
            "handoff durable import destination finalization_receipt_path",
        )
        validate_strict_child_path(
            self.read_model_path,
            self.record_dir,
            "handoff durable import destination read_model_path",
        )
        validate_non_overlapping_relative_paths(
            [
                f"{self.record_dir}/record-manifest.json",
                self.primary_data_path,
                self.writer_receipt_path,
                self.finalization_receipt_path,
                self.read_model_path,
            ],
            "handoff durable import destination output paths",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "primary_data_path": self.primary_data_path,
            "writer_receipt_path": self.writer_receipt_path,
            "finalization_receipt_path": self.finalization_receipt_path,
            "read_model_path": self.read_model_path,
        }


@dataclass(frozen=True)
class HandoffDurableImportRequest:
    """Approved handoff request to import one planned measurement durably."""

    request_id: str
    approval_state: str
    requested_package_id: str
    measurement_record_id: str
    destination: HandoffDurableImportDestination

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "handoff durable import request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("handoff durable import approval_state is unsupported")
        validate_public_identifier(
            self.requested_package_id,
            "handoff durable import requested_package_id",
        )
        validate_public_identifier(
            self.measurement_record_id,
            "handoff durable import measurement_record_id",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "requested_package_id": self.requested_package_id,
            "measurement_record_id": self.measurement_record_id,
            "durable_record_destination": self.destination.to_dict(),
        }


@dataclass(frozen=True)
class HandoffDurableImportRun:
    """Local receipt for adapting a handoff import plan into durable storage."""

    request: HandoffDurableImportRequest
    import_plan: HandoffImportPlanRun
    durable_import_request: MeasurementRecordDurableImportRequest | None = None
    durable_import_run: MeasurementRecordDurableImportRun | None = None

    @property
    def imported(self) -> bool:
        return self.durable_import_run is not None and self.durable_import_run.imported

    @property
    def classification(self) -> str:
        if self.imported:
            return "imported_handoff_measurement_record"
        if self.durable_import_run is not None:
            return "blocked_before_handoff_durable_import"
        if not self.import_plan.import_plan_allowed:
            return "blocked_before_handoff_durable_import"
        if not self.request.approved:
            return "blocked_before_handoff_durable_import"
        return "ready_for_handoff_durable_import"

    @property
    def block_reason(self) -> str | None:
        return _durable_import_block_reason(
            final_state=self.classification,
            approval_state=self.request.approval_state,
            import_plan_allowed=self.import_plan.import_plan_allowed,
            import_plan_block_reason=self.import_plan.block_reason,
            durable_import_classification=(
                None if self.durable_import_run is None else self.durable_import_run.classification
            ),
            rollback_performed=(
                False
                if self.durable_import_run is None
                else self.durable_import_run.rollback_performed
            ),
            partial_commit=(
                False if self.durable_import_run is None else self.durable_import_run.partial_commit
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        workflow_steps = [
            "build_import_plan",
            *(
                [
                    "map_handoff_measurement_to_durable_import_request",
                    "run_measurement_record_durable_import",
                ]
                if self.durable_import_request is not None
                else []
            ),
        ]
        return {
            "artifact_posture": "local_handoff_durable_import_receipt",
            "classification": self.classification,
            "block_reason": self.block_reason,
            "steps": workflow_steps,
            "request": self.request.to_dict(),
            "import_plan": {
                "classification": self.import_plan.classification,
                "allowed": self.import_plan.import_plan_allowed,
                "package_id": self.import_plan.package.package_id,
                "planned_measurement_ids": [
                    plan.measurement.measurement_record_id
                    for plan in self.import_plan.measurement_plans
                ],
                "linked_context": [
                    plan.to_dict() for plan in self.import_plan.linked_context_plans
                ],
            },
            "durable_import_request": (
                None
                if self.durable_import_request is None
                else self.durable_import_request.to_dict()
            ),
            "durable_import_result": (
                None if self.durable_import_run is None else self.durable_import_run.to_dict()
            ),
        }


def run_handoff_durable_import_from_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
    storage_root: str | Path,
) -> HandoffDurableImportRun:
    """Import one ready handoff-plan measurement through durable record storage."""

    try:
        return _run_handoff_durable_import_from_plan(
            request,
            import_plan=import_plan,
            storage_root=storage_root,
        )
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="run_handoff_durable_import_from_plan",
        ) from exc


def _run_handoff_durable_import_from_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
    storage_root: str | Path,
) -> HandoffDurableImportRun:
    durable_request = _build_durable_import_request_from_handoff_plan(
        request,
        import_plan=import_plan,
    )
    if durable_request is None:
        return HandoffDurableImportRun(request=request, import_plan=import_plan)

    durable_run = import_measurement_record_from_request(
        durable_request,
        content_root=Path(import_plan.receiving_gate.package_dir),
        storage_root=storage_root,
    )
    return HandoffDurableImportRun(
        request=request,
        import_plan=import_plan,
        durable_import_request=durable_request,
        durable_import_run=durable_run,
    )


def _durable_import_block_reason(
    *,
    final_state: str,
    approval_state: str,
    import_plan_allowed: bool,
    import_plan_block_reason: str | None,
    durable_import_classification: str | None,
    rollback_performed: bool,
    partial_commit: bool,
) -> str | None:
    if final_state == "imported_handoff_measurement_record":
        return None
    if approval_state != "approved":
        return "request_not_approved"
    if not import_plan_allowed:
        return import_plan_block_reason or "import_plan_not_ready"
    if durable_import_classification == "rolled_back_after_import_failure" or rollback_performed:
        return "durable_import_rolled_back"
    if durable_import_classification == "import_failed_after_partial_commit" or partial_commit:
        return "durable_import_partial_commit"
    if durable_import_classification == "blocked_before_import":
        return "durable_import_blocked_before_import"
    if final_state == "ready_for_handoff_durable_import":
        return "durable_import_not_run"
    return "handoff_durable_import_blocked"


def build_durable_import_request_from_handoff_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
) -> MeasurementRecordDurableImportRequest | None:
    """Map a ready single-measurement handoff import plan into durable import."""

    try:
        return _build_durable_import_request_from_handoff_plan(
            request,
            import_plan=import_plan,
        )
    except ValueError as exc:
        raise promote_handoff_contract_error(
            exc,
            operation="build_durable_import_request_from_handoff_plan",
        ) from exc


def _build_durable_import_request_from_handoff_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
) -> MeasurementRecordDurableImportRequest | None:
    if request.requested_package_id != import_plan.package.package_id:
        raise ValueError("handoff durable import package id must match import plan package")
    if not request.approved or not import_plan.import_plan_allowed:
        return None
    if len(import_plan.measurement_plans) != 1:
        raise ValueError("handoff durable import requires exactly one planned measurement")

    measurement = import_plan.measurement_plans[0].measurement
    if request.measurement_record_id != measurement.measurement_record_id:
        raise ValueError("handoff durable import measurement id must match import plan")
    source = _durable_import_source_from_measurement(
        measurement,
        package_id=import_plan.package.package_id,
    )
    return MeasurementRecordDurableImportRequest(
        request_id=request.request_id,
        approval_state=request.approval_state,
        record_id=request.destination.record_id,
        record_dir=request.destination.record_dir,
        primary_data_path=request.destination.primary_data_path,
        writer_receipt_path=request.destination.writer_receipt_path,
        finalization_receipt_path=request.destination.finalization_receipt_path,
        read_model_path=request.destination.read_model_path,
        import_source=source,
        creation_source_kind="handoff",
        label=measurement.label,
        experiment_type=measurement.experiment_type,
    )


def _durable_import_source_from_measurement(
    measurement: HandoffMeasurement,
    *,
    package_id: str,
) -> MeasurementRecordImportSource:
    if measurement.declared_digest is None:
        raise ValueError("handoff measurement declared digest is required for durable import")
    if measurement.declared_size_bytes is None:
        raise ValueError("handoff measurement declared size is required for durable import")
    validate_positive_integer(
        measurement.observed_size_bytes,
        "handoff measurement observed_size_bytes",
    )
    if measurement.observed_size_bytes != measurement.declared_size_bytes:
        raise ValueError("handoff measurement declared size must match observed size")

    return MeasurementRecordImportSource(
        source_kind="handoff_package",
        source_id=package_id,
        source_item_id=measurement.measurement_record_id,
        content_ref=measurement.primary_package_path,
        declared_digest=measurement.declared_digest,
        size_bytes=measurement.observed_size_bytes,
        rows_recorded=measurement.primary_table.row_count,
        primary_data_format=measurement.primary_format,
    )
