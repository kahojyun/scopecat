"""Attach converted primary data to an existing legacy measurement record."""

from __future__ import annotations

import copy
import csv
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from scopecat.measurement_records.creation import (
    CANDIDATE_MANIFEST_SCHEMA,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.durable_import import MeasurementRecordImportSource
from scopecat.measurement_records.finalization import (
    MeasurementRecordFinalizationRequest,
    MeasurementRecordFinalizationRun,
    finalize_measurement_record_from_read_view,
)
from scopecat.measurement_records.legacy_run import LEGACY_RUN_RECEIPT_SCHEMA
from scopecat.measurement_records.read_model_projection import (
    MeasurementRecordReadModelProjectionRequest,
    MeasurementRecordReadModelProjectionRun,
    project_measurement_record_read_model_from_read_view,
)
from scopecat.measurement_records.read_model_shared import _validate_canonical_read_model_path
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    MeasurementRecordReadRun,
    read_created_record_primary_table_from_request,
)
from scopecat.measurement_records.writer_integration import (
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    MeasurementRecordWriterRun,
    write_created_record_primary_data_from_request,
)

LEGACY_PRIMARY_IMPORT_SCHEMA = "scopecat.measurement_record_legacy_primary_import.v0"
LEGACY_PRIMARY_IMPORT_POLICY = {
    "workflow_authority": "approved_legacy_primary_import_request",
    "record_authority": "existing_legacy_system_measurement_record",
    "legacy_receipt_authority": "record_local_legacy_run_receipt",
    "source_authority": "reviewed_converted_normalized_primary_data_facts",
    "primary_data_materialization": "write_primary_data_to_existing_legacy_record",
    "read_view": "read_created_record_primary_table",
    "lifecycle_finalization": "finalize_measurement_record_complete",
    "read_model_projection": "project_measurement_record_read_model",
    "record_manifest": "not_replaced",
    "collision_policy": "no_overwrite_existing_legacy_record_targets",
    "rollback": "best_effort_synchronous_created_artifact_cleanup",
    "final_storage_schema": "not_defined",
}
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
DOES_NOT_CLAIM = [
    "new_record_import",
    "manifest_replacement",
    "primary_data_merge_or_compaction",
    "legacy_payload_observation",
    "legacy_adapter_framework",
    "automatic_legacy_file_discovery",
    "record_id_generation_policy",
    "conflict_resolution_beyond_no_overwrite",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "public_storage_schema",
]


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
        _validate_canonical_read_model_path(
            self.read_model_path,
            self.record_dir,
            "legacy primary import read_model_path",
        )
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
    """Local receipt for attaching converted primary data to a legacy record."""

    request: LegacyPrimaryImportRequest
    storage_root: Path
    content_root: Path
    writer_run: MeasurementRecordWriterRun | None = None
    read_view_run: MeasurementRecordReadRun | None = None
    finalization_run: MeasurementRecordFinalizationRun | None = None
    projection_run: MeasurementRecordReadModelProjectionRun | None = None
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
            "legacy_primary_import_policy": copy.deepcopy(LEGACY_PRIMARY_IMPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_legacy_primary_import_request",
                    *(
                        []
                        if not self.request.approved
                        else [
                            "validate_existing_legacy_record",
                            "validate_legacy_receipt_continuity",
                            "preflight_converted_primary_data",
                        ]
                    ),
                    *(
                        []
                        if not self.attached
                        else [
                            "write_primary_data_to_legacy_record",
                            "read_created_record_primary_table",
                            "finalize_measurement_record",
                            "project_measurement_record_read_model",
                        ]
                    ),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "content_root": str(self.content_root),
            "import_result": {
                "performed": self.attached,
                "rollback_performed": self.rollback_performed,
                "import_error": self.import_error,
            },
            "pipeline": {
                "writer": _run_classification(self.writer_run),
                "read_view": _run_classification(self.read_view_run),
                "finalization": _run_classification(self.finalization_run),
                "projection": _run_classification(self.projection_run),
            },
        }


def attach_converted_primary_data_to_legacy_record(
    source: dict[str, Any],
    *,
    content_root: str | Path,
    storage_root: str | Path,
) -> LegacyPrimaryImportRun:
    """Attach converted primary data to an existing legacy record from raw input."""

    request = _parse_source(source)
    return attach_converted_primary_data_to_legacy_record_from_request(
        request,
        content_root=content_root,
        storage_root=storage_root,
    )


def attach_converted_primary_data_to_legacy_record_from_request(
    request: LegacyPrimaryImportRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    projection_model_writer: Callable[[Path, bytes], None] | None = None,
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
        _validate_existing_legacy_record(storage, request)
        _preflight_source(request, content)
    except Exception as exc:
        return LegacyPrimaryImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
            import_error=str(exc),
        )
    created_paths = [
        request.primary_data_path,
        request.writer_receipt_path,
        request.finalization_receipt_path,
        request.read_model_path,
    ]
    writer_run = read_view_run = finalization_run = projection_run = None
    try:
        writer_run = write_created_record_primary_data_from_request(
            _writer_request(request),
            content_root=content,
            storage_root=storage,
        )
        if not writer_run.written:
            raise _LegacyPrimaryImportFailure(
                _classification_error("writer", writer_run.classification)
            )
        read_view_run = read_created_record_primary_table_from_request(
            _read_request(request),
            storage_root=storage,
        )
        finalization_run = finalize_measurement_record_from_read_view(
            _finalization_request(request),
            read_view=read_view_run,
            storage_root=storage,
        )
        if not finalization_run.finalized:
            raise _LegacyPrimaryImportFailure(
                _classification_error("finalization", finalization_run.classification)
            )
        projection_run = project_measurement_record_read_model_from_read_view(
            _projection_request(request),
            read_view=read_view_run,
            storage_root=storage,
            model_writer=projection_model_writer,
        )
        if not projection_run.projected:
            raise _LegacyPrimaryImportFailure(
                _classification_error("projection", projection_run.classification)
            )
    except Exception as exc:
        return LegacyPrimaryImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
            writer_run=writer_run,
            read_view_run=read_view_run,
            finalization_run=finalization_run,
            projection_run=projection_run,
            rollback_performed=_rollback_created_artifacts(storage, created_paths),
            import_error=str(exc),
        )

    return LegacyPrimaryImportRun(
        request=request,
        storage_root=storage,
        content_root=content,
        writer_run=writer_run,
        read_view_run=read_view_run,
        finalization_run=finalization_run,
        projection_run=projection_run,
    )


def _parse_source(source: dict[str, Any]) -> LegacyPrimaryImportRequest:
    if source.get("legacy_primary_import_schema") != LEGACY_PRIMARY_IMPORT_SCHEMA:
        raise ValueError(
            f"legacy primary import source schema must be {LEGACY_PRIMARY_IMPORT_SCHEMA}"
        )
    if source.get("legacy_primary_import_policy") != LEGACY_PRIMARY_IMPORT_POLICY:
        raise ValueError("legacy primary import source policy is unsupported")
    request = _require_dict(source, "legacy_primary_import_request")
    source_facts = _require_dict(request, "import_source")
    return LegacyPrimaryImportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        legacy_receipt_path=_require_text(request, "legacy_receipt_path"),
        primary_data_path=_require_text(request, "primary_data_path"),
        writer_receipt_path=_require_text(request, "writer_receipt_path"),
        finalization_receipt_path=_require_text(request, "finalization_receipt_path"),
        read_model_path=_require_text(request, "read_model_path"),
        import_source=MeasurementRecordImportSource(
            source_kind=_require_text(source_facts, "source_kind"),
            source_id=_require_text(source_facts, "source_id"),
            source_item_id=_require_text(source_facts, "source_item_id"),
            content_ref=_require_text(source_facts, "content_ref"),
            declared_digest=_require_text(source_facts, "declared_digest"),
            size_bytes=_require_int(source_facts, "size_bytes"),
            rows_recorded=_require_int(source_facts, "rows_recorded"),
            primary_data_format=_optional_text(
                source_facts,
                "primary_data_format",
                default="csv_table",
            ),
        ),
    )


def _validate_existing_legacy_record(
    storage: Path,
    request: LegacyPrimaryImportRequest,
) -> None:
    manifest = _read_json(storage, request.creation_manifest_path, "legacy primary import manifest")
    if manifest.get("schema") != CANDIDATE_MANIFEST_SCHEMA:
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


def _preflight_source(request: LegacyPrimaryImportRequest, content_root: Path) -> None:
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


def _writer_request(request: LegacyPrimaryImportRequest) -> MeasurementRecordWriterRequest:
    chunk = MeasurementRecordWriterChunk(
        chunk_id=f"{request.import_source.source_item_id}-chunk",
        sequence=1,
        event_id=f"{request.request_id}-source",
        content_ref=request.import_source.content_ref,
        declared_digest=request.import_source.declared_digest,
        size_bytes=request.import_source.size_bytes,
        rows_recorded=request.import_source.rows_recorded,
        total_rows_recorded=request.import_source.rows_recorded,
    )
    return MeasurementRecordWriterRequest(
        request_id=f"{request.request_id}-write",
        approval_state=request.approval_state,
        record_id=request.record_id,
        record_dir=request.record_dir,
        primary_data_path=request.primary_data_path,
        writer_receipt_path=request.writer_receipt_path,
        primary_data_format=request.import_source.primary_data_format,
        expected_rows=request.import_source.rows_recorded,
        chunks=(chunk,),
    )


def _read_request(request: LegacyPrimaryImportRequest) -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id=f"{request.request_id}-read",
        record_id=request.record_id,
        record_dir=request.record_dir,
        writer_receipt_path=request.writer_receipt_path,
    )


def _finalization_request(
    request: LegacyPrimaryImportRequest,
) -> MeasurementRecordFinalizationRequest:
    return MeasurementRecordFinalizationRequest(
        request_id=f"{request.request_id}-finalize",
        approval_state=request.approval_state,
        record_id=request.record_id,
        record_dir=request.record_dir,
        writer_receipt_path=request.writer_receipt_path,
        finalization_receipt_path=request.finalization_receipt_path,
        final_state="complete",
    )


def _projection_request(
    request: LegacyPrimaryImportRequest,
) -> MeasurementRecordReadModelProjectionRequest:
    return MeasurementRecordReadModelProjectionRequest(
        request_id=f"{request.request_id}-project",
        approval_state=request.approval_state,
        record_id=request.record_id,
        record_dir=request.record_dir,
        writer_receipt_path=request.writer_receipt_path,
        finalization_receipt_path=request.finalization_receipt_path,
        read_model_path=request.read_model_path,
    )


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


def _classification_error(owner: str, classification: str) -> str:
    return f"legacy primary import {owner} step did not complete: {classification}"


def _run_classification(
    run: (
        MeasurementRecordWriterRun
        | MeasurementRecordReadRun
        | MeasurementRecordFinalizationRun
        | MeasurementRecordReadModelProjectionRun
        | None
    ),
) -> str | None:
    if run is None:
        return None
    return run.classification


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "legacy primary import path")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


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


class _LegacyPrimaryImportFailure(RuntimeError):
    pass
