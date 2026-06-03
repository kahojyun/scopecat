"""Export selected stored Measurement Records to handoff packages."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    HANDOFF_PACKAGE_CREATED_BY,
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
    validate_strict_child_path,
    validate_text,
)
from scopecat.handoff.writer import HandoffPackageWriteReceipt, write_package
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import path_under as _path_under
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.read_model_refresh import (
    READ_MODEL_REFRESH_POLICY,
    READ_MODEL_REFRESH_SCHEMA,
    MeasurementRecordReadModelRefreshRun,
    refresh_measurement_record_read_model,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_SCHEMA
from scopecat.measurement_records.read_view import READ_VIEW_POLICY, READ_VIEW_SCHEMA

SELECTED_RECORD_EXPORT_POLICY = {
    "workflow_authority": "approved_selected_measurement_record_export_request",
    "record_authority": "stored_measurement_record_read_model_and_receipts",
    "source_authority": "caller_provided_storage_root_plus_record_local_paths",
    "package_authority": "delegated_handoff_package_writer",
    "primary_data_materialization": "copy_record_local_primary_data",
    "linked_context_materialization": "declared_reference_or_payload",
    "portable_export_boundary": "handoff_package_manifest_primary_data_and_declared_context",
    "record_storage_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "package_import_acceptance": "not_performed",
}
DOES_NOT_CLAIM = [
    "shared_measurement_schema",
    "read_model_refresh",
    "existing_record_update",
    "linked_context_payload_import",
    "reference_resolution",
    "schema_inference",
    "scientific_validity",
    "archive_creation",
    "external_authenticity_or_trust_validation",
    "package_import_acceptance",
]
APPROVAL_STATES = {"approved", "rejected", "needs_review"}

PRE_EXPORT_READ_MODEL_REFRESH_POLICY = {
    "workflow_authority": "approved_selected_measurement_record_export_request",
    "freshness_authority": "selected_record_export_read_model_freshness_review",
    "refresh_authority": "delegated_measurement_record_read_model_refresh",
    "export_authority": "selected_measurement_record_export",
    "user_visible_refresh": "transparent_pre_export_projection_refresh",
    "refresh_scope": "missing_invalid_or_stale_read_model_only",
    "record_storage_mutation": "delegated_read_model_atomic_replace_only",
    "package_write": "after_fresh_read_model_evidence",
    "package_import_acceptance": "not_performed",
}


@dataclass(frozen=True)
class SelectedMeasurementRecordExportLinkedContext:
    """Selected-record linked context to expose in the handoff manifest."""

    link_id: str
    kind: str
    label: str
    relation: str
    reason: str
    context_reference: dict[str, str] | None = None
    source_path: str | None = None
    package_path: str | None = None
    expected_digest: str | None = None
    expected_size_bytes: int | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.link_id, "selected record export linked context link_id")
        validate_public_identifier(self.kind, "selected record export linked context kind")
        validate_text(self.label, "selected record export linked context label")
        validate_public_identifier(self.relation, "selected record export linked context relation")
        validate_text(self.reason, "selected record export linked context reason")
        if self.context_reference is not None and not isinstance(self.context_reference, dict):
            raise ValueError("selected record export context_reference must be an object")
        payload_fields = (
            self.source_path,
            self.package_path,
            self.expected_digest,
            self.expected_size_bytes,
        )
        has_payload = any(value is not None for value in payload_fields)
        if has_payload and not all(value is not None for value in payload_fields):
            raise ValueError("selected record export linked context payload fields are paired")
        if self.source_path is not None:
            validate_relative_path(
                self.source_path,
                "selected record export linked context source_path",
            )
        if self.package_path is not None:
            validate_strict_child_path(
                self.package_path,
                "context",
                "selected record export linked context package_path",
            )
        if self.expected_digest is not None:
            validate_sha256_digest(
                self.expected_digest,
                "selected record export linked context expected_digest",
            )
        if self.expected_size_bytes is not None:
            validate_positive_integer(
                self.expected_size_bytes,
                "selected record export linked context expected_size_bytes",
            )

    @property
    def packages_payload(self) -> bool:
        return self.source_path is not None

    def to_request_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "relation": self.relation,
            "reason": self.reason,
        }
        if self.context_reference is not None:
            item["context_reference"] = copy.deepcopy(self.context_reference)
        if self.packages_payload:
            item["source_path"] = self.source_path
            item["package_path"] = self.package_path
            item["expected_digest"] = self.expected_digest
            item["expected_size_bytes"] = self.expected_size_bytes
        return item

    def to_writer_item(self, *, measurement_record_id: str) -> dict[str, Any]:
        item = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "package_path": self.package_path,
            "include_status": "included_by_user" if self.packages_payload else "visible_excluded",
            "relation": self.relation,
            "authority": MANIFEST_AUTHORITY,
            "package_state": "packaged"
            if self.packages_payload
            else "not_packaged_visible_reference",
            "reason": None if self.packages_payload else self.reason,
            "linked_measurement_record_ids": [measurement_record_id],
        }
        if self.packages_payload:
            item["source_path"] = self.source_path
            item["expected_digest"] = self.expected_digest
            item["expected_size_bytes"] = self.expected_size_bytes
        if self.context_reference is not None:
            item["context_reference"] = copy.deepcopy(self.context_reference)
        return item


@dataclass(frozen=True)
class SelectedMeasurementRecordBatchExportRecord:
    """One stored Measurement Record selected for a batch handoff export."""

    record_id: str
    record_dir: str
    read_model_path: str
    legacy_data_id: int
    target: str
    declared_preview_metadata: dict[str, Any]
    linked_context: tuple[SelectedMeasurementRecordExportLinkedContext, ...] = ()

    def __post_init__(self) -> None:
        validate_public_identifier(self.record_id, "selected record export record_id")
        validate_relative_path(self.record_dir, "selected record export record_dir")
        validate_relative_path(self.read_model_path, "selected record export read_model_path")
        if self.read_model_path != f"{self.record_dir}/record-read-model.json":
            raise ValueError("selected record export read_model_path must be record-local")
        if not isinstance(self.legacy_data_id, int) or isinstance(self.legacy_data_id, bool):
            raise ValueError("selected record export legacy_data_id must be an integer")
        if self.legacy_data_id < 0:
            raise ValueError("selected record export legacy_data_id must be non-negative")
        validate_public_identifier(self.target, "selected record export target")
        if not isinstance(self.declared_preview_metadata, dict):
            raise ValueError("selected record export declared_preview_metadata must be an object")
        validate_handoff_preview_ready_metadata(
            self.declared_preview_metadata,
            primary_path=f"measurements/{self.record_id}/primary.csv",
            owner="selected record export preview",
        )
        for item in self.linked_context:
            if item.source_path is not None:
                _validate_strict_child_path(
                    item.source_path,
                    self.record_dir,
                    "selected record export linked context source_path",
                )

    @property
    def package_primary_path(self) -> str:
        return f"measurements/{self.record_id}/primary.csv"

    def to_record_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "read_model_path": self.read_model_path,
            "legacy_data_id": self.legacy_data_id,
            "target": self.target,
            "declared_preview_metadata": copy.deepcopy(self.declared_preview_metadata),
            "linked_context": [item.to_request_item() for item in self.linked_context],
        }


@dataclass(frozen=True)
class SelectedMeasurementRecordExportRequest:
    """Approved request to export one stored record through the handoff writer."""

    request_id: str
    approval_state: str
    package_id: str
    display_name: str
    source_export_summary_id: str
    display_path: str
    record_id: str
    record_dir: str
    read_model_path: str
    legacy_data_id: int
    target: str
    declared_preview_metadata: dict[str, Any]
    linked_context: tuple[SelectedMeasurementRecordExportLinkedContext, ...] = ()

    def __post_init__(self) -> None:
        _validate_selected_export_identity(
            request_id=self.request_id,
            approval_state=self.approval_state,
            package_id=self.package_id,
            display_name=self.display_name,
            source_export_summary_id=self.source_export_summary_id,
            display_path=self.display_path,
        )
        self.to_batch_record()

    def to_batch_record(self) -> SelectedMeasurementRecordBatchExportRecord:
        return SelectedMeasurementRecordBatchExportRecord(
            record_id=self.record_id,
            record_dir=self.record_dir,
            read_model_path=self.read_model_path,
            legacy_data_id=self.legacy_data_id,
            target=self.target,
            declared_preview_metadata=copy.deepcopy(self.declared_preview_metadata),
            linked_context=self.linked_context,
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def package_dir(self) -> str:
        return self.package_id

    @property
    def manifest_path(self) -> str:
        return f"{self.package_dir}/package-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "package_id": self.package_id,
            "display_name": self.display_name,
            "source_export_summary_id": self.source_export_summary_id,
            "display_path": self.display_path,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "read_model_path": self.read_model_path,
            "legacy_data_id": self.legacy_data_id,
            "target": self.target,
            "declared_preview_metadata": copy.deepcopy(self.declared_preview_metadata),
            "linked_context": [item.to_request_item() for item in self.linked_context],
        }


@dataclass(frozen=True)
class SelectedMeasurementRecordBatchExportRequest:
    """Approved request to export selected stored records into one package."""

    request_id: str
    approval_state: str
    package_id: str
    display_name: str
    source_export_summary_id: str
    display_path: str
    records: tuple[SelectedMeasurementRecordBatchExportRecord, ...]

    def __post_init__(self) -> None:
        _validate_selected_export_identity(
            request_id=self.request_id,
            approval_state=self.approval_state,
            package_id=self.package_id,
            display_name=self.display_name,
            source_export_summary_id=self.source_export_summary_id,
            display_path=self.display_path,
        )
        if not self.records:
            raise ValueError("selected record batch export requires records")
        seen_ids: set[str] = set()
        for record in self.records:
            if record.record_id in seen_ids:
                raise ValueError(
                    f"duplicate selected record batch export record_id: {record.record_id}"
                )
            seen_ids.add(record.record_id)

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def package_dir(self) -> str:
        return self.package_id

    @property
    def manifest_path(self) -> str:
        return f"{self.package_dir}/package-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "package_id": self.package_id,
            "display_name": self.display_name,
            "source_export_summary_id": self.source_export_summary_id,
            "display_path": self.display_path,
            "records": [record.to_record_dict() for record in self.records],
        }


@dataclass(frozen=True)
class SelectedMeasurementRecordExportRun:
    """Local review run for selected-record package export."""

    request: SelectedMeasurementRecordExportRequest
    storage_root: Path
    package_root: Path
    read_model: dict[str, Any] | None = None
    record_manifest: dict[str, Any] | None = None
    writer_receipt: dict[str, Any] | None = None
    package_write: HandoffPackageWriteReceipt | None = None
    export_error: str | None = None

    @property
    def exported(self) -> bool:
        return self.classification == "exported_selected_measurement_record"

    @property
    def classification(self) -> str:
        if self.export_error is not None:
            return "blocked_before_export"
        if not self.request.approved:
            return "blocked_before_export"
        return "exported_selected_measurement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_selected_record_export_receipt",
            "selected_record_export_policy": copy.deepcopy(SELECTED_RECORD_EXPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_selected_record_export_request",
                    *([] if not self.request.approved else ["read_record_read_model"]),
                    *([] if self.record_manifest is None else ["read_record_creation_manifest"]),
                    *([] if self.writer_receipt is None else ["read_record_writer_receipt"]),
                    *([] if self.package_write is None else ["write_handoff_package"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "record": _record_ref(self.read_model, self.record_manifest, self.writer_receipt),
            "package_write": None if self.package_write is None else self.package_write.to_dict(),
            "export_review": _export_review(
                classification=self.classification,
                approved=self.request.approved,
                export_error=self.export_error,
                package_written=self.package_write is not None,
            ),
            "read_model_freshness_review": _read_model_freshness_review(
                classification=self.classification,
                approved=self.request.approved,
                export_error=self.export_error,
                package_written=self.package_write is not None,
            ),
            "export": {
                "performed": self.exported,
                "storage_root": str(self.storage_root),
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir if self.exported else None,
                "export_error": self.export_error,
            },
        }


@dataclass(frozen=True)
class SelectedMeasurementRecordPreflightExportRun:
    """Transparent pre-export read-model refresh followed by selected export."""

    request: SelectedMeasurementRecordExportRequest
    storage_root: Path
    package_root: Path
    initial_export: SelectedMeasurementRecordExportRun
    refresh_run: MeasurementRecordReadModelRefreshRun | None = None
    final_export: SelectedMeasurementRecordExportRun | None = None
    preflight_error: str | None = None

    @property
    def export_run(self) -> SelectedMeasurementRecordExportRun:
        return self.final_export or self.initial_export

    @property
    def exported(self) -> bool:
        return self.export_run.exported

    @property
    def classification(self) -> str:
        if self.exported:
            return "exported_selected_measurement_record_after_preflight"
        if self.preflight_error is not None:
            return "blocked_before_export_refresh_failed"
        if self.refresh_run is not None and not self.refresh_run.refreshed:
            return "blocked_before_export_refresh_failed"
        if self.refresh_run is None:
            return "blocked_or_exported_without_preflight_refresh"
        return "blocked_before_export_after_preflight_refresh"

    def to_dict(self) -> dict[str, Any]:
        refresh_performed = self.refresh_run is not None and self.refresh_run.refreshed
        return {
            "artifact_posture": "local_selected_record_preflight_export_receipt",
            "pre_export_read_model_refresh_policy": copy.deepcopy(
                PRE_EXPORT_READ_MODEL_REFRESH_POLICY
            ),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "run_initial_selected_record_export_preflight",
                    *([] if self.refresh_run is None else ["run_read_model_refresh"]),
                    *([] if self.final_export is None else ["retry_selected_record_export"]),
                ],
                "does_not_claim": [
                    "primary_data_repair",
                    "manifest_replacement",
                    "receipt_mutation",
                    "package_import_acceptance",
                    "external_authenticity_or_trust_validation",
                    "gui_review_state",
                ],
            },
            "request": self.request.to_dict(),
            "initial_export": self.initial_export.to_dict(),
            "refresh": None if self.refresh_run is None else self.refresh_run.to_dict(),
            "final_export": None if self.final_export is None else self.final_export.to_dict(),
            "preflight_review": {
                "classification": self.classification,
                "refresh_performed": refresh_performed,
                "package_written": self.exported,
                "block_reason": _preflight_block_reason(self),
                "next_action": _preflight_next_action(self),
                "retry_requires": _preflight_retry_requirement(self),
                "preflight_error": self.preflight_error,
            },
            "export": {
                "performed": self.exported,
                "storage_root": str(self.storage_root),
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir if self.exported else None,
                "export_error": self.export_run.export_error,
            },
        }


@dataclass(frozen=True)
class _SelectedRecordExportEvidence:
    record: SelectedMeasurementRecordBatchExportRecord
    read_model: dict[str, Any]
    record_manifest: dict[str, Any]
    writer_receipt: dict[str, Any]


@dataclass(frozen=True)
class SelectedMeasurementRecordBatchExportRun:
    """Local review run for selected-record batch package export."""

    request: SelectedMeasurementRecordBatchExportRequest
    storage_root: Path
    package_root: Path
    records: tuple[_SelectedRecordExportEvidence, ...] = ()
    package_write: HandoffPackageWriteReceipt | None = None
    export_error: str | None = None

    @property
    def exported(self) -> bool:
        return self.classification == "exported_selected_measurement_record_batch"

    @property
    def classification(self) -> str:
        if self.export_error is not None:
            return "blocked_before_export"
        if not self.request.approved:
            return "blocked_before_export"
        return "exported_selected_measurement_record_batch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_selected_record_batch_export_receipt",
            "selected_record_export_policy": copy.deepcopy(SELECTED_RECORD_EXPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_selected_record_batch_export_request",
                    *([] if not self.request.approved else ["read_record_read_models"]),
                    *([] if not self.records else ["read_record_creation_manifests"]),
                    *([] if not self.records else ["read_record_writer_receipts"]),
                    *([] if self.package_write is None else ["write_handoff_package"]),
                ],
                "does_not_claim": [*DOES_NOT_CLAIM, "batch_durable_import"],
            },
            "request": self.request.to_dict(),
            "records": [
                _record_ref(record.read_model, record.record_manifest, record.writer_receipt)
                for record in self.records
            ],
            "package_write": None if self.package_write is None else self.package_write.to_dict(),
            "export_review": _export_review(
                classification=self.classification,
                approved=self.request.approved,
                export_error=self.export_error,
                package_written=self.package_write is not None,
            ),
            "read_model_freshness_review": _read_model_freshness_review(
                classification=self.classification,
                approved=self.request.approved,
                export_error=self.export_error,
                package_written=self.package_write is not None,
            ),
            "export": {
                "performed": self.exported,
                "storage_root": str(self.storage_root),
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir if self.exported else None,
                "export_error": self.export_error,
            },
        }


def export_selected_measurement_record(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordExportRun:
    """Export one stored Measurement Record from a raw route-local source."""

    request = _parse_source(source)
    return export_selected_measurement_record_from_request(
        request,
        storage_root=storage_root,
        package_root=package_root,
    )


def export_selected_measurement_record_from_request(
    request: SelectedMeasurementRecordExportRequest,
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordExportRun:
    """Export one stored Measurement Record using existing package writer behavior."""

    storage = _existing_directory_root(Path(storage_root), "selected record export storage root")
    packages = _existing_directory_root(Path(package_root), "selected record export package root")
    if not request.approved:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
        )

    try:
        read_model = _read_read_model(storage, request)
        manifest = _read_json(
            storage, f"{request.record_dir}/record-manifest.json", "record manifest"
        )
        writer_receipt_path = _writer_receipt_path(read_model)
        writer_receipt = _read_json(storage, writer_receipt_path, "writer receipt")
        writer_source = _writer_source(request, read_model, manifest, writer_receipt)
        package_write = write_package(writer_source, source_root=storage, package_root=packages)
    except ValueError as exc:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            export_error=str(exc),
        )

    return SelectedMeasurementRecordExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        read_model=read_model,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        package_write=package_write,
    )


def export_selected_measurement_record_with_preflight_refresh(
    request: SelectedMeasurementRecordExportRequest,
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordPreflightExportRun:
    """Export a selected record, transparently refreshing stale read-model evidence."""

    storage = _existing_directory_root(
        Path(storage_root),
        "selected record preflight export storage root",
    )
    packages = _existing_directory_root(
        Path(package_root),
        "selected record preflight export package root",
    )
    initial_export = export_selected_measurement_record_from_request(
        request,
        storage_root=storage,
        package_root=packages,
    )
    if initial_export.exported or not _should_refresh_before_export(initial_export):
        return SelectedMeasurementRecordPreflightExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            initial_export=initial_export,
        )

    try:
        refresh_run = refresh_measurement_record_read_model(
            _pre_export_refresh_source(request, storage),
            storage_root=storage,
        )
    except ValueError as exc:
        return SelectedMeasurementRecordPreflightExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            initial_export=initial_export,
            preflight_error=str(exc),
        )
    if not refresh_run.refreshed:
        return SelectedMeasurementRecordPreflightExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            initial_export=initial_export,
            refresh_run=refresh_run,
        )

    final_export = export_selected_measurement_record_from_request(
        request,
        storage_root=storage,
        package_root=packages,
    )
    return SelectedMeasurementRecordPreflightExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        initial_export=initial_export,
        refresh_run=refresh_run,
        final_export=final_export,
    )


def export_selected_measurement_record_batch(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordBatchExportRun:
    """Export selected stored Measurement Records from a raw route-local source."""

    request = _parse_batch_source(source)
    return export_selected_measurement_record_batch_from_request(
        request,
        storage_root=storage_root,
        package_root=package_root,
    )


def export_selected_measurement_record_batch_from_request(
    request: SelectedMeasurementRecordBatchExportRequest,
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordBatchExportRun:
    """Export selected stored Measurement Records using the package writer."""

    storage = _existing_directory_root(Path(storage_root), "selected record export storage root")
    packages = _existing_directory_root(Path(package_root), "selected record export package root")
    if not request.approved:
        return SelectedMeasurementRecordBatchExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
        )

    try:
        records = tuple(_read_record_export_evidence(storage, record) for record in request.records)
        writer_source = _batch_writer_source(request, records)
        package_write = write_package(writer_source, source_root=storage, package_root=packages)
    except ValueError as exc:
        return SelectedMeasurementRecordBatchExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            export_error=str(exc),
        )

    return SelectedMeasurementRecordBatchExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        records=records,
        package_write=package_write,
    )


def _parse_source(source: dict[str, Any]) -> SelectedMeasurementRecordExportRequest:
    if source.get("selected_record_export_policy") != SELECTED_RECORD_EXPORT_POLICY:
        raise ValueError("selected record export policy is unsupported")
    request = _require_dict(source, "selected_record_export_request")
    linked_context = tuple(
        _parse_linked_context(item)
        for item in _optional_list(request, "linked_context", default=[])
    )
    return SelectedMeasurementRecordExportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        package_id=_require_text(request, "package_id"),
        display_name=_require_text(request, "display_name"),
        source_export_summary_id=_require_text(request, "source_export_summary_id"),
        display_path=_require_text(request, "display_path"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        read_model_path=_require_text(request, "read_model_path"),
        legacy_data_id=_require_int(request, "legacy_data_id"),
        target=_require_text(request, "target"),
        declared_preview_metadata=_require_dict(request, "declared_preview_metadata"),
        linked_context=linked_context,
    )


def _validate_selected_export_identity(
    *,
    request_id: str,
    approval_state: str,
    package_id: str,
    display_name: str,
    source_export_summary_id: str,
    display_path: str,
) -> None:
    validate_public_identifier(request_id, "selected record export request_id")
    if approval_state not in APPROVAL_STATES:
        raise ValueError("selected record export approval_state is unsupported")
    identity = {
        "package_id": package_id,
        "display_name": display_name,
        "created_by": HANDOFF_PACKAGE_CREATED_BY,
        "source_export_summary_id": source_export_summary_id,
        "display_path": display_path,
        "local_path_redacted": True,
    }
    validate_handoff_package_identity(identity, display_path="required")


def _parse_batch_source(source: dict[str, Any]) -> SelectedMeasurementRecordBatchExportRequest:
    if source.get("selected_record_export_policy") != SELECTED_RECORD_EXPORT_POLICY:
        raise ValueError("selected record batch export policy is unsupported")
    request = _require_dict(source, "selected_record_batch_export_request")
    return SelectedMeasurementRecordBatchExportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        package_id=_require_text(request, "package_id"),
        display_name=_require_text(request, "display_name"),
        source_export_summary_id=_require_text(request, "source_export_summary_id"),
        display_path=_require_text(request, "display_path"),
        records=tuple(
            _parse_batch_record(item) for item in _optional_list(request, "records", default=[])
        ),
    )


def _parse_batch_record(item: Any) -> SelectedMeasurementRecordBatchExportRecord:
    item = _require_mapping(item, "selected record batch export record")
    linked_context = tuple(
        _parse_linked_context(context)
        for context in _optional_list(item, "linked_context", default=[])
    )
    return SelectedMeasurementRecordBatchExportRecord(
        record_id=_require_text(item, "record_id"),
        record_dir=_require_text(item, "record_dir"),
        read_model_path=_require_text(item, "read_model_path"),
        legacy_data_id=_require_int(item, "legacy_data_id"),
        target=_require_text(item, "target"),
        declared_preview_metadata=_require_dict(item, "declared_preview_metadata"),
        linked_context=linked_context,
    )


def _parse_linked_context(item: Any) -> SelectedMeasurementRecordExportLinkedContext:
    item = _require_mapping(item, "selected record export linked_context item")
    context_reference = item.get("context_reference")
    if context_reference is not None:
        context_reference = _require_mapping(
            context_reference,
            "selected record export context_reference",
        )
    return SelectedMeasurementRecordExportLinkedContext(
        link_id=_require_text(item, "link_id"),
        kind=_require_text(item, "kind"),
        label=_require_text(item, "label"),
        relation=_require_text(item, "relation"),
        reason=_require_text(item, "reason"),
        context_reference=copy.deepcopy(context_reference),
        source_path=_optional_text(item, "source_path"),
        package_path=_optional_text(item, "package_path"),
        expected_digest=_optional_text(item, "expected_digest"),
        expected_size_bytes=_optional_int(item, "expected_size_bytes"),
    )


def _read_record_export_evidence(
    storage: Path,
    record: SelectedMeasurementRecordBatchExportRecord,
) -> _SelectedRecordExportEvidence:
    read_model = _read_read_model(storage, record)
    manifest = _read_json(storage, f"{record.record_dir}/record-manifest.json", "record manifest")
    writer_receipt_path = _writer_receipt_path(read_model)
    writer_receipt = _read_json(storage, writer_receipt_path, "writer receipt")
    return _SelectedRecordExportEvidence(
        record=record,
        read_model=read_model,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
    )


def _package_write_policy() -> dict[str, str]:
    return {
        "write_authority": "approved_handoff_package_write_request",
        "source_authority": "caller_provided_source_root_plus_declared_relative_paths",
        "destination_authority": "caller_provided_package_root_plus_declared_package_paths",
        "package_format": "directory_manifest",
        "overwrite_behavior": "no_overwrite",
        "checksum_algorithm": "sha256",
        "primary_data_materialization": "copy_declared_primary_data",
        "linked_context_materialization": "declared_reference_or_payload",
        "archive_creation": "not_performed",
        "package_acceptance": "not_performed",
        "source_mutation": "not_performed",
        "schema_inference": "not_performed",
        "recursive_relation_traversal": "not_performed",
        "gui_workflow": "not_defined",
        "shared_measurement_schema": "not_defined",
    }


def _package_write_identity(
    request: SelectedMeasurementRecordExportRequest | SelectedMeasurementRecordBatchExportRequest,
) -> dict[str, Any]:
    return {
        "package_id": request.package_id,
        "display_name": request.display_name,
        "created_by": HANDOFF_PACKAGE_CREATED_BY,
        "source_export_summary_id": request.source_export_summary_id,
        "display_path": request.display_path,
        "local_path_redacted": True,
    }


def _package_write_request(
    request: SelectedMeasurementRecordExportRequest | SelectedMeasurementRecordBatchExportRequest,
) -> dict[str, str]:
    return {
        "request_id": request.request_id,
        "approval_state": "approved",
        "package_dir": request.package_dir,
        "manifest_path": request.manifest_path,
        "collision_policy": "no_overwrite",
    }


def _measurement_writer_item(evidence: _SelectedRecordExportEvidence) -> dict[str, Any]:
    record = _require_dict(evidence.record_manifest, "record")
    primary_data = _require_dict(evidence.read_model, "primary_data")
    primary_path = _require_text(primary_data, "path")
    validate_relative_path(primary_path, "selected record export primary data path")
    _validate_strict_child_path(
        primary_path,
        evidence.record.record_dir,
        "selected record export primary data path",
    )
    digest = _require_text(primary_data, "digest")
    size_bytes = _require_int(primary_data, "size_bytes")
    label = record.get("label") or evidence.record.record_id
    experiment_type = record.get("experiment_type") or "unspecified"
    validate_public_identifier(experiment_type, "selected record export experiment_type")
    _validate_record_continuity(
        evidence.record,
        evidence.read_model,
        evidence.record_manifest,
        evidence.writer_receipt,
    )

    package_primary_path = evidence.record.package_primary_path
    primary = {
        "kind": "primary_data",
        "label": "Stored primary data",
        "source_path": primary_path,
        "expected_digest": digest,
        "expected_size_bytes": size_bytes,
        "package_path": package_primary_path,
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": MANIFEST_AUTHORITY,
        "format": "csv_table",
        "package_state": "packaged",
        "reason": None,
    }
    return {
        "measurement_record_id": evidence.record.record_id,
        "legacy_data_id": evidence.record.legacy_data_id,
        "label": label,
        "experiment_type": experiment_type,
        "target": evidence.record.target,
        "primary_data": primary,
        "declared_preview_metadata": copy.deepcopy(evidence.record.declared_preview_metadata),
        "default_bundle": [
            {
                "item_id": f"{evidence.record.record_id}-primary",
                "kind": "primary_data",
                "label": primary["label"],
                "package_path": package_primary_path,
                "include_status": "included_by_default",
                "relation": "selected_measurement_source",
                "authority": MANIFEST_AUTHORITY,
                "package_state": "packaged",
                "reason": None,
            }
        ],
    }


def _batch_writer_source(
    request: SelectedMeasurementRecordBatchExportRequest,
    records: tuple[_SelectedRecordExportEvidence, ...],
) -> dict[str, Any]:
    return {
        "package_write_policy": _package_write_policy(),
        "package_write_request": _package_write_request(request),
        "package_identity": _package_write_identity(request),
        "selected_measurements": [_measurement_writer_item(record) for record in records],
        "linked_context": [
            item.to_writer_item(measurement_record_id=record.record.record_id)
            for record in records
            for item in record.record.linked_context
        ],
    }


def _writer_source(
    request: SelectedMeasurementRecordExportRequest,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
) -> dict[str, Any]:
    evidence = _SelectedRecordExportEvidence(
        record=request.to_batch_record(),
        read_model=read_model,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
    )
    return {
        "package_write_policy": _package_write_policy(),
        "package_write_request": _package_write_request(request),
        "package_identity": _package_write_identity(request),
        "selected_measurements": [_measurement_writer_item(evidence)],
        "linked_context": [
            item.to_writer_item(measurement_record_id=evidence.record.record_id)
            for item in evidence.record.linked_context
        ],
    }


def _validate_record_continuity(
    request: SelectedMeasurementRecordBatchExportRecord,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
) -> None:
    read_model_record = _require_dict(read_model, "record")
    manifest_record = _require_dict(manifest, "record")
    writer_record = _require_dict(writer_receipt, "record")
    if read_model_record.get("record_id") != request.record_id:
        raise ValueError("selected record export read model record_id must match request")
    if read_model_record.get("record_dir") != request.record_dir:
        raise ValueError("selected record export read model record_dir must match request")
    if read_model_record.get("lifecycle_state") != "complete":
        raise ValueError("selected record export requires complete read model lifecycle")
    if manifest_record.get("record_id") != request.record_id:
        raise ValueError("selected record export manifest record_id must match request")
    if writer_record.get("record_id") != request.record_id:
        raise ValueError("selected record export writer receipt record_id must match request")
    if writer_record.get("record_dir") != request.record_dir:
        raise ValueError("selected record export writer receipt record_dir must match request")
    writer_primary = _require_dict(writer_receipt, "primary_data")
    model_primary = _require_dict(read_model, "primary_data")
    if writer_primary.get("path") != model_primary.get("path"):
        raise ValueError("selected record export primary data path must match writer receipt")
    if writer_primary.get("digest") != model_primary.get("digest"):
        raise ValueError("selected record export primary data digest must match writer receipt")
    if writer_primary.get("size_bytes") != model_primary.get("size_bytes"):
        raise ValueError("selected record export primary data size must match writer receipt")


def _read_read_model(
    root: Path, request: SelectedMeasurementRecordBatchExportRecord
) -> dict[str, Any]:
    read_model = _read_json(root, request.read_model_path, "record read model")
    if read_model.get("schema") != READ_MODEL_SCHEMA:
        raise ValueError("selected record export read model schema is unsupported")
    return read_model


def _writer_receipt_path(read_model: dict[str, Any]) -> str:
    sources = _require_dict(read_model, "sources")
    writer = _require_dict(sources, "writer_receipt")
    return _require_text(writer, "path")


def _export_review(
    *,
    classification: str,
    approved: bool,
    export_error: str | None,
    package_written: bool,
) -> dict[str, Any]:
    block_reason = _export_block_reason(approved=approved, export_error=export_error)
    return {
        "classification": classification,
        "package_written": package_written,
        "block_reason": block_reason,
        "next_action": _export_next_action(
            classification=classification,
            block_reason=block_reason,
        ),
        "retry_requires": _export_retry_requirement(block_reason),
    }


def _export_block_reason(*, approved: bool, export_error: str | None) -> str | None:
    if export_error is None:
        return None if approved else "request_not_approved"
    if "target already exists" in export_error:
        return "package_destination_collision"
    if "is required" in export_error:
        return "missing_record_evidence"
    if "must match writer receipt" in export_error or "must match request" in export_error:
        return "record_evidence_mismatch"
    if "requires complete read model lifecycle" in export_error:
        return "record_not_complete"
    if "must stay under record_dir" in export_error:
        return "record_path_scope_violation"
    return "export_validation_error"


def _export_next_action(*, classification: str, block_reason: str | None) -> str:
    if classification in {
        "exported_selected_measurement_record",
        "exported_selected_measurement_record_batch",
    }:
        return "transfer_package_for_receiving_review"
    if block_reason == "request_not_approved":
        return "approve_selected_record_export_request"
    if block_reason == "package_destination_collision":
        return "choose_new_package_destination_before_retry"
    if block_reason in {
        "missing_record_evidence",
        "record_evidence_mismatch",
        "record_not_complete",
        "record_path_scope_violation",
    }:
        return "review_record_evidence_before_export_retry"
    return "review_selected_record_export_error_before_retry"


def _export_retry_requirement(block_reason: str | None) -> str | None:
    if block_reason is None:
        return None
    if block_reason == "request_not_approved":
        return "approved_selected_record_export_request"
    if block_reason == "package_destination_collision":
        return "fresh_package_destination_or_removed_collision"
    if block_reason in {
        "missing_record_evidence",
        "record_evidence_mismatch",
        "record_not_complete",
        "record_path_scope_violation",
    }:
        return "fresh_matching_record_read_model_manifest_and_writer_receipt"
    return "reviewed_export_input_correction"


def _read_model_freshness_review(
    *,
    classification: str,
    approved: bool,
    export_error: str | None,
    package_written: bool,
) -> dict[str, Any]:
    block_reason = _read_model_freshness_block_reason(
        approved=approved,
        export_error=export_error,
    )
    return {
        "classification": _read_model_freshness_classification(
            classification=classification,
            block_reason=block_reason,
            package_written=package_written,
        ),
        "read_model_refresh": "not_performed",
        "block_reason": block_reason,
        "next_action": _read_model_freshness_next_action(
            classification=classification,
            block_reason=block_reason,
        ),
        "retry_requires": _read_model_freshness_retry_requirement(block_reason),
        "does_not_claim": [
            "read_model_refresh",
            "automatic_projection",
            "storage_mutation",
            "record_repair",
        ],
    }


def _read_model_freshness_block_reason(
    *,
    approved: bool,
    export_error: str | None,
) -> str | None:
    if export_error is None:
        return None if approved else "request_not_approved"
    if "target already exists" in export_error:
        return "package_destination_collision"
    if "record read model is required" in export_error:
        return "missing_read_model"
    if (
        "read model schema is unsupported" in export_error
        or "record read model must be JSON" in export_error
        or "record read model must be an object" in export_error
    ):
        return "invalid_read_model"
    if (
        "read model record_id must match request" in export_error
        or "read model record_dir must match request" in export_error
        or "must match writer receipt" in export_error
    ):
        return "stale_read_model"
    if "requires complete read model lifecycle" in export_error:
        return "read_model_not_complete"
    if "is required" in export_error:
        return "missing_record_evidence"
    if "must stay under record_dir" in export_error:
        return "read_model_scope_invalid"
    if "must match request" in export_error:
        return "record_evidence_mismatch"
    return "read_model_freshness_unresolved"


def _read_model_freshness_classification(
    *,
    classification: str,
    block_reason: str | None,
    package_written: bool,
) -> str:
    if package_written:
        return "fresh_read_model_evidence"
    if block_reason is None and classification in {
        "exported_selected_measurement_record",
        "exported_selected_measurement_record_batch",
    }:
        return "fresh_read_model_evidence"
    if block_reason == "request_not_approved":
        return "not_checked_before_approval"
    if block_reason == "package_destination_collision":
        return "fresh_read_model_evidence_not_exported"
    if block_reason == "missing_read_model":
        return "missing_read_model_requires_projection"
    if block_reason == "invalid_read_model":
        return "invalid_read_model_requires_projection"
    if block_reason == "stale_read_model":
        return "stale_read_model_requires_refresh"
    if block_reason == "read_model_not_complete":
        return "read_model_not_complete_for_export"
    if block_reason in {
        "missing_record_evidence",
        "read_model_scope_invalid",
        "record_evidence_mismatch",
    }:
        return "read_model_freshness_not_exportable"
    return "read_model_freshness_unresolved"


def _read_model_freshness_next_action(
    *,
    classification: str,
    block_reason: str | None,
) -> str:
    if classification in {
        "exported_selected_measurement_record",
        "exported_selected_measurement_record_batch",
    }:
        return "continue_selected_record_export"
    if block_reason == "request_not_approved":
        return "approve_selected_record_export_request"
    if block_reason == "package_destination_collision":
        return "choose_new_package_destination_before_retry"
    if block_reason in {"missing_read_model", "invalid_read_model", "stale_read_model"}:
        return "project_or_refresh_read_model_before_selected_record_export"
    if block_reason in {
        "read_model_not_complete",
        "missing_record_evidence",
        "read_model_scope_invalid",
        "record_evidence_mismatch",
    }:
        return "review_record_evidence_before_export_retry"
    return "review_selected_record_export_error_before_retry"


def _read_model_freshness_retry_requirement(block_reason: str | None) -> str | None:
    if block_reason is None:
        return None
    if block_reason == "request_not_approved":
        return "approved_selected_record_export_request"
    if block_reason == "package_destination_collision":
        return "fresh_package_destination_or_removed_collision"
    if block_reason in {"missing_read_model", "invalid_read_model", "stale_read_model"}:
        return "fresh_projected_record_read_model"
    if block_reason in {
        "read_model_not_complete",
        "missing_record_evidence",
        "read_model_scope_invalid",
        "record_evidence_mismatch",
    }:
        return "fresh_matching_record_read_model_manifest_and_writer_receipt"
    return "reviewed_export_input_correction"


def _should_refresh_before_export(run: SelectedMeasurementRecordExportRun) -> bool:
    review = run.to_dict()["read_model_freshness_review"]
    return review["block_reason"] in {
        "missing_read_model",
        "invalid_read_model",
        "stale_read_model",
    }


def _pre_export_refresh_source(
    request: SelectedMeasurementRecordExportRequest,
    storage: Path,
) -> dict[str, Any]:
    expected_target_condition = "missing"
    expected_digest = None
    read_model_path = _path_under(
        storage,
        request.read_model_path,
        "selected record preflight read model",
    )
    if read_model_path.exists():
        expected_target_condition = "replace_existing"
        expected_digest = _file_digest(read_model_path)

    refresh_request = {
        "request_id": f"pre-export-refresh-{request.record_id}",
        "approval_state": "approved",
        "record_id": request.record_id,
        "record_dir": request.record_dir,
        "writer_receipt_path": f"{request.record_dir}/writer-receipt.json",
        "finalization_receipt_path": f"{request.record_dir}/finalization-receipt.json",
        "read_model_path": request.read_model_path,
        "expected_target_condition": expected_target_condition,
    }
    if expected_digest is not None:
        refresh_request["expected_current_read_model_digest"] = expected_digest
    return {
        "read_model_refresh_schema": READ_MODEL_REFRESH_SCHEMA,
        "read_model_refresh_policy": READ_MODEL_REFRESH_POLICY,
        "refresh_request": refresh_request,
        "read_view_source": {
            "read_view_schema": READ_VIEW_SCHEMA,
            "read_view_policy": READ_VIEW_POLICY,
            "read_request": {
                "request_id": f"pre-export-read-{request.record_id}",
                "record_id": request.record_id,
                "record_dir": request.record_dir,
                "writer_receipt_path": f"{request.record_dir}/writer-receipt.json",
                "preview_row_limit": 2,
            },
        },
    }


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _preflight_block_reason(run: SelectedMeasurementRecordPreflightExportRun) -> str | None:
    if run.exported:
        return None
    if run.preflight_error is not None:
        return "read_model_refresh_failed"
    if run.refresh_run is not None and not run.refresh_run.refreshed:
        return "read_model_refresh_failed"
    return run.export_run.to_dict()["export_review"]["block_reason"]


def _preflight_next_action(run: SelectedMeasurementRecordPreflightExportRun) -> str:
    if run.exported:
        return "transfer_package_for_receiving_review"
    if run.preflight_error is not None:
        return "review_read_model_refresh_error_before_export_retry"
    if run.refresh_run is not None and not run.refresh_run.refreshed:
        return "review_read_model_refresh_error_before_export_retry"
    return run.export_run.to_dict()["export_review"]["next_action"]


def _preflight_retry_requirement(
    run: SelectedMeasurementRecordPreflightExportRun,
) -> str | None:
    if run.exported:
        return None
    if run.preflight_error is not None:
        return "successful_read_model_refresh_then_export_retry"
    if run.refresh_run is not None and not run.refresh_run.refreshed:
        return "successful_read_model_refresh_then_export_retry"
    return run.export_run.to_dict()["export_review"]["retry_requires"]


def _record_ref(
    read_model: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    writer_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if read_model is None:
        return None
    record = _require_dict(read_model, "record")
    primary = _require_dict(read_model, "primary_data")
    result = {
        "record_id": record.get("record_id"),
        "record_dir": record.get("record_dir"),
        "lifecycle_state": record.get("lifecycle_state"),
        "primary_data_path": primary.get("path"),
        "primary_data_digest": primary.get("digest"),
        "primary_data_size_bytes": primary.get("size_bytes"),
    }
    if manifest is not None:
        manifest_record = _require_dict(manifest, "record")
        result["label"] = manifest_record.get("label")
        result["experiment_type"] = manifest_record.get("experiment_type")
    if writer_receipt is not None:
        writer_request = _require_dict(writer_receipt, "writer_request")
        result["writer_receipt_path"] = writer_request.get("writer_receipt_path")
    return result


def _read_json(root: Path, relative_path: str, label: str) -> dict[str, Any]:
    validate_relative_path(relative_path, f"selected record export {label}")
    _ensure_no_symlink_parents(root, relative_path, f"selected record export {label}")
    path = _path_under(root, relative_path, f"selected record export {label}")
    if path.is_symlink():
        raise ValueError(f"selected record export {label} must not be a symlink")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"selected record export {label} is required") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"selected record export {label} must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"selected record export {label} must be an object")
    return parsed


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    return _require_mapping(source.get(key), key)


def _optional_list(source: dict[str, Any], key: str, *, default: list[Any]) -> list[Any]:
    value = source.get(key, default)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    return validate_text(source.get(key), key)


def _optional_text(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    return validate_text(value, key)


def _require_int(source: dict[str, Any], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_int(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value
