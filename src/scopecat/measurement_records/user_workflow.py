"""User-facing measurement recording workflows over receipt primitives."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    validate_public_identifier,
    validate_text,
)
from scopecat.measurement_records._primary_table_read import (
    PrimaryTableReadRequest,
    PrimaryTableReadResult,
    read_record_primary_table,
)
from scopecat.measurement_records.durable_import import MeasurementRecordImportSource
from scopecat.measurement_records.legacy_primary_import import (
    LegacyPrimaryImportRequest,
    LegacyPrimaryImportRun,
    attach_converted_primary_data_to_legacy_record_from_request,
)
from scopecat.measurement_records.legacy_run import (
    LegacyRunLocator,
    LegacyRunRecordRequest,
    LegacyRunRecordRun,
    record_legacy_measurement_run_from_request,
)
from scopecat.measurement_records.recorded_reference import (
    MeasurementRecordReference,
    MeasurementRecordReferenceRequest,
    MeasurementRecordReferenceRun,
    record_measurement_record_references_from_request,
)


@dataclass(frozen=True)
class LegacyMeasurementSource:
    """User-facing facts for an externally executed legacy measurement."""

    legacy_system_id: str
    legacy_run_id: str
    label: str | None = None
    experiment_type: str | None = None
    primary_locator: str | None = None
    notebook_locator: str | None = None
    run_started_at: str | None = None
    run_completed_at: str | None = None
    created_at: str | None = None
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.legacy_system_id, "legacy source legacy_system_id")
        validate_public_identifier(self.legacy_run_id, "legacy source legacy_run_id")
        for value, owner in (
            (self.label, "legacy source label"),
            (self.experiment_type, "legacy source experiment_type"),
            (self.primary_locator, "legacy source primary_locator"),
            (self.notebook_locator, "legacy source notebook_locator"),
            (self.run_started_at, "legacy source run_started_at"),
            (self.run_completed_at, "legacy source run_completed_at"),
            (self.created_at, "legacy source created_at"),
            (self.operator_notes, "legacy source operator_notes"),
        ):
            if value is not None:
                validate_text(value, owner)


@dataclass(frozen=True)
class ConvertedPrimaryData:
    """User-facing normalized primary data already written under content_root."""

    path: Path
    rows_recorded: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise ValueError("converted primary data path must be a Path")
        if not isinstance(self.rows_recorded, int) or isinstance(self.rows_recorded, bool):
            raise ValueError("converted primary data rows_recorded must be an integer")
        if self.rows_recorded < 0:
            raise ValueError("converted primary data rows_recorded must be non-negative")


@dataclass(frozen=True)
class RecordedReferenceInput:
    """User-facing reference to context, derived artifacts, or evidence."""

    family: str
    role: str
    reference_kind: str
    reference_value: str
    label: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    preview: str | None = None

    def to_reference(self, *, base_id: str, sequence: int) -> MeasurementRecordReference:
        return MeasurementRecordReference(
            reference_id=f"ref-{base_id}-{sequence}",
            family=self.family,
            role=self.role,
            reference_kind=self.reference_kind,
            reference_value=self.reference_value,
            label=self.label,
            digest=self.digest,
            size_bytes=self.size_bytes,
            preview=self.preview,
        )


@dataclass(frozen=True)
class LegacyMeasurementRecordRequest:
    """User-facing request to record one legacy measurement and its references."""

    source: LegacyMeasurementSource
    primary_data: ConvertedPrimaryData
    references: tuple[RecordedReferenceInput, ...] = ()
    preview_row_limit: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.source, LegacyMeasurementSource):
            raise ValueError("legacy measurement request source is unsupported")
        if not isinstance(self.primary_data, ConvertedPrimaryData):
            raise ValueError("legacy measurement request primary_data is unsupported")
        if not isinstance(self.references, tuple):
            raise ValueError("legacy measurement request references must be a tuple")
        for reference in self.references:
            if not isinstance(reference, RecordedReferenceInput):
                raise ValueError("legacy measurement request references are unsupported")
        if not isinstance(self.preview_row_limit, int) or isinstance(self.preview_row_limit, bool):
            raise ValueError("legacy measurement request preview_row_limit must be an integer")
        if self.preview_row_limit <= 0:
            raise ValueError("legacy measurement request preview_row_limit must be positive")


@dataclass(frozen=True)
class LegacyMeasurementIds:
    """Generated Scopecat ids hidden from the user-facing request."""

    measurement_id: str
    record_id: str
    legacy_record_request_id: str
    primary_attach_request_id: str
    recorded_reference_request_id: str
    recorded_reference_set_id: str
    primary_table_read_request_id: str
    primary_locator_id: str
    notebook_locator_id: str
    normalized_source_item_id: str


@dataclass(frozen=True)
class LegacyMeasurementRecordRun:
    """Composed user-facing result for one recorded legacy measurement."""

    request: LegacyMeasurementRecordRequest
    generated_ids: LegacyMeasurementIds
    storage_root: Path
    content_root: Path
    legacy_run: LegacyRunRecordRun
    primary_attach: LegacyPrimaryImportRun | None = None
    primary_table_read: PrimaryTableReadResult | None = None
    recorded_reference: MeasurementRecordReferenceRun | None = None

    @property
    def recorded(self) -> bool:
        references_ready = self.recorded_reference is None or self.recorded_reference.recorded
        return (
            self.legacy_run.recorded
            and self.primary_attach is not None
            and self.primary_attach.attached
            and self.primary_table_read is not None
            and self.primary_table_read.classification == "primary_table_ready"
            and references_ready
        )

    @property
    def classification(self) -> str:
        if self.recorded:
            return "recorded_legacy_measurement"
        return "legacy_measurement_recording_review_needed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "recorded": self.recorded,
            "measurement": {
                "measurement_id": self.generated_ids.measurement_id,
                "record_id": self.generated_ids.record_id,
                "record_dir": f"records/{self.generated_ids.record_id}",
                "title": self.request.source.label or self.request.source.legacy_run_id,
                "legacy_system_id": self.request.source.legacy_system_id,
                "legacy_run_id": self.request.source.legacy_run_id,
            },
            "steps": {
                "legacy_run": self.legacy_run.classification,
                "primary_attach": None
                if self.primary_attach is None
                else self.primary_attach.classification,
                "recorded_reference": None
                if self.recorded_reference is None
                else self.recorded_reference.classification,
                "primary_table_read": None
                if self.primary_table_read is None
                else self.primary_table_read.classification,
            },
        }


def record_legacy_measurement(
    *,
    source: LegacyMeasurementSource,
    primary_data: ConvertedPrimaryData,
    references: tuple[RecordedReferenceInput, ...] = (),
    storage_root: str | Path,
    content_root: str | Path,
    preview_row_limit: int = 10,
) -> LegacyMeasurementRecordRun:
    """Record one legacy measurement using user-facing source and reference facts."""

    return record_legacy_measurement_from_request(
        LegacyMeasurementRecordRequest(
            source=source,
            primary_data=primary_data,
            references=references,
            preview_row_limit=preview_row_limit,
        ),
        storage_root=storage_root,
        content_root=content_root,
    )


def record_legacy_measurement_from_request(
    request: LegacyMeasurementRecordRequest,
    *,
    storage_root: str | Path,
    content_root: str | Path,
) -> LegacyMeasurementRecordRun:
    """Record one legacy measurement without exposing receipt request ids to callers."""

    storage = Path(storage_root)
    content = Path(content_root)
    ids = _legacy_measurement_ids(request.source)
    content_ref = _content_ref(content, request.primary_data.path)
    legacy_run = record_legacy_measurement_run_from_request(
        _legacy_record_request(request.source, ids),
        storage_root=storage,
    )
    if not legacy_run.recorded:
        return LegacyMeasurementRecordRun(
            request=request,
            generated_ids=ids,
            storage_root=storage,
            content_root=content,
            legacy_run=legacy_run,
        )
    primary_attach = attach_converted_primary_data_to_legacy_record_from_request(
        _primary_attach_request(request, ids, content_ref),
        content_root=content,
        storage_root=storage,
    )
    if not primary_attach.attached:
        return LegacyMeasurementRecordRun(
            request=request,
            generated_ids=ids,
            storage_root=storage,
            content_root=content,
            legacy_run=legacy_run,
            primary_attach=primary_attach,
        )
    recorded_reference = None
    if request.references:
        recorded_reference = record_measurement_record_references_from_request(
            _reference_request(request.references, ids),
            storage_root=storage,
        )
    primary_table_read = read_record_primary_table(
        PrimaryTableReadRequest(
            request_id=ids.primary_table_read_request_id,
            record_id=ids.record_id,
            record_dir=f"records/{ids.record_id}",
            writer_receipt_path=f"records/{ids.record_id}/writer-receipt.json",
            preview_row_limit=request.preview_row_limit,
        ),
        storage_root=storage,
    )
    return LegacyMeasurementRecordRun(
        request=request,
        generated_ids=ids,
        storage_root=storage,
        content_root=content,
        legacy_run=legacy_run,
        primary_attach=primary_attach,
        recorded_reference=recorded_reference,
        primary_table_read=primary_table_read,
    )


def legacy_measurement_slug(source: LegacyMeasurementSource) -> str:
    """Return the stable local slug used for generated Scopecat ids."""

    return _slug(f"{source.legacy_system_id}-{source.legacy_run_id}")


def _legacy_measurement_ids(source: LegacyMeasurementSource) -> LegacyMeasurementIds:
    base = legacy_measurement_slug(source)
    return LegacyMeasurementIds(
        measurement_id=f"meas-{base}",
        record_id=f"rec-{base}",
        legacy_record_request_id=f"record-{base}-legacy",
        primary_attach_request_id=f"attach-{base}-primary",
        recorded_reference_request_id=f"record-{base}-references",
        recorded_reference_set_id=f"references-{base}",
        primary_table_read_request_id=f"read-{base}-primary",
        primary_locator_id=f"loc-{base}-primary",
        notebook_locator_id=f"loc-{base}-notebook",
        normalized_source_item_id=f"normalized-{base}",
    )


def _legacy_record_request(
    source: LegacyMeasurementSource,
    ids: LegacyMeasurementIds,
) -> LegacyRunRecordRequest:
    locators = []
    if source.primary_locator is not None:
        locators.append(
            LegacyRunLocator(
                locator_id=ids.primary_locator_id,
                kind="workspace_relative_path",
                role="primary_data",
                value=source.primary_locator,
            )
        )
    if source.notebook_locator is not None:
        locators.append(
            LegacyRunLocator(
                locator_id=ids.notebook_locator_id,
                kind="opaque_reference",
                role="notebook",
                value=source.notebook_locator,
            )
        )
    return LegacyRunRecordRequest(
        request_id=ids.legacy_record_request_id,
        approval_state="approved",
        record_id=ids.record_id,
        record_dir=f"records/{ids.record_id}",
        legacy_system_id=source.legacy_system_id,
        legacy_run_id=source.legacy_run_id,
        created_at=source.created_at,
        label=source.label,
        experiment_type=source.experiment_type,
        run_started_at=source.run_started_at,
        run_completed_at=source.run_completed_at,
        locators=tuple(locators),
        operator_notes=source.operator_notes,
    )


def _primary_attach_request(
    request: LegacyMeasurementRecordRequest,
    ids: LegacyMeasurementIds,
    content_ref: str,
) -> LegacyPrimaryImportRequest:
    normalized_path = request.primary_data.path
    return LegacyPrimaryImportRequest(
        request_id=ids.primary_attach_request_id,
        approval_state="approved",
        record_id=ids.record_id,
        record_dir=f"records/{ids.record_id}",
        legacy_receipt_path=f"records/{ids.record_id}/legacy-run-receipt.json",
        primary_data_path=f"records/{ids.record_id}/primary.csv",
        writer_receipt_path=f"records/{ids.record_id}/writer-receipt.json",
        finalization_receipt_path=f"records/{ids.record_id}/finalization-receipt.json",
        read_model_path=f"records/{ids.record_id}/record-read-model.json",
        import_source=MeasurementRecordImportSource(
            source_kind="adapter_normalized_primary_data",
            source_id=ids.record_id,
            source_item_id=ids.normalized_source_item_id,
            content_ref=content_ref,
            declared_digest=_sha256_file(normalized_path),
            size_bytes=normalized_path.stat().st_size,
            rows_recorded=request.primary_data.rows_recorded,
        ),
    )


def _reference_request(
    references: tuple[RecordedReferenceInput, ...],
    ids: LegacyMeasurementIds,
) -> MeasurementRecordReferenceRequest:
    return MeasurementRecordReferenceRequest(
        request_id=ids.recorded_reference_request_id,
        approval_state="approved",
        record_id=ids.record_id,
        record_dir=f"records/{ids.record_id}",
        reference_set_id=ids.recorded_reference_set_id,
        references=tuple(
            reference.to_reference(base_id=ids.measurement_id, sequence=index)
            for index, reference in enumerate(references, start=1)
        ),
        operator_notes="Recorded user-selected references.",
    )


def _content_ref(content_root: Path, path: Path) -> str:
    root = content_root.resolve()
    target = path.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("converted primary data path must stay under content_root") from exc
    if not target.is_file():
        raise ValueError("converted primary data path must be an existing file")
    return relative.as_posix()


def _sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "legacy-run"
