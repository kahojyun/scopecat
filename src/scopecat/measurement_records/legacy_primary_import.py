"""Attach converted primary data to an existing legacy measurement record."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    MANIFEST_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records._primary_data_commit import (
    build_primary_data_commit_artifacts,
)
from scopecat.measurement_records._primary_data_source import (
    read_reviewed_primary_data_source,
)
from scopecat.measurement_records._primary_table_summary import (
    summarize_observed_primary_table,
)
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import path_under as _path_under_common
from scopecat.measurement_records._storage import (
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.durable_import import (
    MeasurementRecordImportSource,
)
from scopecat.measurement_records.legacy_run import LEGACY_RUN_RECEIPT_SCHEMA
from scopecat.measurement_records.read_model_shared import READ_MODEL_FILENAME

APPROVAL_STATES = {"approved", "rejected", "needs_review"}


@dataclass(frozen=True)
class LegacyPrimaryImportRequest:
    """Approved request to attach converted primary data to a legacy record."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    legacy_receipt_path: str
    primary_data_path: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str
    import_source: MeasurementRecordImportSource

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "legacy primary import request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("legacy primary import approval_state is unsupported")
        validate_public_identifier(self.record_id, "legacy primary import record_id")
        validate_relative_path(self.record_dir, "legacy primary import record_dir")
        for path, owner in (
            (self.legacy_receipt_path, "legacy primary import legacy_receipt_path"),
            (self.primary_data_path, "legacy primary import primary_data_path"),
            (self.writer_receipt_path, "legacy primary import writer_receipt_path"),
            (
                self.finalization_receipt_path,
                "legacy primary import finalization_receipt_path",
            ),
            (self.read_model_path, "legacy primary import read_model_path"),
        ):
            validate_relative_path(path, owner)
            _validate_strict_child_path(path, self.record_dir, owner)
        _validate_canonical_read_model_path(self.read_model_path, self.record_dir)
        _validate_non_overlapping_paths(
            (
                self.creation_manifest_path,
                self.legacy_receipt_path,
                self.primary_data_path,
                self.writer_receipt_path,
                self.finalization_receipt_path,
                self.read_model_path,
            ),
            "legacy primary import output paths",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "legacy_receipt_path": self.legacy_receipt_path,
            "primary_data_path": self.primary_data_path,
            "writer_receipt_path": self.writer_receipt_path,
            "finalization_receipt_path": self.finalization_receipt_path,
            "read_model_path": self.read_model_path,
            "import_source": self.import_source.to_dict(),
        }


@dataclass(frozen=True)
class LegacyPrimaryImportRun:
    """Local result for attaching converted primary data to a legacy record."""

    request: LegacyPrimaryImportRequest
    storage_root: Path
    content_root: Path
    attached_record: dict[str, Any] | None = None
    rollback_performed: bool = False
    import_error: str | None = None

    @property
    def attached(self) -> bool:
        return self.classification == "attached_legacy_primary_data"

    @property
    def classification(self) -> str:
        if self.import_error is not None:
            if self.rollback_performed:
                return "rolled_back_after_legacy_primary_import_failure"
            return "blocked_before_legacy_primary_import"
        if not self.request.approved:
            return "blocked_before_legacy_primary_import"
        return "attached_legacy_primary_data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "content_root": str(self.content_root),
            "attached_record": (
                None if self.attached_record is None else dict(self.attached_record)
            ),
            "import_result": {
                "performed": self.attached,
                "rollback_performed": self.rollback_performed,
                "import_error": self.import_error,
            },
        }


def attach_converted_primary_data_to_legacy_record_from_request(
    request: LegacyPrimaryImportRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    read_model_writer: Callable[[Path, bytes], None] | None = None,
) -> LegacyPrimaryImportRun:
    """Attach converted primary data to an existing legacy record."""

    content = _existing_directory_root(Path(content_root), "legacy primary import content root")
    storage = _existing_directory_root(Path(storage_root), "legacy primary import storage root")
    if not request.approved:
        return LegacyPrimaryImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
        )
    try:
        manifest = _validate_existing_legacy_record(storage, request)
        primary_content = _preflight_source(request, content)
        table, findings = summarize_observed_primary_table(
            primary_content,
            source=request.primary_data_path,
            declared_row_count=request.import_source.rows_recorded,
            preview_row_limit=5,
        )
        if findings:
            raise ValueError("legacy primary import primary table review needed")
        attached_record = _write_attached_primary_data(
            storage,
            request,
            manifest=manifest,
            primary_content=primary_content,
            table=table,
            read_model_writer=read_model_writer or _write_new_file,
        )
    except Exception as exc:
        rollback_performed = _rollback_created_artifacts(
            storage,
            [
                request.primary_data_path,
                request.writer_receipt_path,
                request.finalization_receipt_path,
                request.read_model_path,
            ],
        )
        return LegacyPrimaryImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
            rollback_performed=rollback_performed,
            import_error=str(exc),
        )

    return LegacyPrimaryImportRun(
        request=request,
        storage_root=storage,
        content_root=content,
        attached_record=attached_record,
    )


def _validate_existing_legacy_record(
    storage: Path,
    request: LegacyPrimaryImportRequest,
) -> dict[str, Any]:
    manifest = _read_json(storage, request.creation_manifest_path, "legacy primary import manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("legacy primary import manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("legacy primary import record_id must match manifest")
    storage_section = _require_dict(manifest, "storage")
    if storage_section.get("record_dir") != request.record_dir:
        raise ValueError("legacy primary import record_dir must match manifest")
    creation = _require_dict(manifest, "creation")
    if creation.get("source_kind") != "legacy_system":
        raise ValueError("legacy primary import requires a legacy_system record")
    primary_data = _require_dict(manifest, "primary_data")
    if primary_data.get("state") != "not_recorded":
        raise ValueError("legacy primary import requires primary_data to be not_recorded")

    receipt = _read_json(
        storage,
        request.legacy_receipt_path,
        "legacy primary import legacy receipt",
    )
    if receipt.get("schema") != LEGACY_RUN_RECEIPT_SCHEMA:
        raise ValueError("legacy primary import legacy receipt schema is unsupported")
    receipt_record = _require_dict(receipt, "record")
    if receipt_record.get("record_id") != request.record_id:
        raise ValueError("legacy primary import legacy receipt record_id must match request")
    if receipt_record.get("record_dir") != request.record_dir:
        raise ValueError("legacy primary import legacy receipt record_dir must match request")
    if request.import_source.source_id != request.record_id:
        raise ValueError("legacy primary import source_id must be the legacy record id")
    return manifest


def _preflight_source(request: LegacyPrimaryImportRequest, content_root: Path) -> bytes:
    return read_reviewed_primary_data_source(
        request.import_source,
        content_root=content_root,
        owner="legacy primary import source",
    )


def _write_attached_primary_data(
    storage: Path,
    request: LegacyPrimaryImportRequest,
    *,
    manifest: dict[str, Any],
    primary_content: bytes,
    table: dict[str, Any],
    read_model_writer: Callable[[Path, bytes], None],
) -> dict[str, Any]:
    _ensure_new_targets(storage, request)
    artifacts = build_primary_data_commit_artifacts(
        request_id=request.request_id,
        record_id=request.record_id,
        record_dir=request.record_dir,
        creation_manifest_path=request.creation_manifest_path,
        primary_data_path=request.primary_data_path,
        writer_receipt_path=request.writer_receipt_path,
        finalization_receipt_path=request.finalization_receipt_path,
        manifest=manifest,
        import_source=request.import_source,
        primary_content=primary_content,
        table=table,
    )

    _write_new_file(_path_under(storage, request.primary_data_path), primary_content)
    _write_new_file(
        _path_under(storage, request.writer_receipt_path),
        artifacts.writer_receipt_content,
    )
    _write_new_file(
        _path_under(storage, request.finalization_receipt_path),
        artifacts.finalization_receipt_content,
    )
    try:
        read_model_writer(
            _path_under(storage, request.read_model_path),
            artifacts.read_model_content,
        )
    except Exception as exc:
        raise ValueError(f"legacy primary import read model write failed: {exc}") from exc
    return {
        "record_id": request.record_id,
        "record_dir": request.record_dir,
        "primary_data_path": request.primary_data_path,
        "writer_receipt_path": request.writer_receipt_path,
        "finalization_receipt_path": request.finalization_receipt_path,
        "read_model_path": request.read_model_path,
        "primary_data_digest": artifacts.primary_digest,
        "read_model_digest": artifacts.read_model_digest,
    }


def _ensure_new_targets(storage: Path, request: LegacyPrimaryImportRequest) -> None:
    for relative_path in (
        request.primary_data_path,
        request.writer_receipt_path,
        request.finalization_receipt_path,
        request.read_model_path,
    ):
        _ensure_no_symlink_parents(storage, relative_path, "legacy primary import target")
        if (
            _path_under(storage, relative_path).exists()
            or _path_under(storage, relative_path).is_symlink()
        ):
            raise ValueError("legacy primary import target already exists")


def _read_json(root: Path, relative_path: str, owner: str) -> dict[str, Any]:
    target = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, owner)
    if target.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{owner} is unavailable") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{owner} must be a JSON object")
    return payload


def _rollback_created_artifacts(root: Path, relative_paths: list[str]) -> bool:
    removed = False
    for relative_path in reversed(relative_paths):
        target = _path_under(root, relative_path)
        try:
            target.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "legacy primary import path")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _validate_canonical_read_model_path(read_model_path: str, record_dir: str) -> None:
    if read_model_path != f"{record_dir}/{READ_MODEL_FILENAME}":
        raise ValueError("legacy primary import read_model_path must be the canonical path")


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(value: dict[str, Any], field: str, *, default: str | None) -> str | None:
    if field not in value:
        return default
    return validate_text(value[field], field)


def _require_int(value: dict[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item
