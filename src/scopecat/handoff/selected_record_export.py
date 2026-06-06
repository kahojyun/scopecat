"""Export selected stored Measurement Records to handoff packages."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    HANDOFF_PACKAGE_CREATED_BY,
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
    validate_strict_child_path,
    validate_text,
)
from scopecat.handoff._declared_preview import (
    HandoffPackagePreviewMetadata,
    coerce_handoff_package_preview_metadata,
)
from scopecat.handoff.writer import (
    HandoffPackageBundleItem,
    HandoffPackageIdentity,
    HandoffPackageLinkedContext,
    HandoffPackagePrimaryData,
    HandoffPackageSelectedMeasurement,
    HandoffPackageWriteReceipt,
    HandoffPackageWriteRequest,
    HandoffPackageWriteSource,
    write_package_from_source,
)
from scopecat.measurement_records import (
    MeasurementRecordHandoffLinkedContextSelection,
    MeasurementRecordHandoffPreparationRun,
    PackageableMeasurementRecord,
    PackageableMeasurementRecordLinkedContext,
    prepare_measurement_record_for_handoff,
)

APPROVAL_STATES = {"approved", "rejected", "needs_review"}


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

    def to_measurement_record_selection(self) -> MeasurementRecordHandoffLinkedContextSelection:
        return MeasurementRecordHandoffLinkedContextSelection(
            link_id=self.link_id,
            kind=self.kind,
            label=self.label,
            relation=self.relation,
            reason=self.reason,
            context_reference=copy.deepcopy(self.context_reference),
            source_path=self.source_path,
            package_path=self.package_path,
            expected_digest=self.expected_digest,
            expected_size_bytes=self.expected_size_bytes,
        )


@dataclass(frozen=True)
class SelectedMeasurementRecordBatchExportRecord:
    """One stored Measurement Record selected for a batch handoff export."""

    record_id: str
    legacy_data_id: int
    target: str
    declared_preview_metadata: HandoffPackagePreviewMetadata
    linked_context: tuple[SelectedMeasurementRecordExportLinkedContext, ...] = ()

    def __post_init__(self) -> None:
        validate_public_identifier(self.record_id, "selected record export record_id")
        if not isinstance(self.legacy_data_id, int) or isinstance(self.legacy_data_id, bool):
            raise ValueError("selected record export legacy_data_id must be an integer")
        if self.legacy_data_id < 0:
            raise ValueError("selected record export legacy_data_id must be non-negative")
        validate_public_identifier(self.target, "selected record export target")
        object.__setattr__(
            self,
            "declared_preview_metadata",
            _coerce_declared_preview_metadata(self.declared_preview_metadata),
        )

    @property
    def package_primary_path(self) -> str:
        return f"measurements/{self.record_id}/primary.csv"

    def to_record_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "legacy_data_id": self.legacy_data_id,
            "target": self.target,
            "declared_preview_metadata": self.declared_preview_metadata.to_manifest(),
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
    legacy_data_id: int
    target: str
    declared_preview_metadata: HandoffPackagePreviewMetadata
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
        object.__setattr__(
            self,
            "declared_preview_metadata",
            _coerce_declared_preview_metadata(self.declared_preview_metadata),
        )
        self.to_batch_record()

    def to_batch_record(self) -> SelectedMeasurementRecordBatchExportRecord:
        return SelectedMeasurementRecordBatchExportRecord(
            record_id=self.record_id,
            legacy_data_id=self.legacy_data_id,
            target=self.target,
            declared_preview_metadata=self.declared_preview_metadata,
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
            "legacy_data_id": self.legacy_data_id,
            "target": self.target,
            "declared_preview_metadata": self.declared_preview_metadata.to_manifest(),
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
class _SelectedRecordExportRecordRef:
    record_id: str
    lifecycle_state: str
    primary_data_path: str
    primary_data_digest: str
    primary_data_size_bytes: int
    primary_data_format: str
    primary_data_row_count: int
    label: str | None
    experiment_type: str | None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "record_id": self.record_id,
            "lifecycle_state": self.lifecycle_state,
            "primary_data_path": self.primary_data_path,
            "primary_data_digest": self.primary_data_digest,
            "primary_data_size_bytes": self.primary_data_size_bytes,
            "primary_data_format": self.primary_data_format,
            "primary_data_row_count": self.primary_data_row_count,
        }
        if self.label is not None:
            result["label"] = self.label
        if self.experiment_type is not None:
            result["experiment_type"] = self.experiment_type
        return result


@dataclass(frozen=True)
class SelectedMeasurementRecordExportRun:
    """Local run for selected-record package export."""

    request: SelectedMeasurementRecordExportRequest
    storage_root: Path
    package_root: Path
    record: _SelectedRecordExportRecordRef | None = None
    preparation: MeasurementRecordHandoffPreparationRun | None = None
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

    @property
    def block_reason(self) -> str | None:
        return _export_block_reason(
            approved=self.request.approved,
            export_error=self.export_error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "block_reason": self.block_reason,
            "request": self.request.to_dict(),
            "record": None if self.record is None else self.record.to_dict(),
            "preparation": None if self.preparation is None else self.preparation.to_dict(),
            "package_write": None if self.package_write is None else self.package_write.to_dict(),
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
        if self.block_reason == "read_model_refresh_failed":
            return "blocked_before_export_refresh_failed"
        return "blocked_or_exported_without_preflight_refresh"

    @property
    def block_reason(self) -> str | None:
        return _preflight_block_reason(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "block_reason": self.block_reason,
            "request": self.request.to_dict(),
            "initial_export": self.initial_export.to_dict(),
            "refresh": (
                None
                if self.export_run.preparation is None
                else self.export_run.preparation.to_dict()["refresh"]
            ),
            "final_export": None if self.final_export is None else self.final_export.to_dict(),
            "preflight_error": self.preflight_error,
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
    record_ref: _SelectedRecordExportRecordRef
    preparation: MeasurementRecordHandoffPreparationRun
    packageable_record: PackageableMeasurementRecord


@dataclass(frozen=True)
class SelectedMeasurementRecordBatchExportRun:
    """Local run for selected-record batch package export."""

    request: SelectedMeasurementRecordBatchExportRequest
    storage_root: Path
    package_root: Path
    records: tuple[_SelectedRecordExportRecordRef, ...] = ()
    preparations: tuple[MeasurementRecordHandoffPreparationRun, ...] = ()
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

    @property
    def block_reason(self) -> str | None:
        return _export_block_reason(
            approved=self.request.approved,
            export_error=self.export_error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "block_reason": self.block_reason,
            "request": self.request.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "preparations": [run.to_dict() for run in self.preparations],
            "package_write": None if self.package_write is None else self.package_write.to_dict(),
            "export": {
                "performed": self.exported,
                "storage_root": str(self.storage_root),
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir if self.exported else None,
                "export_error": self.export_error,
            },
        }


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

    evidence = None
    try:
        evidence = _read_record_export_evidence(storage, request.to_batch_record())
        writer_source = _writer_source(request, evidence)
        package_write = write_package_from_source(
            writer_source,
            source_root=storage,
            package_root=packages,
        )
    except _ExportPreparationError as exc:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            preparation=exc.preparation,
            export_error=str(exc),
        )
    except ValueError as exc:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            preparation=None if evidence is None else evidence.preparation,
            export_error=str(exc),
        )

    return SelectedMeasurementRecordExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        record=evidence.record_ref,
        preparation=evidence.preparation,
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
    return SelectedMeasurementRecordPreflightExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        initial_export=initial_export,
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
        package_write = write_package_from_source(
            writer_source,
            source_root=storage,
            package_root=packages,
        )
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
        records=tuple(record.record_ref for record in records),
        preparations=tuple(record.preparation for record in records),
        package_write=package_write,
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


def _read_record_export_evidence(
    storage: Path,
    record: SelectedMeasurementRecordBatchExportRecord,
) -> _SelectedRecordExportEvidence:
    preparation = prepare_measurement_record_for_handoff(
        record.record_id,
        storage_root=storage,
        linked_context_selection=tuple(
            item.to_measurement_record_selection() for item in record.linked_context
        ),
    )
    if not preparation.prepared or preparation.packageable_record is None:
        raise _ExportPreparationError(preparation)
    return _SelectedRecordExportEvidence(
        record=record,
        record_ref=_record_ref_from_packageable(preparation.packageable_record),
        preparation=preparation,
        packageable_record=preparation.packageable_record,
    )


def _package_write_identity(
    request: SelectedMeasurementRecordExportRequest | SelectedMeasurementRecordBatchExportRequest,
) -> HandoffPackageIdentity:
    return HandoffPackageIdentity(
        package_id=request.package_id,
        display_name=request.display_name,
        created_by=HANDOFF_PACKAGE_CREATED_BY,
        source_export_summary_id=request.source_export_summary_id,
        display_path=request.display_path,
        local_path_redacted=True,
    )


def _package_write_request(
    request: SelectedMeasurementRecordExportRequest | SelectedMeasurementRecordBatchExportRequest,
) -> HandoffPackageWriteRequest:
    return HandoffPackageWriteRequest(
        request_id=request.request_id,
        package_dir=request.package_dir,
        manifest_path=request.manifest_path,
    )


def _measurement_writer_item(
    evidence: _SelectedRecordExportEvidence,
) -> HandoffPackageSelectedMeasurement:
    ref = evidence.record_ref
    label = ref.label or evidence.record.record_id
    experiment_type = ref.experiment_type or "unspecified"
    validate_public_identifier(experiment_type, "selected record export experiment_type")
    package_primary_path = evidence.record.package_primary_path
    primary = HandoffPackagePrimaryData(
        kind="primary_data",
        label="Stored primary data",
        source_path=ref.primary_data_path,
        expected_digest=ref.primary_data_digest,
        expected_size_bytes=ref.primary_data_size_bytes,
        package_path=package_primary_path,
        include_status="included_by_default",
        relation="selected_measurement_source",
        authority=MANIFEST_AUTHORITY,
        format=ref.primary_data_format,
        package_state="packaged",
        reason=None,
    )
    return HandoffPackageSelectedMeasurement(
        measurement_record_id=evidence.record.record_id,
        legacy_data_id=evidence.record.legacy_data_id,
        label=label,
        experiment_type=experiment_type,
        target=evidence.record.target,
        primary_data=primary,
        declared_preview_metadata=evidence.record.declared_preview_metadata,
        default_bundle=(
            HandoffPackageBundleItem(
                item_id=f"{evidence.record.record_id}-primary",
                kind="primary_data",
                label=primary.label,
                package_path=package_primary_path,
                include_status="included_by_default",
                relation="selected_measurement_source",
                authority=MANIFEST_AUTHORITY,
                package_state="packaged",
                reason=None,
            ),
        ),
    )


def _coerce_declared_preview_metadata(
    source: object,
) -> HandoffPackagePreviewMetadata:
    return coerce_handoff_package_preview_metadata(
        source,
        owner="selected record export preview",
    )


def _batch_writer_source(
    request: SelectedMeasurementRecordBatchExportRequest,
    records: tuple[_SelectedRecordExportEvidence, ...],
) -> HandoffPackageWriteSource:
    return HandoffPackageWriteSource(
        request=_package_write_request(request),
        identity=_package_write_identity(request),
        selected_measurements=tuple(_measurement_writer_item(record) for record in records),
        linked_context=tuple(
            _linked_context_writer_item(item, measurement_record_id=record.record.record_id)
            for record in records
            for item in record.packageable_record.linked_context
        ),
    )


def _writer_source(
    request: SelectedMeasurementRecordExportRequest,
    evidence: _SelectedRecordExportEvidence,
) -> HandoffPackageWriteSource:
    return HandoffPackageWriteSource(
        request=_package_write_request(request),
        identity=_package_write_identity(request),
        selected_measurements=(_measurement_writer_item(evidence),),
        linked_context=tuple(
            _linked_context_writer_item(item, measurement_record_id=evidence.record.record_id)
            for item in evidence.packageable_record.linked_context
        ),
    )


def _export_block_reason(*, approved: bool, export_error: str | None) -> str | None:
    if export_error is None:
        return None if approved else "request_not_approved"
    if export_error == "read_model_refresh_failed":
        return "read_model_refresh_failed"
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


def _preflight_block_reason(run: SelectedMeasurementRecordPreflightExportRun) -> str | None:
    if run.exported:
        return None
    if run.preflight_error is not None:
        return "read_model_refresh_failed"
    return run.export_run.block_reason


def _record_ref_from_packageable(
    record: PackageableMeasurementRecord,
) -> _SelectedRecordExportRecordRef:
    return _SelectedRecordExportRecordRef(
        record_id=record.record_id,
        lifecycle_state=record.lifecycle_state,
        primary_data_path=record.primary_data_path,
        primary_data_digest=record.primary_data_digest,
        primary_data_size_bytes=record.primary_data_size_bytes,
        primary_data_format=record.primary_data_format,
        primary_data_row_count=record.primary_data_row_count,
        label=record.label,
        experiment_type=record.experiment_type,
    )


def _linked_context_writer_item(
    item: PackageableMeasurementRecordLinkedContext,
    *,
    measurement_record_id: str,
) -> HandoffPackageLinkedContext:
    return HandoffPackageLinkedContext(
        link_id=item.link_id,
        kind=item.kind,
        label=item.label,
        package_path=item.package_path,
        include_status="included_by_user" if item.packages_payload else "visible_excluded",
        relation=item.relation,
        authority=MANIFEST_AUTHORITY,
        package_state="packaged" if item.packages_payload else "not_packaged_visible_reference",
        reason=None if item.packages_payload else item.reason,
        linked_measurement_record_ids=(measurement_record_id,),
        source_path=item.source_path,
        expected_digest=item.expected_digest,
        expected_size_bytes=item.expected_size_bytes,
        context_reference=None if item.context_reference is None else dict(item.context_reference),
    )


def _existing_directory_root(path: Path, owner: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    if not path.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    return path.resolve()


class _ExportPreparationError(ValueError):
    def __init__(self, preparation: MeasurementRecordHandoffPreparationRun) -> None:
        message = (
            preparation.block_reason
            if preparation.block_reason == "read_model_refresh_failed"
            else preparation.preparation_error
            or preparation.initial_error
            or preparation.block_reason
            or "measurement record is not exportable"
        )
        super().__init__(message)
        self.preparation = preparation
