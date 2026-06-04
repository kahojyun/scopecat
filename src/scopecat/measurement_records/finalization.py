"""Receipt-based lifecycle finalization for created measurement records."""

from __future__ import annotations

import copy
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
from scopecat.measurement_records._storage import (
    path_under as _path_under_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.creation import (
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRun,
    read_created_record_primary_table,
)

FINALIZATION_SCHEMA = "scopecat.measurement_record_finalization.v0"
FINALIZATION_RECEIPT_SCHEMA = "measurement_record_finalization_receipt_v0"
FINALIZATION_STATES = {"complete", "failed"}
APPROVAL_STATES = {"approved", "rejected", "needs_review"}


@dataclass(frozen=True)
class MeasurementRecordFinalizationRequest:
    """Approved request to write a record-local finalization receipt."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    finalization_receipt_path: str
    final_state: str
    operator_reason: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "finalization request request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("finalization request approval_state is unsupported")
        validate_public_identifier(self.record_id, "finalization request record_id")
        validate_relative_path(self.record_dir, "finalization request record_dir")
        validate_relative_path(
            self.writer_receipt_path,
            "finalization request writer_receipt_path",
        )
        validate_relative_path(
            self.finalization_receipt_path,
            "finalization request finalization_receipt_path",
        )
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "finalization request writer_receipt_path",
        )
        _validate_strict_child_path(
            self.finalization_receipt_path,
            self.record_dir,
            "finalization request finalization_receipt_path",
        )
        if self.final_state not in FINALIZATION_STATES:
            raise ValueError("finalization request final_state is unsupported")
        if self.final_state == "failed":
            _validate_operator_reason(self.operator_reason, "finalization request operator_reason")
        elif self.operator_reason is not None:
            validate_text(self.operator_reason, "finalization request operator_reason")
        if self.writer_receipt_path == self.finalization_receipt_path:
            raise ValueError("finalization request receipt paths must differ")

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
            "writer_receipt_path": self.writer_receipt_path,
            "finalization_receipt_path": self.finalization_receipt_path,
            "final_state": self.final_state,
        }
        if self.operator_reason is not None:
            request["operator_reason"] = self.operator_reason
        return request


@dataclass(frozen=True)
class MeasurementRecordFinalizationRun:
    """Local receipt for lifecycle finalization."""

    request: MeasurementRecordFinalizationRequest
    read_view: MeasurementRecordReadRun
    storage_root: Path
    finalization_receipt_path: str
    finalization_error: str | None = None

    @property
    def finalized(self) -> bool:
        return self.classification in {"finalized_complete", "finalized_failed"}

    @property
    def classification(self) -> str:
        if self.finalization_error is not None:
            return "blocked_before_finalization"
        if not self.request.approved:
            return "blocked_before_finalization"
        return f"finalized_{self.request.final_state}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_finalization_receipt",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "read_view": {
                "classification": self.read_view.classification,
                "review_findings": [
                    copy.deepcopy(finding) for finding in self.read_view.review_findings
                ],
            },
            "finalization": {
                "performed": self.finalized,
                "final_state": self.request.final_state if self.finalized else None,
                "finalization_error": self.finalization_error,
                "storage_root": str(self.storage_root),
                "finalization_receipt_path": self.finalization_receipt_path,
            },
        }


def finalize_measurement_record(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordFinalizationRun:
    """Finalize a measurement record from a raw finalization source."""

    request, read_view_source = _parse_source(source)
    read_view = read_created_record_primary_table(read_view_source, storage_root=storage_root)
    return finalize_measurement_record_from_read_view(
        request,
        read_view=read_view,
        storage_root=storage_root,
    )


def finalize_measurement_record_from_read_view(
    request: MeasurementRecordFinalizationRequest,
    *,
    read_view: MeasurementRecordReadRun,
    storage_root: str | Path,
    receipt_writer: Callable[[Path, dict[str, Any]], None] | None = None,
) -> MeasurementRecordFinalizationRun:
    """Finalize a measurement record from an already computed read view."""

    root = _existing_directory_root(Path(storage_root), "finalization storage root")
    _validate_request_against_read_view(request, read_view)
    if not request.approved:
        return MeasurementRecordFinalizationRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            finalization_receipt_path=request.finalization_receipt_path,
        )

    block_reason = _finalization_block_reason(request, read_view)
    if block_reason is not None:
        return MeasurementRecordFinalizationRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            finalization_receipt_path=request.finalization_receipt_path,
            finalization_error=block_reason,
        )

    receipt = _finalization_receipt(request, read_view)
    writer = receipt_writer or _write_json_new_file
    try:
        _write_finalization_receipt(root, request.finalization_receipt_path, receipt, writer)
    except _FinalizationWriteFailure as exc:
        return MeasurementRecordFinalizationRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            finalization_receipt_path=request.finalization_receipt_path,
            finalization_error=str(exc),
        )

    return MeasurementRecordFinalizationRun(
        request=request,
        read_view=read_view,
        storage_root=root,
        finalization_receipt_path=request.finalization_receipt_path,
    )


def _parse_source(
    source: dict[str, Any],
) -> tuple[MeasurementRecordFinalizationRequest, dict[str, Any]]:
    if source.get("finalization_schema") != FINALIZATION_SCHEMA:
        raise ValueError(f"finalization source schema must be {FINALIZATION_SCHEMA}")
    request = _require_dict(source, "finalization_request")
    read_view_source = _require_dict(source, "read_view_source")
    return (
        MeasurementRecordFinalizationRequest(
            request_id=_require_text(request, "request_id"),
            approval_state=_require_text(request, "approval_state"),
            record_id=_require_text(request, "record_id"),
            record_dir=_require_text(request, "record_dir"),
            writer_receipt_path=_require_text(request, "writer_receipt_path"),
            finalization_receipt_path=_require_text(
                request,
                "finalization_receipt_path",
            ),
            final_state=_require_text(request, "final_state"),
            operator_reason=_optional_text(request, "operator_reason"),
        ),
        read_view_source,
    )


def _validate_request_against_read_view(
    request: MeasurementRecordFinalizationRequest,
    read_view: MeasurementRecordReadRun,
) -> None:
    if read_view.storage_root != _existing_directory_root(
        Path(read_view.storage_root),
        "finalization read view storage root",
    ):
        raise ValueError("finalization read view storage root is invalid")
    if request.record_id != read_view.request.record_id:
        raise ValueError("finalization record_id must match read view")
    if request.record_dir != read_view.request.record_dir:
        raise ValueError("finalization record_dir must match read view")
    if request.creation_manifest_path != read_view.request.creation_manifest_path:
        raise ValueError("finalization creation_manifest_path must match read view")
    if request.writer_receipt_path != read_view.request.writer_receipt_path:
        raise ValueError("finalization writer_receipt_path must match read view")
    writer_ref = read_view.to_dict()["writer_receipt"]
    table = read_view.table
    if writer_ref["primary_data_path"] != table["source"]:
        raise ValueError("finalization primary data path must match read view")
    if writer_ref["rows_recorded"] != table["declared_row_count"]:
        raise ValueError("finalization row count must match read view")


def _finalization_block_reason(
    request: MeasurementRecordFinalizationRequest,
    read_view: MeasurementRecordReadRun,
) -> str | None:
    if request.final_state == "complete" and read_view.classification != "primary_table_ready":
        return "complete finalization requires a ready read view"
    return None


def _finalization_receipt(
    request: MeasurementRecordFinalizationRequest,
    read_view: MeasurementRecordReadRun,
) -> dict[str, Any]:
    read_summary = read_view.to_dict()
    receipt = {
        "schema": FINALIZATION_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "writer_receipt_path": request.writer_receipt_path,
        },
        "finalization": {
            "request_id": request.request_id,
            "final_state": request.final_state,
            "operator_reason": request.operator_reason,
            "evidence": {
                "read_view_classification": read_view.classification,
                "primary_data_path": read_summary["writer_receipt"]["primary_data_path"],
                "primary_data_digest": read_summary["writer_receipt"]["primary_data_digest"],
                "rows_recorded": read_summary["writer_receipt"]["rows_recorded"],
                "table_row_count": read_view.table["row_count"],
            },
        },
    }
    return receipt


def _write_finalization_receipt(
    root: Path,
    relative_path: str,
    receipt: dict[str, Any],
    receipt_writer: Callable[[Path, dict[str, Any]], None],
) -> None:
    path = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "finalization receipt")
    if path.exists() or path.is_symlink():
        raise _FinalizationWriteFailure("finalization receipt target already exists")
    try:
        receipt_writer(path, receipt)
    except Exception as exc:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise _FinalizationWriteFailure(f"finalization receipt write failed: {exc}") from exc


def _write_json_new_file(path: Path, content: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, sort_keys=True)
        handle.write("\n")


class _FinalizationWriteFailure(RuntimeError):
    pass


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "finalization path")


def _validate_operator_reason(value: str | None, owner: str) -> str:
    if value is None or not isinstance(value, str) or value.strip() == "" or "\n" in value:
        raise ValueError(f"{owner} is required as a single line")
    return value


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(value: dict[str, Any], field: str) -> str | None:
    if field not in value:
        return None
    return validate_text(value[field], field)
