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
class MeasurementRecordView:
    """Read-only view of one canonical local Measurement Record."""

    handle: MeasurementRecordHandle
    storage_root: Path
    record_manifest: dict[str, Any] | None = None
    legacy_run_receipt: dict[str, Any] | None = None
    declared_locators: tuple[dict[str, Any], ...] = ()
    read_model: dict[str, Any] | None = None
    primary_data: dict[str, Any] | None = None
    reference_receipts: tuple[dict[str, Any], ...] = ()
    read_error: str | None = None

    @property
    def classification(self) -> str:
        if self.record_manifest is None:
            return "missing_measurement_record"
        if self.read_error is not None:
            return "blocked_before_measurement_record_open"
        return "opened_measurement_record"

    @property
    def record(self) -> dict[str, Any] | None:
        if self.record_manifest is None:
            return None
        record = self.record_manifest.get("record")
        if not isinstance(record, dict):
            return None
        return copy.deepcopy(record)

    @property
    def creation_source_kind(self) -> str | None:
        if self.record_manifest is None:
            return None
        creation = self.record_manifest.get("creation")
        if not isinstance(creation, dict):
            return None
        source_kind = creation.get("source_kind")
        return source_kind if isinstance(source_kind, str) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "handle": self.handle.to_dict(),
            "storage_root": str(self.storage_root),
            "record": self.record,
            "creation_source_kind": self.creation_source_kind,
            "record_manifest": copy.deepcopy(self.record_manifest),
            "legacy_run_receipt": copy.deepcopy(self.legacy_run_receipt),
            "declared_locators": [copy.deepcopy(item) for item in self.declared_locators],
            "read_model": copy.deepcopy(self.read_model),
            "primary_data": copy.deepcopy(self.primary_data),
            "reference_receipts": [copy.deepcopy(item) for item in self.reference_receipts],
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
            record_manifest=manifest_result.value,
            read_error=manifest_result.error,
        )

    try:
        _validate_manifest(record_id, record_dir, manifest_result.value)
    except ValueError as exc:
        return MeasurementRecordView(
            handle=handle,
            storage_root=root,
            record_manifest=manifest_result.value,
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
        record_manifest=manifest_result.value,
        legacy_run_receipt=legacy.value,
        declared_locators=_declared_locators(legacy.value),
        read_model=read_model.value,
        primary_data=_primary_data_summary(read_model.value),
        reference_receipts=references.values,
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


def _declared_locators(legacy_receipt: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    if legacy_receipt is None:
        return ()
    locators = legacy_receipt.get("declared_locators")
    if not isinstance(locators, list):
        return ()
    return tuple(copy.deepcopy(locator) for locator in locators if isinstance(locator, dict))


def _primary_data_summary(read_model: dict[str, Any] | None) -> dict[str, Any] | None:
    if read_model is None:
        return None
    primary_data = read_model.get("primary_data")
    if not isinstance(primary_data, dict):
        return None
    return copy.deepcopy(primary_data)


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
