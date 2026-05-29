"""Adapter from a ready handoff import plan to durable measurement-record import."""

from __future__ import annotations

import copy
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
from scopecat.handoff.import_plan import HandoffImportPlanRun, run_import_plan
from scopecat.handoff.package import HandoffMeasurement
from scopecat.measurement_records.durable_import import (
    MeasurementRecordDurableImportRequest,
    MeasurementRecordDurableImportRun,
    MeasurementRecordImportSource,
    import_measurement_record_from_request,
)

HANDOFF_DURABLE_IMPORT_SCHEMA = "scopecat.handoff_durable_import.v0"
HANDOFF_DURABLE_IMPORT_POLICY = {
    "workflow_authority": "approved_handoff_durable_import_request",
    "import_plan": "required_ready_single_measurement_import_plan",
    "destination_authority": "caller_declared_durable_record_destination",
    "source_mapping": "handoff_package_measurement_primary_data",
    "durable_import": "delegated_to_measurement_record_durable_import",
    "candidate_storage_acceptance": "not_performed",
    "batch_import": "not_performed",
    "linked_context_payload_import": "not_performed",
}
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
DOES_NOT_CLAIM = [
    "candidate_storage_acceptance_route",
    "batch_measurement_import",
    "existing_record_update",
    "linked_context_payload_import",
    "package_authenticity_or_trust",
    "conflict_resolution_beyond_durable_import_no_overwrite",
    "durable_schema_publication",
]


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

    def to_dict(self) -> dict[str, Any]:
        workflow_steps = [
            "run_import_plan",
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
            "handoff_durable_import_policy": copy.deepcopy(HANDOFF_DURABLE_IMPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": workflow_steps,
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "import_plan": {
                "classification": self.import_plan.classification,
                "allowed": self.import_plan.import_plan_allowed,
                "package_id": self.import_plan.package.package_id,
                "planned_measurement_ids": [
                    plan.measurement.measurement_record_id
                    for plan in self.import_plan.measurement_plans
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


def run_handoff_durable_import(
    source: dict[str, Any],
    *,
    package_dir: str | Path,
    storage_root: str | Path,
) -> HandoffDurableImportRun:
    """Run the full handoff package to durable measurement-record import route."""

    request, import_plan_source = _parse_source(source)
    import_plan = run_import_plan(import_plan_source, package_dir=package_dir)
    return run_handoff_durable_import_from_plan(
        request,
        import_plan=import_plan,
        storage_root=storage_root,
    )


def run_handoff_durable_import_from_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
    storage_root: str | Path,
) -> HandoffDurableImportRun:
    """Import one ready handoff-plan measurement through durable record storage."""

    durable_request = build_durable_import_request_from_handoff_plan(
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


def build_durable_import_request_from_handoff_plan(
    request: HandoffDurableImportRequest,
    *,
    import_plan: HandoffImportPlanRun,
) -> MeasurementRecordDurableImportRequest | None:
    """Map a ready single-measurement handoff import plan into durable import."""

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


def _parse_source(source: dict[str, Any]) -> tuple[HandoffDurableImportRequest, dict[str, Any]]:
    source = _require_mapping(source, "handoff durable import source")
    _require_keys(
        source,
        {
            "handoff_durable_import_schema",
            "handoff_durable_import_policy",
            "import_plan_source",
            "handoff_durable_import_request",
        },
        "handoff durable import source",
    )
    if source["handoff_durable_import_schema"] != HANDOFF_DURABLE_IMPORT_SCHEMA:
        raise ValueError("handoff durable import schema is unsupported")
    if source["handoff_durable_import_policy"] != HANDOFF_DURABLE_IMPORT_POLICY:
        raise ValueError("handoff durable import policy is unsupported")
    request = _parse_request(source["handoff_durable_import_request"])
    import_plan_source = copy.deepcopy(
        _require_mapping(source["import_plan_source"], "import_plan_source")
    )
    return request, import_plan_source


def _parse_request(source: Any) -> HandoffDurableImportRequest:
    request = _require_mapping(source, "handoff_durable_import_request")
    _require_keys(
        request,
        {
            "request_id",
            "approval_state",
            "requested_package_id",
            "measurement_record_id",
            "durable_record_destination",
        },
        "handoff_durable_import_request",
    )
    return HandoffDurableImportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        requested_package_id=_require_text(request, "requested_package_id"),
        measurement_record_id=_require_text(request, "measurement_record_id"),
        destination=_parse_destination(request["durable_record_destination"]),
    )


def _parse_destination(source: Any) -> HandoffDurableImportDestination:
    destination = _require_mapping(source, "durable_record_destination")
    _require_keys(
        destination,
        {
            "record_id",
            "record_dir",
            "primary_data_path",
            "writer_receipt_path",
            "finalization_receipt_path",
            "read_model_path",
        },
        "durable_record_destination",
    )
    return HandoffDurableImportDestination(
        record_id=_require_text(destination, "record_id"),
        record_dir=_require_text(destination, "record_dir"),
        primary_data_path=_require_text(destination, "primary_data_path"),
        writer_receipt_path=_require_text(destination, "writer_receipt_path"),
        finalization_receipt_path=_require_text(destination, "finalization_receipt_path"),
        read_model_path=_require_text(destination, "read_model_path"),
    )


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_keys(value: dict[str, Any], expected_keys: set[str], owner: str) -> None:
    if set(value) != expected_keys:
        raise ValueError(f"{owner} fields are unsupported")


def _require_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value
