"""Attach converted primary data to an existing legacy measurement record."""

from __future__ import annotations

import csv
import io
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
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import path_under as _path_under_common
from scopecat.measurement_records._storage import sha256 as _sha256
from scopecat.measurement_records._storage import (
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.durable_import import (
    FINALIZATION_RECEIPT_SCHEMA,
    WRITER_RECEIPT_SCHEMA,
    MeasurementRecordImportSource,
)
from scopecat.measurement_records.legacy_run import LEGACY_RUN_RECEIPT_SCHEMA
from scopecat.measurement_records.normalized_primary_table import (
    summarize_observed_primary_table_for_read_view,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_FILENAME, READ_MODEL_SCHEMA

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
            "artifact_posture": "local_legacy_primary_import_receipt",
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
        table, findings = summarize_observed_primary_table_for_read_view(
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
    path = _path_under(content_root, request.import_source.content_ref)
    _ensure_no_symlink_parents(
        content_root,
        request.import_source.content_ref,
        "legacy primary import source",
    )
    if path.is_symlink():
        raise ValueError("legacy primary import source must not be a symlink")
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("legacy primary import source is unavailable") from exc
    if _sha256(content) != request.import_source.declared_digest:
        raise ValueError("legacy primary import source digest does not match")
    if len(content) != request.import_source.size_bytes:
        raise ValueError("legacy primary import source size does not match")
    if _count_normalized_csv_rows(content) != request.import_source.rows_recorded:
        raise ValueError("legacy primary import source row count does not match")
    return content


def _count_normalized_csv_rows(content: bytes) -> int:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("legacy primary import source must be utf-8 CSV") from exc
    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("legacy primary import source requires a CSV header") from exc
    if not header:
        raise ValueError("legacy primary import source requires a CSV header")
    if any(name.strip() == "" for name in header):
        raise ValueError("legacy primary import source CSV headers must be non-blank")
    if len(set(header)) != len(header):
        raise ValueError("legacy primary import source requires unique CSV headers")
    rows = 0
    for row in reader:
        if len(row) != len(header):
            raise ValueError("legacy primary import source rows must match the CSV header")
        rows += 1
    return rows


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
    primary_digest = _sha256(primary_content)
    manifest_content = _json_bytes(manifest)
    writer_receipt_content = _json_bytes(
        _writer_receipt(request, manifest=manifest, primary_content=primary_content)
    )
    finalization_receipt_content = _json_bytes(
        _finalization_receipt(request, primary_digest=primary_digest, table=table)
    )
    read_model_content = _json_bytes(
        _read_model(
            request,
            manifest=manifest,
            table=table,
            manifest_digest=_sha256(manifest_content),
            writer_receipt_digest=_sha256(writer_receipt_content),
            finalization_receipt_digest=_sha256(finalization_receipt_content),
            primary_size=len(primary_content),
        )
    )

    _write_new_file(_path_under(storage, request.primary_data_path), primary_content)
    _write_new_file(_path_under(storage, request.writer_receipt_path), writer_receipt_content)
    _write_new_file(
        _path_under(storage, request.finalization_receipt_path), finalization_receipt_content
    )
    try:
        read_model_writer(_path_under(storage, request.read_model_path), read_model_content)
    except Exception as exc:
        raise ValueError(f"legacy primary import read model write failed: {exc}") from exc
    return {
        "record_id": request.record_id,
        "record_dir": request.record_dir,
        "primary_data_path": request.primary_data_path,
        "writer_receipt_path": request.writer_receipt_path,
        "finalization_receipt_path": request.finalization_receipt_path,
        "read_model_path": request.read_model_path,
        "primary_data_digest": primary_digest,
        "read_model_digest": _sha256(read_model_content),
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


def _writer_receipt(
    request: LegacyPrimaryImportRequest,
    *,
    manifest: dict[str, Any],
    primary_content: bytes,
) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    source = request.import_source
    return {
        "schema": WRITER_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "creation_lifecycle_state": record["lifecycle_state"],
        },
        "writer_request": {
            "request_id": f"{request.request_id}-write",
            "primary_data_path": request.primary_data_path,
            "writer_receipt_path": request.writer_receipt_path,
            "primary_data_format": source.primary_data_format,
            "expected_rows": source.rows_recorded,
        },
        "primary_data": {
            "path": request.primary_data_path,
            "format": source.primary_data_format,
            "digest": _sha256(primary_content),
            "size_bytes": len(primary_content),
            "rows_recorded": source.rows_recorded,
        },
        "source": source.to_dict(),
    }


def _finalization_receipt(
    request: LegacyPrimaryImportRequest,
    *,
    primary_digest: str,
    table: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": FINALIZATION_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "writer_receipt_path": request.writer_receipt_path,
        },
        "finalization": {
            "request_id": f"{request.request_id}-finalize",
            "final_state": "complete",
            "operator_reason": None,
            "evidence": {
                "read_view_classification": table["classification"],
                "primary_data_path": request.primary_data_path,
                "primary_data_digest": primary_digest,
                "rows_recorded": request.import_source.rows_recorded,
                "table_row_count": table["row_count"],
            },
        },
    }


def _read_model(
    request: LegacyPrimaryImportRequest,
    *,
    manifest: dict[str, Any],
    table: dict[str, Any],
    manifest_digest: str,
    writer_receipt_digest: str,
    finalization_receipt_digest: str,
    primary_size: int,
) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    return {
        "schema": READ_MODEL_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "lifecycle_state": "complete",
            "creation_lifecycle_state": record["lifecycle_state"],
        },
        "sources": {
            "creation_manifest": {
                "path": request.creation_manifest_path,
                "schema": MANIFEST_SCHEMA,
                "digest": manifest_digest,
            },
            "writer_receipt": {
                "path": request.writer_receipt_path,
                "schema": WRITER_RECEIPT_SCHEMA,
                "digest": writer_receipt_digest,
            },
            "finalization_receipt": {
                "path": request.finalization_receipt_path,
                "schema": FINALIZATION_RECEIPT_SCHEMA,
                "digest": finalization_receipt_digest,
            },
            "read_view": {
                "classification": table["classification"],
            },
        },
        "primary_data": {
            "path": request.primary_data_path,
            "format": table["format"],
            "digest": request.import_source.declared_digest,
            "size_bytes": primary_size,
            "declared_row_count": request.import_source.rows_recorded,
            "observed_row_count": table["row_count"],
        },
        "table": {
            "classification": table["classification"],
            "columns": table["columns"],
            "preview": table["preview"],
        },
        "review": {
            "findings": [],
        },
        "finalization": {
            "final_state": "complete",
            "operator_reason": None,
        },
    }


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


def _json_bytes(content: dict[str, Any]) -> bytes:
    return (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
