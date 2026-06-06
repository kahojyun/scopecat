"""Open canonical Measurement Records by record id."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    validate_public_identifier,
)
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents,
    existing_directory_root,
    path_under,
)
from scopecat.measurement_records.adoption import (
    READ_MODEL_FILENAME,
    MeasurementRecordHandle,
    canonical_record_dir,
    canonical_record_handle,
)
from scopecat.measurement_records.legacy_run import LEGACY_RUN_RECEIPT_NAME
from scopecat.measurement_records.recorded_reference import RECORDED_REFERENCE_RECEIPT_DIR


@dataclass(frozen=True)
class MeasurementRecordSummary:
    """User-facing summary of one Measurement Record."""

    record_id: str
    record_dir: str
    lifecycle_state: str | None
    creation_source_kind: str | None
    label: str | None = None
    experiment_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "lifecycle_state": self.lifecycle_state,
            "creation_source_kind": self.creation_source_kind,
            "label": self.label,
            "experiment_type": self.experiment_type,
        }


@dataclass(frozen=True)
class MeasurementRecordLocatorView:
    """Declared source locator visible to users and downstream workflows."""

    locator_id: str
    kind: str
    role: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
        }


@dataclass(frozen=True)
class MeasurementRecordSourceView:
    """Declared legacy source facts for a Measurement Record."""

    legacy_system_id: str | None = None
    legacy_run_id: str | None = None
    run_started_at: str | None = None
    run_completed_at: str | None = None
    operator_notes: str | None = None
    locators: tuple[MeasurementRecordLocatorView, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_system_id": self.legacy_system_id,
            "legacy_run_id": self.legacy_run_id,
            "run_started_at": self.run_started_at,
            "run_completed_at": self.run_completed_at,
            "operator_notes": self.operator_notes,
            "locators": [locator.to_dict() for locator in self.locators],
        }


@dataclass(frozen=True)
class MeasurementRecordPrimaryDataView:
    """Openable normalized primary-data summary for a Measurement Record."""

    openable_path: str
    digest: str | None = None
    size_bytes: int | None = None
    observed_row_count: int | None = None
    columns: tuple[str, ...] = ()
    preview: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "openable_path": self.openable_path,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "observed_row_count": self.observed_row_count,
            "columns": list(self.columns),
            "preview": [copy.deepcopy(row) for row in self.preview],
        }


@dataclass(frozen=True)
class MeasurementRecordReferenceView:
    """Declared reference attached to a Measurement Record."""

    reference_id: str
    family: str
    role: str
    reference_kind: str
    reference_value: str
    label: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "family": self.family,
            "role": self.role,
            "reference_kind": self.reference_kind,
            "reference_value": self.reference_value,
            "label": self.label,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class MeasurementRecordReferenceSetView:
    """Declared reference set attached to a Measurement Record."""

    reference_set_id: str
    operator_notes: str | None = None
    previous_reference_receipt_path: str | None = None
    previous_reference_set_id: str | None = None
    references: tuple[MeasurementRecordReferenceView, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_set_id": self.reference_set_id,
            "operator_notes": self.operator_notes,
            "previous_reference_set_id": self.previous_reference_set_id,
            "references": [reference.to_dict() for reference in self.references],
        }


@dataclass(frozen=True)
class MeasurementRecordView:
    """Read-only user-shaped view of one canonical local Measurement Record."""

    handle: MeasurementRecordHandle
    storage_root: Path
    record: MeasurementRecordSummary | None = None
    source: MeasurementRecordSourceView | None = None
    primary_data: MeasurementRecordPrimaryDataView | None = None
    reference_sets: tuple[MeasurementRecordReferenceSetView, ...] = ()
    read_error: str | None = None

    @property
    def classification(self) -> str:
        if self.record is None:
            return "missing_measurement_record"
        if self.read_error is not None:
            return "blocked_before_measurement_record_open"
        return "opened_measurement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "handle": self.handle.to_dict(),
            "record": None if self.record is None else self.record.to_dict(),
            "source": None if self.source is None else self.source.to_dict(),
            "primary_data": None if self.primary_data is None else self.primary_data.to_dict(),
            "reference_sets": [reference_set.to_dict() for reference_set in self.reference_sets],
            "read_error": self.read_error,
        }


def open_measurement_record(
    record_id: str,
    *,
    storage_root: str | Path,
) -> MeasurementRecordView:
    """Open one canonical Measurement Record by record_id."""

    validate_public_identifier(record_id, "open measurement record record_id")
    root = existing_directory_root(Path(storage_root), "open measurement record storage root")
    record_dir = canonical_record_dir(record_id)
    handle = canonical_record_handle(
        record_id,
        has_read_model=_optional_artifact_exists(root, f"{record_dir}/{READ_MODEL_FILENAME}"),
    )

    manifest_path = f"{record_dir}/{RECORD_MANIFEST_NAME}"
    manifest_result = _read_optional_json(root, manifest_path, "record manifest")
    if manifest_result.missing:
        return MeasurementRecordView(
            handle=handle,
            storage_root=root,
            read_error="record manifest is missing",
        )
    if manifest_result.error is not None:
        return MeasurementRecordView(
            handle=handle,
            storage_root=root,
            read_error=manifest_result.error,
        )

    try:
        _validate_manifest(record_id, record_dir, manifest_result.value)
    except ValueError as exc:
        return MeasurementRecordView(
            handle=handle,
            storage_root=root,
            read_error=str(exc),
        )

    legacy = _read_optional_json(
        root,
        f"{record_dir}/{LEGACY_RUN_RECEIPT_NAME}",
        "legacy run receipt",
    )
    read_model = _read_optional_json(
        root,
        f"{record_dir}/{READ_MODEL_FILENAME}",
        "record read model",
    )
    references = _read_reference_receipts(root, record_dir)
    read_error = legacy.error or read_model.error or references.error
    return MeasurementRecordView(
        handle=handle,
        storage_root=root,
        record=_record_summary(manifest_result.value),
        source=_source_view(legacy.value),
        primary_data=_primary_data_summary(read_model.value),
        reference_sets=_reference_sets(references.values),
        read_error=read_error,
    )


@dataclass(frozen=True)
class _OptionalJsonRead:
    value: dict[str, Any] | None = None
    missing: bool = False
    error: str | None = None


@dataclass(frozen=True)
class _ReferenceReceiptRead:
    values: tuple[dict[str, Any], ...] = ()
    error: str | None = None


def _read_optional_json(root: Path, relative_path: str, label: str) -> _OptionalJsonRead:
    ensure_no_symlink_parents(root, relative_path, label)
    target = path_under(root, relative_path, label)
    if target.is_symlink():
        return _OptionalJsonRead(error=f"{label} must not be a symlink")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _OptionalJsonRead(missing=True)
    except json.JSONDecodeError as exc:
        return _OptionalJsonRead(error=f"{label} must be JSON: {exc}")
    if not isinstance(payload, dict):
        return _OptionalJsonRead(error=f"{label} must be an object")
    return _OptionalJsonRead(value=payload)


def _read_reference_receipts(root: Path, record_dir: str) -> _ReferenceReceiptRead:
    receipt_dir_path = path_under(
        root,
        f"{record_dir}/{RECORDED_REFERENCE_RECEIPT_DIR}",
        "recorded reference receipt directory",
    )
    ensure_no_symlink_parents(
        root,
        f"{record_dir}/{RECORDED_REFERENCE_RECEIPT_DIR}/placeholder",
        "recorded reference receipt directory",
    )
    if receipt_dir_path.is_symlink():
        return _ReferenceReceiptRead(error="recorded reference receipt directory is a symlink")
    if not receipt_dir_path.exists():
        return _ReferenceReceiptRead()
    if not receipt_dir_path.is_dir():
        return _ReferenceReceiptRead(
            error="recorded reference receipt directory is not a directory"
        )

    receipts: list[dict[str, Any]] = []
    for receipt_path in sorted(receipt_dir_path.glob("*.json")):
        relative_path = f"{record_dir}/{RECORDED_REFERENCE_RECEIPT_DIR}/{receipt_path.name}"
        result = _read_optional_json(root, relative_path, "recorded reference receipt")
        if result.error is not None:
            return _ReferenceReceiptRead(values=tuple(receipts), error=result.error)
        if result.value is not None:
            receipts.append(result.value)
    return _ReferenceReceiptRead(values=tuple(receipts))


def _validate_manifest(record_id: str, record_dir: str, manifest: dict[str, Any] | None) -> None:
    if manifest is None:
        raise ValueError("record manifest is missing")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("record manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != record_id:
        raise ValueError("record manifest record_id does not match requested record_id")
    storage = _require_dict(manifest, "storage")
    if storage.get("record_dir") != record_dir:
        raise ValueError("record manifest record_dir does not match canonical record_dir")
    if storage.get("manifest_path") != f"{record_dir}/{RECORD_MANIFEST_NAME}":
        raise ValueError("record manifest path does not match canonical manifest path")


def _record_summary(manifest: dict[str, Any] | None) -> MeasurementRecordSummary | None:
    if manifest is None:
        return None
    record = manifest.get("record")
    storage = manifest.get("storage")
    creation = manifest.get("creation")
    if not isinstance(record, dict) or not isinstance(storage, dict):
        return None
    if not isinstance(creation, dict):
        creation = {}
    return MeasurementRecordSummary(
        record_id=_optional_text(record, "record_id"),
        record_dir=_optional_text(storage, "record_dir"),
        lifecycle_state=_optional_text(record, "lifecycle_state"),
        creation_source_kind=_optional_text(creation, "source_kind"),
        label=_optional_text(record, "label"),
        experiment_type=_optional_text(record, "experiment_type"),
    )


def _source_view(legacy_receipt: dict[str, Any] | None) -> MeasurementRecordSourceView | None:
    if legacy_receipt is None:
        return None
    legacy_run = legacy_receipt.get("legacy_run")
    if not isinstance(legacy_run, dict):
        return MeasurementRecordSourceView(locators=_locator_views(legacy_receipt))
    return MeasurementRecordSourceView(
        legacy_system_id=_optional_text(legacy_run, "legacy_system_id"),
        legacy_run_id=_optional_text(legacy_run, "legacy_run_id"),
        run_started_at=_optional_text(legacy_run, "run_started_at"),
        run_completed_at=_optional_text(legacy_run, "run_completed_at"),
        operator_notes=_optional_text(legacy_run, "operator_notes"),
        locators=_locator_views(legacy_receipt),
    )


def _locator_views(
    legacy_receipt: dict[str, Any] | None,
) -> tuple[MeasurementRecordLocatorView, ...]:
    if legacy_receipt is None:
        return ()
    locators = legacy_receipt.get("declared_locators")
    if not isinstance(locators, list):
        return ()
    result: list[MeasurementRecordLocatorView] = []
    for locator in locators:
        if not isinstance(locator, dict):
            continue
        result.append(
            MeasurementRecordLocatorView(
                locator_id=_optional_text(locator, "locator_id") or "",
                kind=_optional_text(locator, "kind") or "",
                role=_optional_text(locator, "role") or "",
                value=_optional_text(locator, "value") or "",
            )
        )
    return tuple(result)


def _primary_data_summary(
    read_model: dict[str, Any] | None,
) -> MeasurementRecordPrimaryDataView | None:
    if read_model is None:
        return None
    primary_data = read_model.get("primary_data")
    if not isinstance(primary_data, dict):
        return None
    return MeasurementRecordPrimaryDataView(
        openable_path=_optional_text(primary_data, "path") or "",
        digest=_optional_text(primary_data, "digest"),
        size_bytes=_optional_int(primary_data, "size_bytes"),
        observed_row_count=_optional_int(primary_data, "observed_row_count"),
        columns=tuple(_text_items(primary_data.get("columns"))),
        preview=tuple(_dict_items(primary_data.get("preview"))),
    )


def _reference_sets(
    receipts: tuple[dict[str, Any], ...],
) -> tuple[MeasurementRecordReferenceSetView, ...]:
    result: list[MeasurementRecordReferenceSetView] = []
    for receipt in receipts:
        reference_set = receipt.get("reference_set")
        if not isinstance(reference_set, dict):
            continue
        previous = reference_set.get("previous_reference_receipt")
        previous_path = None
        previous_id = None
        if isinstance(previous, dict):
            previous_path = _optional_text(previous, "path")
            previous_id = _optional_text(previous, "reference_set_id")
        result.append(
            MeasurementRecordReferenceSetView(
                reference_set_id=_optional_text(reference_set, "reference_set_id") or "",
                operator_notes=_optional_text(reference_set, "operator_notes"),
                previous_reference_receipt_path=previous_path,
                previous_reference_set_id=previous_id,
                references=_reference_views(receipt),
            )
        )
    return tuple(result)


def _reference_views(receipt: dict[str, Any]) -> tuple[MeasurementRecordReferenceView, ...]:
    references = receipt.get("references")
    if not isinstance(references, list):
        return ()
    result: list[MeasurementRecordReferenceView] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        result.append(
            MeasurementRecordReferenceView(
                reference_id=_optional_text(reference, "reference_id") or "",
                family=_optional_text(reference, "family") or "",
                role=_optional_text(reference, "role") or "",
                reference_kind=_optional_text(reference, "reference_kind") or "",
                reference_value=_optional_text(reference, "reference_value") or "",
                label=_optional_text(reference, "label"),
                digest=_optional_text(reference, "digest"),
                size_bytes=_optional_int(reference, "size_bytes"),
                preview=_optional_text(reference, "preview"),
            )
        )
    return tuple(result)


def _optional_text(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) else None


def _optional_int(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _text_items(source: Any) -> list[str]:
    if not isinstance(source, list):
        return []
    return [item for item in source if isinstance(item, str)]


def _dict_items(source: Any) -> list[dict[str, str]]:
    if not isinstance(source, list):
        return []
    return [copy.deepcopy(item) for item in source if isinstance(item, dict)]


def _optional_artifact_exists(root: Path, relative_path: str) -> bool:
    try:
        ensure_no_symlink_parents(root, relative_path, "measurement record optional artifact")
    except ValueError:
        return False
    return path_under(root, relative_path, "measurement record optional artifact").exists()


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"record manifest {key} must be an object")
    return value
