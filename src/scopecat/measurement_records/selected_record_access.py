"""Internal selected-record access helpers for downstream workflows."""

from __future__ import annotations

import hashlib
from pathlib import Path

from scopecat.measurement_records._contracts import validate_sha256_digest
from scopecat.measurement_records._storage import path_under
from scopecat.measurement_records.read_model_refresh import (
    MeasurementRecordReadModelRefreshRequest,
    MeasurementRecordReadModelRefreshRun,
    refresh_measurement_record_read_model_from_read_view,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_SCHEMA
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRequest,
    read_created_record_primary_table_from_request,
)

SELECTED_RECORD_READ_MODEL_SCHEMA = READ_MODEL_SCHEMA
SelectedRecordReadModelRefreshRun = MeasurementRecordReadModelRefreshRun


def refresh_selected_record_read_model_for_export(
    *,
    record_id: str,
    record_dir: str,
    read_model_path: str,
    storage_root: Path,
    preview_row_limit: int = 2,
) -> SelectedRecordReadModelRefreshRun:
    """Refresh selected-record read-model evidence before handoff export."""

    refresh_request, read_request = _pre_export_refresh_requests(
        record_id=record_id,
        record_dir=record_dir,
        read_model_path=read_model_path,
        storage_root=storage_root,
        preview_row_limit=preview_row_limit,
    )
    read_view = read_created_record_primary_table_from_request(
        read_request,
        storage_root=storage_root,
    )
    return refresh_measurement_record_read_model_from_read_view(
        refresh_request,
        read_view=read_view,
        storage_root=storage_root,
    )


def _pre_export_refresh_requests(
    *,
    record_id: str,
    record_dir: str,
    read_model_path: str,
    storage_root: Path,
    preview_row_limit: int,
) -> tuple[MeasurementRecordReadModelRefreshRequest, MeasurementRecordReadRequest]:
    expected_target_condition = "missing"
    expected_digest = None
    target = path_under(
        storage_root,
        read_model_path,
        "selected record preflight read model",
    )
    if target.exists():
        expected_target_condition = "replace_existing"
        expected_digest = validate_sha256_digest(_file_digest(target), "read model digest")

    return (
        MeasurementRecordReadModelRefreshRequest(
            request_id=f"pre-export-refresh-{record_id}",
            approval_state="approved",
            record_id=record_id,
            record_dir=record_dir,
            writer_receipt_path=f"{record_dir}/writer-receipt.json",
            finalization_receipt_path=f"{record_dir}/finalization-receipt.json",
            read_model_path=read_model_path,
            expected_target_condition=expected_target_condition,
            expected_current_read_model_digest=expected_digest,
        ),
        MeasurementRecordReadRequest(
            request_id=f"pre-export-read-{record_id}",
            record_id=record_id,
            record_dir=record_dir,
            writer_receipt_path=f"{record_dir}/writer-receipt.json",
            preview_row_limit=preview_row_limit,
        ),
    )


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
