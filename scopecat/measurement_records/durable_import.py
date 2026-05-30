"""Durable new-record import through the measurement-record pipeline."""

from __future__ import annotations

import copy
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

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
from scopecat.measurement_records.creation import (
    MeasurementRecordCreationRequest,
    MeasurementRecordCreationRun,
    create_measurement_record_from_request,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.finalization import (
    MeasurementRecordFinalizationRequest,
    MeasurementRecordFinalizationRun,
    finalize_measurement_record_from_read_view,
)
from scopecat.measurement_records.read_model_projection import (
    MeasurementRecordReadModelProjectionRequest,
    MeasurementRecordReadModelProjectionRun,
    project_measurement_record_read_model_from_read_view,
)
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    MeasurementRecordReadRun,
    read_created_record_primary_table_from_request,
)
from scopecat.measurement_records.writer_integration import (
    MeasurementRecordWriterChunk,
    MeasurementRecordWriterRequest,
    MeasurementRecordWriterRun,
    validate_positive_integer,
    validate_sha256_digest,
    write_created_record_primary_data_from_request,
)

DURABLE_IMPORT_SCHEMA = "scopecat.measurement_record_durable_import.v0"
DURABLE_IMPORT_POLICY = {
    "workflow_authority": "approved_measurement_record_durable_import_request",
    "source_authority": "reviewed_normalized_primary_data_facts",
    "record_creation": "create_new_measurement_record",
    "primary_data_materialization": "write_created_record_primary_data",
    "read_view": "read_created_record_primary_table",
    "lifecycle_finalization": "finalize_measurement_record_complete",
    "read_model_projection": "project_measurement_record_read_model",
    "record_manifest": "not_replaced",
    "existing_record_update": "not_performed",
    "collision_policy": "no_overwrite_new_record",
    "rollback": "best_effort_synchronous_new_record_cleanup",
    "storage_root_concurrency": "not_supported",
    "final_storage_schema": "not_defined",
}
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
SOURCE_KINDS = {
    "adapter_normalized_primary_data",
    "fixture_normalized_primary_data",
    "handoff_package",
}
CREATION_SOURCE_KINDS = {"import", "handoff"}
PRIMARY_DATA_FORMATS = {"csv_table"}
DOES_NOT_CLAIM = [
    "existing_record_import_or_update",
    "attach_to_existing_created_shell",
    "primary_data_merge_or_compaction",
    "manifest_replacement",
    "linked_context_payload_import",
    "adapter_transport_or_discovery",
    "package_authenticity_or_trust",
    "conflict_resolution_beyond_no_overwrite",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "public_storage_schema",
]
_DurableImportPipelineRun = (
    MeasurementRecordCreationRun
    | MeasurementRecordWriterRun
    | MeasurementRecordReadRun
    | MeasurementRecordFinalizationRun
    | MeasurementRecordReadModelProjectionRun
)


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
        return f"{self.record_dir}/record-manifest.json"

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
    """Local receipt for durable new-record import."""

    request: MeasurementRecordDurableImportRequest
    storage_root: Path
    content_root: Path
    creation_run: MeasurementRecordCreationRun | None = None
    writer_run: MeasurementRecordWriterRun | None = None
    read_view_run: MeasurementRecordReadRun | None = None
    finalization_run: MeasurementRecordFinalizationRun | None = None
    projection_run: MeasurementRecordReadModelProjectionRun | None = None
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
            "durable_import_policy": copy.deepcopy(DURABLE_IMPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_durable_import_request",
                    "preflight_normalized_source",
                    *(
                        []
                        if not self.imported
                        else [
                            "create_measurement_record",
                            "write_created_record_primary_data",
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
                "performed": self.imported,
                "rollback_performed": self.rollback_performed,
                "partial_commit": self.partial_commit,
                "import_error": self.import_error,
            },
            "pipeline": {
                "creation": _run_classification(self.creation_run),
                "writer": _run_classification(self.writer_run),
                "read_view": _run_classification(self.read_view_run),
                "finalization": _run_classification(self.finalization_run),
                "projection": _run_classification(self.projection_run),
            },
        }


def import_measurement_record(
    source: dict[str, Any],
    *,
    content_root: str | Path,
    storage_root: str | Path,
) -> MeasurementRecordDurableImportRun:
    """Import reviewed normalized data into a new record from a raw source."""

    request = _parse_source(source)
    return import_measurement_record_from_request(
        request,
        content_root=content_root,
        storage_root=storage_root,
    )


def import_measurement_record_from_request(
    request: MeasurementRecordDurableImportRequest,
    *,
    content_root: str | Path,
    storage_root: str | Path,
    projection_model_writer: Callable[[Path, bytes], None] | None = None,
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

    creation_run = writer_run = read_view_run = finalization_run = projection_run = None
    guard = _DurableImportMutationGuard(storage, request)
    with guard:
        guard.stage("preflight")
        _preflight_source(request, content)
        guard.stage("creation")
        creation_run = create_measurement_record_from_request(
            _creation_request(request),
            storage_root=storage,
        )
        if not creation_run.created:
            raise _DurableImportFailure(_classification_error("creation", creation_run))
        guard.mark_mutation_started(creation_run)

        guard.stage("writer")
        writer_run = write_created_record_primary_data_from_request(
            _writer_request(request),
            content_root=content,
            storage_root=storage,
        )
        if not writer_run.written:
            raise _DurableImportFailure(_classification_error("writer", writer_run))

        guard.stage("read_view")
        read_view_run = read_created_record_primary_table_from_request(
            _read_request(request),
            storage_root=storage,
        )
        guard.stage("finalization")
        finalization_run = finalize_measurement_record_from_read_view(
            _finalization_request(request),
            read_view=read_view_run,
            storage_root=storage,
        )
        if not finalization_run.finalized:
            raise _DurableImportFailure(_classification_error("finalization", finalization_run))

        guard.stage("projection")
        projection_run = project_measurement_record_read_model_from_read_view(
            _projection_request(request),
            read_view=read_view_run,
            storage_root=storage,
            model_writer=projection_model_writer,
        )
        if not projection_run.projected:
            raise _DurableImportFailure(_classification_error("projection", projection_run))

    if guard.import_error is not None:
        return MeasurementRecordDurableImportRun(
            request=request,
            storage_root=storage,
            content_root=content,
            creation_run=creation_run,
            writer_run=writer_run,
            read_view_run=read_view_run,
            finalization_run=finalization_run,
            projection_run=projection_run,
            rollback_performed=guard.rollback_performed,
            partial_commit=guard.partial_commit,
            import_error=guard.import_error,
        )

    return MeasurementRecordDurableImportRun(
        request=request,
        storage_root=storage,
        content_root=content,
        creation_run=creation_run,
        writer_run=writer_run,
        read_view_run=read_view_run,
        finalization_run=finalization_run,
        projection_run=projection_run,
    )


def _parse_source(source: dict[str, Any]) -> MeasurementRecordDurableImportRequest:
    if source.get("durable_import_schema") != DURABLE_IMPORT_SCHEMA:
        raise ValueError(f"durable import source schema must be {DURABLE_IMPORT_SCHEMA}")
    if source.get("durable_import_policy") != DURABLE_IMPORT_POLICY:
        raise ValueError("durable import source policy is unsupported")
    request = _require_dict(source, "durable_import_request")
    source_facts = _require_dict(request, "import_source")
    return MeasurementRecordDurableImportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        primary_data_path=_require_text(request, "primary_data_path"),
        writer_receipt_path=_require_text(request, "writer_receipt_path"),
        finalization_receipt_path=_require_text(request, "finalization_receipt_path"),
        read_model_path=_require_text(request, "read_model_path"),
        creation_source_kind=_optional_text(request, "creation_source_kind", default="import"),
        label=_optional_text(request, "label", default=None),
        experiment_type=_optional_text(request, "experiment_type", default=None),
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


def _preflight_source(request: MeasurementRecordDurableImportRequest, content_root: Path) -> None:
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


def _creation_request(
    request: MeasurementRecordDurableImportRequest,
) -> MeasurementRecordCreationRequest:
    return MeasurementRecordCreationRequest(
        request_id=f"{request.request_id}-create",
        approval_state=request.approval_state,
        record_id=request.record_id,
        record_dir=request.record_dir,
        initial_lifecycle_state="created",
        creation_source_kind=request.creation_source_kind,
        label=request.label,
        experiment_type=request.experiment_type,
    )


def _writer_request(
    request: MeasurementRecordDurableImportRequest,
) -> MeasurementRecordWriterRequest:
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


def _read_request(request: MeasurementRecordDurableImportRequest) -> MeasurementRecordReadRequest:
    return MeasurementRecordReadRequest(
        request_id=f"{request.request_id}-read",
        record_id=request.record_id,
        record_dir=request.record_dir,
        writer_receipt_path=request.writer_receipt_path,
    )


def _finalization_request(
    request: MeasurementRecordDurableImportRequest,
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
    request: MeasurementRecordDurableImportRequest,
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


@dataclass
class _DurableImportMutationGuard:
    storage_root: Path
    request: MeasurementRecordDurableImportRequest
    current_stage: str = "preflight"
    mutation_started: bool = False
    creation_run: MeasurementRecordCreationRun | None = None
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
            self.creation_run,
        )
        return True

    def stage(self, name: str) -> None:
        self.current_stage = name

    def mark_mutation_started(self, creation_run: MeasurementRecordCreationRun) -> None:
        self.mutation_started = True
        self.creation_run = creation_run


def _rollback_new_record(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
    mutation_started: bool,
    creation_run: MeasurementRecordCreationRun | None,
) -> tuple[bool, bool]:
    if not mutation_started:
        return False, False
    record_path = _path_under(storage_root, request.record_dir)
    try:
        shutil.rmtree(record_path)
    except FileNotFoundError:
        partial_commit = _remove_empty_created_parent_dirs(storage_root, request, creation_run)
        return True, partial_commit
    except OSError:
        return False, True
    partial_commit = _remove_empty_created_parent_dirs(storage_root, request, creation_run)
    return True, partial_commit


def _remove_empty_created_parent_dirs(
    storage_root: Path,
    request: MeasurementRecordDurableImportRequest,
    creation_run: MeasurementRecordCreationRun | None,
) -> bool:
    partial_commit = False
    record_dir = request.record_dir
    for relative_path in reversed(_created_paths(creation_run)):
        if relative_path == record_dir or relative_path.endswith("/record-manifest.json"):
            continue
        path = _path_under(storage_root, relative_path)
        if not path.exists():
            continue
        try:
            path.rmdir()
        except OSError:
            partial_commit = True
    return partial_commit


def _created_paths(creation_run: MeasurementRecordCreationRun | None) -> tuple[str, ...]:
    if creation_run is None:
        return ()
    return creation_run.created_paths


def _classification_error(owner: str, run: _DurableImportPipelineRun) -> str:
    return f"durable import {owner} step did not complete: {run.classification}"


class _DurableImportFailure(RuntimeError):
    pass


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "durable import path")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _run_classification(run: _DurableImportPipelineRun | None) -> str | None:
    if run is None:
        return None
    return run.classification


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
