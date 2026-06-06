"""Measurement Records-owned projection for handoff package export."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    RECORD_MANIFEST_NAME,
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
    validate_text,
)
from scopecat.measurement_records._storage import (
    existing_directory_root,
    path_under,
    validate_strict_child_path,
)
from scopecat.measurement_records.adoption import (
    READ_MODEL_FILENAME,
    canonical_record_dir,
)
from scopecat.measurement_records.selected_record_access import (
    SELECTED_RECORD_READ_MODEL_SCHEMA,
    SelectedRecordReadModelRefreshRun,
    refresh_selected_record_read_model_for_export,
)


@dataclass(frozen=True)
class MeasurementRecordHandoffLinkedContextSelection:
    """Explicit record-local context selection requested for handoff packaging."""

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
        validate_public_identifier(self.link_id, "handoff context link_id")
        validate_public_identifier(self.kind, "handoff context kind")
        validate_text(self.label, "handoff context label")
        validate_public_identifier(self.relation, "handoff context relation")
        validate_text(self.reason, "handoff context reason")
        if self.context_reference is not None and not isinstance(self.context_reference, dict):
            raise ValueError("handoff context_reference must be an object")
        payload_fields = (
            self.source_path,
            self.package_path,
            self.expected_digest,
            self.expected_size_bytes,
        )
        has_payload = any(value is not None for value in payload_fields)
        if has_payload and not all(value is not None for value in payload_fields):
            raise ValueError("handoff context payload fields are paired")
        if self.source_path is not None:
            validate_relative_path(self.source_path, "handoff context source_path")
        if self.package_path is not None:
            validate_relative_path(self.package_path, "handoff context package_path")
        if self.expected_digest is not None:
            validate_sha256_digest(self.expected_digest, "handoff context expected_digest")
        if self.expected_size_bytes is not None:
            validate_positive_integer(
                self.expected_size_bytes,
                "handoff context expected_size_bytes",
            )

    @property
    def packages_payload(self) -> bool:
        return self.source_path is not None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "relation": self.relation,
            "reason": self.reason,
            "context_reference": (
                None if self.context_reference is None else dict(self.context_reference)
            ),
            "source_path": self.source_path,
            "package_path": self.package_path,
            "expected_digest": self.expected_digest,
            "expected_size_bytes": self.expected_size_bytes,
        }
        return result


@dataclass(frozen=True)
class PackageableMeasurementRecordLinkedContext:
    """Measurement Record context projected for package writing."""

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

    @property
    def packages_payload(self) -> bool:
        return self.source_path is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "relation": self.relation,
            "reason": self.reason,
            "context_reference": (
                None if self.context_reference is None else dict(self.context_reference)
            ),
            "source_path": self.source_path,
            "package_path": self.package_path,
            "expected_digest": self.expected_digest,
            "expected_size_bytes": self.expected_size_bytes,
        }


@dataclass(frozen=True)
class PackageableMeasurementRecord:
    """Typed packageable projection of a complete Measurement Record."""

    record_id: str
    lifecycle_state: str
    primary_data_path: str
    primary_data_digest: str
    primary_data_size_bytes: int
    primary_data_format: str
    primary_data_row_count: int
    label: str | None = None
    experiment_type: str | None = None
    linked_context: tuple[PackageableMeasurementRecordLinkedContext, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "lifecycle_state": self.lifecycle_state,
            "primary_data": {
                "path": self.primary_data_path,
                "digest": self.primary_data_digest,
                "size_bytes": self.primary_data_size_bytes,
                "format": self.primary_data_format,
                "observed_row_count": self.primary_data_row_count,
            },
            "label": self.label,
            "experiment_type": self.experiment_type,
            "linked_context": [item.to_dict() for item in self.linked_context],
        }


@dataclass(frozen=True)
class MeasurementRecordHandoffPreparationRun:
    """Read-only preparation result for handoff package export."""

    record_id: str
    storage_root: Path
    linked_context_selection: tuple[MeasurementRecordHandoffLinkedContextSelection, ...] = ()
    packageable_record: PackageableMeasurementRecord | None = None
    initial_error: str | None = None
    refresh_run: SelectedRecordReadModelRefreshRun | None = None
    preparation_error: str | None = None

    @property
    def prepared(self) -> bool:
        return self.packageable_record is not None and self.preparation_error is None

    @property
    def classification(self) -> str:
        if self.prepared:
            return "prepared_measurement_record_for_handoff"
        return "blocked_before_measurement_record_handoff_preparation"

    @property
    def block_reason(self) -> str | None:
        if self.prepared:
            return None
        error = self.preparation_error or self.initial_error or ""
        if (
            self.initial_error is not None
            and "record read model is required" in self.initial_error
            and self.preparation_error is not None
            and self.preparation_error != self.initial_error
        ):
            return "read_model_refresh_failed"
        if "read model is required" in error or "is required" in error:
            return "missing_record_evidence"
        if "schema is unsupported" in error or "must be JSON" in error:
            return "invalid_read_model"
        if "requires complete" in error:
            return "record_not_complete"
        if "must stay under record_dir" in error:
            return "record_path_scope_violation"
        if "must match writer receipt" in error or "must match request" in error:
            return "record_evidence_mismatch"
        if self.refresh_run is not None and not self.refresh_run.refreshed:
            return "read_model_refresh_failed"
        return "record_handoff_preparation_failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "block_reason": self.block_reason,
            "record_id": self.record_id,
            "storage_root": str(self.storage_root),
            "linked_context_selection": [item.to_dict() for item in self.linked_context_selection],
            "packageable_record": (
                None if self.packageable_record is None else self.packageable_record.to_dict()
            ),
            "initial_error": self.initial_error,
            "refresh": None if self.refresh_run is None else self.refresh_run.to_dict(),
            "preparation_error": self.preparation_error,
        }


def prepare_measurement_record_for_handoff(
    record_id: str,
    *,
    storage_root: str | Path,
    linked_context_selection: tuple[MeasurementRecordHandoffLinkedContextSelection, ...] = (),
    preview_row_limit: int = 2,
) -> MeasurementRecordHandoffPreparationRun:
    """Prepare one canonical complete Measurement Record for handoff export."""

    validate_public_identifier(record_id, "handoff preparation record_id")
    storage = existing_directory_root(Path(storage_root), "handoff preparation storage root")
    record_dir = canonical_record_dir(record_id)
    read_model_path = f"{record_dir}/{READ_MODEL_FILENAME}"

    try:
        packageable = _read_packageable_record(
            storage,
            record_id=record_id,
            record_dir=record_dir,
            read_model_path=read_model_path,
            linked_context_selection=linked_context_selection,
        )
    except ValueError as exc:
        initial_error = str(exc)
    else:
        return MeasurementRecordHandoffPreparationRun(
            record_id=record_id,
            storage_root=storage,
            linked_context_selection=linked_context_selection,
            packageable_record=packageable,
        )

    if not _should_refresh_before_preparation(initial_error):
        return MeasurementRecordHandoffPreparationRun(
            record_id=record_id,
            storage_root=storage,
            linked_context_selection=linked_context_selection,
            initial_error=initial_error,
            preparation_error=initial_error,
        )

    try:
        refresh_run = refresh_selected_record_read_model_for_export(
            record_id=record_id,
            record_dir=record_dir,
            read_model_path=read_model_path,
            storage_root=storage,
            preview_row_limit=preview_row_limit,
        )
    except ValueError as exc:
        return MeasurementRecordHandoffPreparationRun(
            record_id=record_id,
            storage_root=storage,
            linked_context_selection=linked_context_selection,
            initial_error=initial_error,
            preparation_error=str(exc),
        )
    if not refresh_run.refreshed:
        return MeasurementRecordHandoffPreparationRun(
            record_id=record_id,
            storage_root=storage,
            linked_context_selection=linked_context_selection,
            initial_error=initial_error,
            refresh_run=refresh_run,
            preparation_error=refresh_run.refresh_error or "read model refresh failed",
        )

    try:
        packageable = _read_packageable_record(
            storage,
            record_id=record_id,
            record_dir=record_dir,
            read_model_path=read_model_path,
            linked_context_selection=linked_context_selection,
        )
    except ValueError as exc:
        return MeasurementRecordHandoffPreparationRun(
            record_id=record_id,
            storage_root=storage,
            linked_context_selection=linked_context_selection,
            initial_error=initial_error,
            refresh_run=refresh_run,
            preparation_error=str(exc),
        )
    return MeasurementRecordHandoffPreparationRun(
        record_id=record_id,
        storage_root=storage,
        linked_context_selection=linked_context_selection,
        packageable_record=packageable,
        initial_error=initial_error,
        refresh_run=refresh_run,
    )


def _read_packageable_record(
    root: Path,
    *,
    record_id: str,
    record_dir: str,
    read_model_path: str,
    linked_context_selection: tuple[MeasurementRecordHandoffLinkedContextSelection, ...],
) -> PackageableMeasurementRecord:
    read_model = _read_json(root, read_model_path, "record read model")
    manifest = _read_json(root, f"{record_dir}/{RECORD_MANIFEST_NAME}", "record manifest")
    writer_receipt_path = _writer_receipt_path(read_model)
    writer_receipt = _read_json(root, writer_receipt_path, "writer receipt")
    _validate_read_model_primary_scope(record_dir, read_model)
    _validate_record_continuity(record_id, record_dir, read_model, manifest, writer_receipt)
    return _packageable_record(
        record_id=record_id,
        record_dir=record_dir,
        read_model=read_model,
        manifest=manifest,
        writer_receipt=writer_receipt,
        linked_context_selection=linked_context_selection,
    )


def _read_json(root: Path, relative_path: str, owner: str) -> dict[str, Any]:
    validate_relative_path(relative_path, owner)
    target = path_under(root, relative_path, owner)
    if not target.is_file():
        raise ValueError(f"{owner} is required")
    try:
        content = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{owner} must be JSON") from exc
    if not isinstance(content, dict):
        raise ValueError(f"{owner} must be an object")
    if owner == "record read model" and content.get("schema") != SELECTED_RECORD_READ_MODEL_SCHEMA:
        raise ValueError("record read model schema is unsupported")
    return content


def _writer_receipt_path(read_model: dict[str, Any]) -> str:
    sources = _require_dict(read_model, "sources")
    writer = _require_dict(sources, "writer_receipt")
    return _require_text(writer, "path")


def _validate_read_model_primary_scope(record_dir: str, read_model: dict[str, Any]) -> None:
    primary_data = _require_dict(read_model, "primary_data")
    primary_path = _require_text(primary_data, "path")
    validate_relative_path(primary_path, "handoff preparation primary data path")
    validate_strict_child_path(
        primary_path,
        record_dir,
        "handoff preparation primary data path",
    )


def _validate_record_continuity(
    record_id: str,
    record_dir: str,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
) -> None:
    read_model_record = _require_dict(read_model, "record")
    manifest_record = _require_dict(manifest, "record")
    writer_record = _require_dict(writer_receipt, "record")
    if read_model_record.get("record_id") != record_id:
        raise ValueError("record read model record_id must match request")
    if read_model_record.get("record_dir") != record_dir:
        raise ValueError("record read model record_dir must match request")
    if read_model_record.get("lifecycle_state") != "complete":
        raise ValueError("record handoff preparation requires complete read model lifecycle")
    if manifest_record.get("record_id") != record_id:
        raise ValueError("record manifest record_id must match request")
    if writer_record.get("record_id") != record_id:
        raise ValueError("writer receipt record_id must match request")
    if writer_record.get("record_dir") != record_dir:
        raise ValueError("writer receipt record_dir must match request")
    writer_primary = _require_dict(writer_receipt, "primary_data")
    model_primary = _require_dict(read_model, "primary_data")
    if writer_primary.get("path") != model_primary.get("path"):
        raise ValueError("primary data path must match writer receipt")
    if writer_primary.get("digest") != model_primary.get("digest"):
        raise ValueError("primary data digest must match writer receipt")
    if writer_primary.get("size_bytes") != model_primary.get("size_bytes"):
        raise ValueError("primary data size must match writer receipt")


def _packageable_record(
    *,
    record_id: str,
    record_dir: str,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
    linked_context_selection: tuple[MeasurementRecordHandoffLinkedContextSelection, ...],
) -> PackageableMeasurementRecord:
    record = _require_dict(read_model, "record")
    primary = _require_dict(read_model, "primary_data")
    manifest_record = _require_dict(manifest, "record")
    writer_primary = _require_dict(writer_receipt, "primary_data")
    return PackageableMeasurementRecord(
        record_id=record_id,
        lifecycle_state=_require_text(record, "lifecycle_state"),
        primary_data_path=_require_text(primary, "path"),
        primary_data_digest=_require_text(primary, "digest"),
        primary_data_size_bytes=_require_int(primary, "size_bytes"),
        primary_data_format=_require_text(writer_primary, "format"),
        primary_data_row_count=_require_int(primary, "observed_row_count"),
        label=_optional_text(manifest_record, "label"),
        experiment_type=_optional_text(manifest_record, "experiment_type"),
        linked_context=tuple(
            _project_linked_context(item, record_dir=record_dir)
            for item in linked_context_selection
        ),
    )


def _project_linked_context(
    item: MeasurementRecordHandoffLinkedContextSelection,
    *,
    record_dir: str,
) -> PackageableMeasurementRecordLinkedContext:
    if item.source_path is not None:
        validate_strict_child_path(
            item.source_path,
            record_dir,
            "handoff context source_path",
        )
    return PackageableMeasurementRecordLinkedContext(
        link_id=item.link_id,
        kind=item.kind,
        label=item.label,
        relation=item.relation,
        reason=item.reason,
        context_reference=None if item.context_reference is None else dict(item.context_reference),
        source_path=item.source_path,
        package_path=item.package_path,
        expected_digest=item.expected_digest,
        expected_size_bytes=item.expected_size_bytes,
    )


def _should_refresh_before_preparation(error: str) -> bool:
    return (
        "record read model is required" in error
        or "record read model schema is unsupported" in error
        or "record read model must be JSON" in error
        or "primary data digest must match writer receipt" in error
        or "primary data size must match writer receipt" in error
        or "primary data path must match writer receipt" in error
    )


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} is required")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def _require_int(source: dict[str, Any], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} is required")
    return value
