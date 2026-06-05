"""Durable new-record import for normalized measurement data."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from scopecat.measurement_records._contracts import (
    FINALIZATION_RECEIPT_SCHEMA,
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    WRITER_RECEIPT_SCHEMA,
    validate_positive_integer,
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
    validate_text,
)
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import (
    path_under as _path_under_common,
)
from scopecat.measurement_records._storage import (
    sha256 as _sha256,
)
from scopecat.measurement_records._storage import (
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.normalized_primary_table import (
    summarize_observed_primary_table_for_read_view,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_FILENAME, READ_MODEL_SCHEMA

APPROVAL_STATES = {"approved", "rejected", "needs_review"}
SOURCE_KINDS = {
    "adapter_normalized_primary_data",
    "fixture_normalized_primary_data",
    "handoff_package",
}
CREATION_SOURCE_KINDS = {"import", "handoff"}
PRIMARY_DATA_FORMATS = {"csv_table"}


@dataclass(frozen=True)
class MeasurementRecordImportSource:
    """Reviewed normalized primary-data source facts for durable import."""

    source_kind: str
    source_id: str
    source_item_id: str
    content_ref: str
    declared_digest: str
    size_bytes: int
    rows_recorded: int
    primary_data_format: str = "csv_table"

    def __post_init__(self) -> None:
        if self.source_kind not in SOURCE_KINDS:
            raise ValueError("durable import source_kind is unsupported")
        validate_public_identifier(self.source_id, "durable import source_id")
        validate_public_identifier(self.source_item_id, "durable import source_item_id")
        validate_relative_path(self.content_ref, "durable import source content_ref")
        validate_sha256_digest(self.declared_digest, "durable import source declared_digest")
        validate_positive_integer(self.size_bytes, "durable import source size_bytes")
        validate_positive_integer(self.rows_recorded, "durable import source rows_recorded")
        validate_public_identifier(
            self.primary_data_format,
            "durable import source primary_data_format",
        )
        if self.primary_data_format not in PRIMARY_DATA_FORMATS:
            raise ValueError("durable import source primary_data_format is unsupported")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "source_item_id": self.source_item_id,
            "content_ref": self.content_ref,
            "declared_digest": self.declared_digest,
            "size_bytes": self.size_bytes,
            "rows_recorded": self.rows_recorded,
            "primary_data_format": self.primary_data_format,
        }


@dataclass(frozen=True)
class MeasurementRecordDurableImportRequest:
    """Approved request to import reviewed normalized data as a new record."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    primary_data_path: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str
    import_source: MeasurementRecordImportSource
    creation_source_kind: str = "import"
    label: str | None = None
    experiment_type: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "durable import request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("durable import approval_state is unsupported")
        validate_public_identifier(self.record_id, "durable import record_id")
        validate_relative_path(self.record_dir, "durable import record_dir")
        validate_relative_path(self.primary_data_path, "durable import primary_data_path")
        validate_relative_path(self.writer_receipt_path, "durable import writer_receipt_path")
        validate_relative_path(
            self.finalization_receipt_path,
            "durable import finalization_receipt_path",
        )
        validate_relative_path(self.read_model_path, "durable import read_model_path")
        _validate_strict_child_path(
            self.primary_data_path,
            self.record_dir,
            "durable import primary_data_path",
        )
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "durable import writer_receipt_path",
        )
        _validate_strict_child_path(
            self.finalization_receipt_path,
            self.record_dir,
            "durable import finalization_receipt_path",
        )
        _validate_strict_child_path(
            self.read_model_path,
            self.record_dir,
            "durable import read_model_path",
        )
        _validate_canonical_read_model_path(self.read_model_path, self.record_dir)
        if self.creation_source_kind not in CREATION_SOURCE_KINDS:
            raise ValueError("durable import creation_source_kind is unsupported")
        if self.label is not None:
            validate_text(self.label, "durable import label")
        if self.experiment_type is not None:
            validate_text(self.experiment_type, "durable import experiment_type")
        _validate_non_overlapping_paths(
            (
                self.creation_manifest_path,
                self.primary_data_path,
                self.writer_receipt_path,
                self.finalization_receipt_path,
                self.read_model_path,
            ),
            "durable import output paths",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    def to_dict(self) -> dict[str, Any]:
        request = {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "primary_data_path": self.primary_data_path,
            "writer_receipt_path": self.writer_receipt_path,
            "finalization_receipt_path": self.finalization_receipt_path,
            "read_model_path": self.read_model_path,
            "creation_source_kind": self.creation_source_kind,
            "import_source": self.import_source.to_dict(),
        }
        if self.label is not None:
            request["label"] = self.label
        if self.experiment_type is not None:
            request["experiment_type"] = self.experiment_type
        return request


@dataclass(frozen=True)
class MeasurementRecordDurableImportRun:
    """Local result for durable new-record import."""

    request: MeasurementRecordDurableImportRequest
    storage_root: Path
    content_root: Path
    stored_record: dict[str, Any] | None = None
    rollback_performed: bool = False
    import_error: str | None = None
    partial_commit: bool = False

    @property
    def imported(self) -> bool:
        return self.classification == "imported_new_record"

    @property
    def classification(self) -> str:
        if self.import_error is not None:
            if self.partial_commit:
                return "import_failed_after_partial_commit"
            if self.rollback_performed:
                return "rolled_back_after_import_failure"
            return "blocked_before_import"
        if not self.request.approved:
            return "blocked_before_import"
        return "imported_new_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_durable_import_receipt",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "content_root": str(self.content_root),
            "stored_record": None if self.stored_record is None else dict(self.stored_record),
            "import_result": {
                "performed": self.imported,
                "rollback_performed": self.rollback_performed,
                "partial_commit": self.partial_commit,
                "import_error": self.import_error,
            },
        }


def import_measurement_record_from_request(
    request: MeasurementRecordDurableImportRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    read_model_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordDurableImportRun:
    """Import reviewed normalized data into a new record from a typed request."""

    content = _existing_directory_root(Path(content_root), "durable import content root")
    storage = _existing_directory_root(Path(storage_root), "durable import storage root")
    if not request.approved:
        return MeasurementRecordDurableImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
        )

    guard = _DurableImportMutationGuard(storage, request)
    stored_record = None
    with guard:
        guard.stage("preflight")
        primary_content = _preflight_source(request, content)
        table, findings = summarize_observed_primary_table_for_read_view(
            primary_content,
            source=request.primary_data_path,
            declared_row_count=request.import_source.rows_recorded,
            preview_row_limit=5,
        )
        if findings:
            raise _DurableImportFailure("durable import primary table review needed")

        guard.stage("target_preflight")
        _ensure_new_record_targets(storage, request)
        guard.stage("write")
        guard.mark_mutation_started()
        stored_record = _write_imported_record(
            storage,
            request,
            primary_content,
            table,
            read_model_writer=read_model_writer or _write_new_file,
        )

    if guard.import_error is not None:
        return MeasurementRecordDurableImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
            rollback_performed=guard.rollback_performed,
            partial_commit=guard.partial_commit,
            import_error=guard.import_error,
        )

    return MeasurementRecordDurableImportRun(
        request=request,
        storage_root=storage,
        content_root=content,
        stored_record=stored_record,
    )


def _preflight_source(request: MeasurementRecordDurableImportRequest, content_root: Path) -> bytes:
    if request.import_source.primary_data_format != "csv_table":
        raise _DurableImportFailure("durable import source format is unsupported")
    path = _path_under(content_root, request.import_source.content_ref)
    _ensure_no_symlink_parents(
        content_root,
        request.import_source.content_ref,
        "durable import source",
    )
    if path.is_symlink():
        raise _DurableImportFailure("durable import source must not be a symlink")
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise _DurableImportFailure("durable import source is unavailable") from exc
    if _sha256(content) != request.import_source.declared_digest:
        raise _DurableImportFailure("durable import source digest does not match")
    if len(content) != request.import_source.size_bytes:
        raise _DurableImportFailure("durable import source size does not match")
    rows = _count_normalized_csv_rows(content)
    if rows != request.import_source.rows_recorded:
        raise _DurableImportFailure("durable import source row count does not match")
    return content


def _count_normalized_csv_rows(content: bytes) -> int:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _DurableImportFailure("durable import source must be utf-8 CSV") from exc
    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise _DurableImportFailure("durable import source requires a CSV header") from exc
    if not header:
        raise _DurableImportFailure("durable import source requires a CSV header")
    if any(name.strip() == "" for name in header):
        raise _DurableImportFailure("durable import source CSV headers must be non-blank")
    if len(set(header)) != len(header):
        raise _DurableImportFailure("durable import source requires unique CSV headers")

    rows = 0
    for row in reader:
        if len(row) != len(header):
            raise _DurableImportFailure("durable import source rows must match the CSV header")
        rows += 1
    return rows


def _write_imported_record(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
    primary_content: bytes,
    table: dict[str, Any],
    *,
    read_model_writer: Callable[[Path, bytes], None],
) -> dict[str, Any]:
    manifest_content = _json_bytes(_record_manifest(request))
    writer_receipt_content = _json_bytes(
        _writer_receipt(
            request,
            primary_content=primary_content,
        )
    )
    finalization_receipt_content = _json_bytes(
        _finalization_receipt(
            request,
            primary_digest=_sha256(primary_content),
            table=table,
        )
    )
    read_model_content = _json_bytes(
        _read_model(
            request,
            table=table,
            manifest_digest=_sha256(manifest_content),
            writer_receipt_digest=_sha256(writer_receipt_content),
            finalization_receipt_digest=_sha256(finalization_receipt_content),
            primary_size=len(primary_content),
        )
    )

    record_dir = _path_under(storage_root, request.record_dir)
    record_dir.mkdir(parents=True)
    _write_new_file(_path_under(storage_root, request.creation_manifest_path), manifest_content)
    _write_new_file(_path_under(storage_root, request.primary_data_path), primary_content)
    _write_new_file(_path_under(storage_root, request.writer_receipt_path), writer_receipt_content)
    _write_new_file(
        _path_under(storage_root, request.finalization_receipt_path),
        finalization_receipt_content,
    )
    try:
        read_model_writer(_path_under(storage_root, request.read_model_path), read_model_content)
    except Exception as exc:
        raise _DurableImportFailure(f"durable import read model write failed: {exc}") from exc

    return {
        "record_id": request.record_id,
        "record_dir": request.record_dir,
        "creation_manifest_path": request.creation_manifest_path,
        "primary_data_path": request.primary_data_path,
        "writer_receipt_path": request.writer_receipt_path,
        "finalization_receipt_path": request.finalization_receipt_path,
        "read_model_path": request.read_model_path,
        "primary_data_digest": _sha256(primary_content),
        "read_model_digest": _sha256(read_model_content),
    }


def _ensure_new_record_targets(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
) -> None:
    if os.path.lexists(_path_under(storage_root, request.record_dir)):
        raise _DurableImportFailure("durable import record_dir target already exists")
    _ensure_no_symlink_parents(storage_root, request.record_dir, "durable import record_dir")
    for relative_path in (
        request.creation_manifest_path,
        request.primary_data_path,
        request.writer_receipt_path,
        request.finalization_receipt_path,
        request.read_model_path,
    ):
        _ensure_no_symlink_parents(storage_root, relative_path, "durable import target")
        if os.path.lexists(_path_under(storage_root, relative_path)):
            raise _DurableImportFailure("durable import target already exists")


def _record_manifest(request: MeasurementRecordDurableImportRequest) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": request.record_id,
        "lifecycle_state": "created",
    }
    if request.label is not None:
        record["label"] = request.label
    if request.experiment_type is not None:
        record["experiment_type"] = request.experiment_type

    return {
        "schema": MANIFEST_SCHEMA,
        "record": record,
        "creation": {
            "request_id": f"{request.request_id}-create",
            "source_kind": request.creation_source_kind,
            "source_kind_authority": "declared_provenance_only",
        },
        "storage": {
            "record_dir": request.record_dir,
            "manifest_path": request.creation_manifest_path,
        },
        "primary_data": {
            "state": "not_recorded",
            "references": [],
        },
    }


def _writer_receipt(
    request: MeasurementRecordDurableImportRequest,
    *,
    primary_content: bytes,
) -> dict[str, Any]:
    primary_digest = _sha256(primary_content)
    source = request.import_source
    return {
        "schema": WRITER_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "creation_lifecycle_state": "created",
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
            "digest": primary_digest,
            "size_bytes": len(primary_content),
            "rows_recorded": source.rows_recorded,
        },
        "source": source.to_dict(),
    }


def _finalization_receipt(
    request: MeasurementRecordDurableImportRequest,
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
    request: MeasurementRecordDurableImportRequest,
    *,
    table: dict[str, Any],
    manifest_digest: str,
    writer_receipt_digest: str,
    finalization_receipt_digest: str,
    primary_size: int,
) -> dict[str, Any]:
    return {
        "schema": READ_MODEL_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "lifecycle_state": "complete",
            "creation_lifecycle_state": "created",
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


@dataclass
class _DurableImportMutationGuard:
    storage_root: Path
    request: MeasurementRecordDurableImportRequest
    current_stage: str = "preflight"
    mutation_started: bool = False
    rollback_performed: bool = False
    partial_commit: bool = False
    import_error: str | None = None

    def __enter__(self) -> _DurableImportMutationGuard:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc is None:
            return False
        if exc_type is not None and not issubclass(exc_type, Exception):
            return False
        if isinstance(exc, _DurableImportFailure):
            self.import_error = str(exc)
        else:
            self.import_error = f"durable import {self.current_stage} step failed: {exc}"
        self.rollback_performed, self.partial_commit = _rollback_new_record(
            self.storage_root,
            self.request,
            self.mutation_started,
        )
        return True

    def stage(self, name: str) -> None:
        self.current_stage = name

    def mark_mutation_started(self) -> None:
        self.mutation_started = True


def _rollback_new_record(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
    mutation_started: bool,
) -> tuple[bool, bool]:
    if not mutation_started:
        return False, False
    record_path = _path_under(storage_root, request.record_dir)
    try:
        shutil.rmtree(record_path)
    except FileNotFoundError:
        return True, _remove_empty_created_parent_dirs(storage_root, request)
    except OSError:
        return False, True
    return True, _remove_empty_created_parent_dirs(storage_root, request)


def _remove_empty_created_parent_dirs(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
) -> bool:
    partial_commit = False
    parts = Path(validate_relative_path(request.record_dir, "durable import record_dir")).parts
    for depth in range(len(parts) - 1, 0, -1):
        path = storage_root.joinpath(*parts[:depth])
        if not path.exists():
            continue
        try:
            path.rmdir()
        except OSError:
            partial_commit = True
            break
    return partial_commit


class _DurableImportFailure(RuntimeError):
    pass


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "durable import path")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _validate_canonical_read_model_path(read_model_path: str, record_dir: str) -> None:
    if read_model_path != f"{record_dir}/{READ_MODEL_FILENAME}":
        raise ValueError("durable import read_model_path must be the canonical path")


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
    if field not in value or value[field] is None:
        return default
    return validate_text(value[field], field)


def _require_int(value: dict[str, Any], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"{field} must be an integer")
    return item
