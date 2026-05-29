"""Project a finalized measurement record into a local read model."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records.creation import (
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.finalization import FINALIZATION_RECEIPT_SCHEMA
from scopecat.measurement_records.read_view import (
    MeasurementRecordReadRun,
    read_created_record_primary_table,
)

READ_MODEL_PROJECTION_SCHEMA = "scopecat.measurement_record_read_model_projection.v0"
READ_MODEL_SCHEMA = "measurement_record_read_model_candidate_v0"
READ_MODEL_PROJECTION_POLICY = {
    "workflow_authority": "approved_measurement_record_read_model_projection_request",
    "record_authority": "existing_measurement_record_creation_manifest",
    "writer_receipt_authority": "record_local_writer_receipt",
    "read_view_authority": "local_record_read_view",
    "finalization_authority": "record_local_finalization_receipt",
    "read_model_materialization": "write_record_local_read_model",
    "record_manifest": "not_replaced",
    "read_model_refresh": "not_performed",
    "collision_policy": "no_overwrite",
    "storage_root_concurrency": "not_supported",
    "final_storage_schema": "not_defined",
}
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
DOES_NOT_CLAIM = [
    "manifest_replacement",
    "canonical_storage_authority",
    "read_model_refresh",
    "stale_read_model_repair",
    "final_storage_schema",
    "conflict_resolution",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "export_schema",
    "gui_review_state",
]


@dataclass(frozen=True)
class MeasurementRecordReadModelProjectionRequest:
    """Approved request to write a record-local derived read model."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "read model projection request request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("read model projection request approval_state is unsupported")
        validate_public_identifier(self.record_id, "read model projection request record_id")
        validate_relative_path(self.record_dir, "read model projection request record_dir")
        validate_relative_path(
            self.writer_receipt_path,
            "read model projection request writer_receipt_path",
        )
        validate_relative_path(
            self.finalization_receipt_path,
            "read model projection request finalization_receipt_path",
        )
        validate_relative_path(
            self.read_model_path, "read model projection request read_model_path"
        )
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "read model projection request writer_receipt_path",
        )
        _validate_strict_child_path(
            self.finalization_receipt_path,
            self.record_dir,
            "read model projection request finalization_receipt_path",
        )
        _validate_strict_child_path(
            self.read_model_path,
            self.record_dir,
            "read model projection request read_model_path",
        )
        _validate_non_overlapping_paths(
            (
                self.creation_manifest_path,
                self.writer_receipt_path,
                self.finalization_receipt_path,
                self.read_model_path,
            ),
            "read model projection request paths",
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
            "writer_receipt_path": self.writer_receipt_path,
            "finalization_receipt_path": self.finalization_receipt_path,
            "read_model_path": self.read_model_path,
        }


@dataclass(frozen=True)
class MeasurementRecordReadModelProjectionRun:
    """Local receipt for read-model projection."""

    request: MeasurementRecordReadModelProjectionRequest
    read_view: MeasurementRecordReadRun
    storage_root: Path
    read_model_path: str
    finalization_receipt: dict[str, Any] | None = None
    read_model_digest: str | None = None
    read_model_size_bytes: int | None = None
    projection_error: str | None = None

    @property
    def projected(self) -> bool:
        return self.classification == "projected_read_model"

    @property
    def classification(self) -> str:
        if self.projection_error is not None:
            return "blocked_before_projection"
        if not self.request.approved:
            return "blocked_before_projection"
        return "projected_read_model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_read_model_projection_receipt",
            "read_model_projection_policy": copy.deepcopy(READ_MODEL_PROJECTION_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "read_created_record_primary_table",
                    "validate_projection_request",
                    *([] if not self.request.approved else ["read_finalization_receipt"]),
                    *([] if not self.projected else ["write_read_model"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "read_view": {
                "classification": self.read_view.classification,
                "review_findings": [
                    copy.deepcopy(finding) for finding in self.read_view.review_findings
                ],
            },
            "finalization_receipt": _finalization_ref(self.finalization_receipt),
            "projection": {
                "performed": self.projected,
                "projection_error": self.projection_error,
                "storage_root": str(self.storage_root),
                "read_model_path": self.read_model_path,
                "read_model_digest": self.read_model_digest,
                "read_model_size_bytes": self.read_model_size_bytes,
            },
        }


def project_measurement_record_read_model(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordReadModelProjectionRun:
    """Project a finalized record read model from a raw projection source."""

    request, read_view_source = _parse_source(source)
    read_view = read_created_record_primary_table(read_view_source, storage_root=storage_root)
    return project_measurement_record_read_model_from_read_view(
        request,
        read_view=read_view,
        storage_root=storage_root,
    )


def project_measurement_record_read_model_from_read_view(
    request: MeasurementRecordReadModelProjectionRequest,
    *,
    read_view: MeasurementRecordReadRun,
    storage_root: str | Path,
    model_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordReadModelProjectionRun:
    """Project a finalized record read model from an already computed read view."""

    root = _existing_directory_root(Path(storage_root), "read model projection storage root")
    _validate_request_against_read_view(request, read_view)
    if not request.approved:
        return MeasurementRecordReadModelProjectionRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            read_model_path=request.read_model_path,
        )

    manifest, manifest_digest = _read_json_at(
        root,
        request.creation_manifest_path,
        "read model projection creation manifest",
    )
    if manifest != read_view.record_manifest:
        raise ValueError("read model projection creation manifest must match read view")
    writer_receipt, writer_digest = _read_json_at(
        root,
        request.writer_receipt_path,
        "read model projection writer receipt",
    )
    if writer_receipt != read_view.writer_receipt:
        raise ValueError("read model projection writer receipt must match read view")
    finalization_receipt, finalization_digest = _read_json_at(
        root,
        request.finalization_receipt_path,
        "read model projection finalization receipt",
    )
    _validate_finalization_receipt(request, read_view, finalization_receipt)

    model = _read_model(
        request,
        read_view,
        manifest_digest=manifest_digest,
        writer_receipt_digest=writer_digest,
        finalization_receipt=finalization_receipt,
        finalization_receipt_digest=finalization_digest,
    )
    model_content = _json_bytes(model)
    writer = model_writer or _write_new_file
    try:
        _write_read_model(root, request.read_model_path, model_content, writer)
    except _ProjectionWriteFailure as exc:
        return MeasurementRecordReadModelProjectionRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            read_model_path=request.read_model_path,
            finalization_receipt=finalization_receipt,
            projection_error=str(exc),
        )

    return MeasurementRecordReadModelProjectionRun(
        request=request,
        read_view=read_view,
        storage_root=root,
        read_model_path=request.read_model_path,
        finalization_receipt=finalization_receipt,
        read_model_digest=_sha256(model_content),
        read_model_size_bytes=len(model_content),
    )


def _parse_source(
    source: dict[str, Any],
) -> tuple[MeasurementRecordReadModelProjectionRequest, dict[str, Any]]:
    if source.get("read_model_projection_schema") != READ_MODEL_PROJECTION_SCHEMA:
        raise ValueError(
            f"read model projection source schema must be {READ_MODEL_PROJECTION_SCHEMA}"
        )
    if source.get("read_model_projection_policy") != READ_MODEL_PROJECTION_POLICY:
        raise ValueError("read model projection source policy is unsupported")
    request = _require_dict(source, "projection_request")
    read_view_source = _require_dict(source, "read_view_source")
    return (
        MeasurementRecordReadModelProjectionRequest(
            request_id=_require_text(request, "request_id"),
            approval_state=_require_text(request, "approval_state"),
            record_id=_require_text(request, "record_id"),
            record_dir=_require_text(request, "record_dir"),
            writer_receipt_path=_require_text(request, "writer_receipt_path"),
            finalization_receipt_path=_require_text(request, "finalization_receipt_path"),
            read_model_path=_require_text(request, "read_model_path"),
        ),
        read_view_source,
    )


def _validate_request_against_read_view(
    request: MeasurementRecordReadModelProjectionRequest,
    read_view: MeasurementRecordReadRun,
) -> None:
    if read_view.storage_root != _existing_directory_root(
        Path(read_view.storage_root),
        "read model projection read view storage root",
    ):
        raise ValueError("read model projection read view storage root is invalid")
    if request.record_id != read_view.request.record_id:
        raise ValueError("read model projection record_id must match read view")
    if request.record_dir != read_view.request.record_dir:
        raise ValueError("read model projection record_dir must match read view")
    if request.creation_manifest_path != read_view.request.creation_manifest_path:
        raise ValueError("read model projection creation_manifest_path must match read view")
    if request.writer_receipt_path != read_view.request.writer_receipt_path:
        raise ValueError("read model projection writer_receipt_path must match read view")


def _validate_finalization_receipt(
    request: MeasurementRecordReadModelProjectionRequest,
    read_view: MeasurementRecordReadRun,
    receipt: dict[str, Any],
) -> None:
    if receipt.get("schema") != FINALIZATION_RECEIPT_SCHEMA:
        raise ValueError("read model projection finalization receipt schema is unsupported")
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("read model projection record_id must match finalization receipt")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("read model projection record_dir must match finalization receipt")
    if record.get("creation_manifest_path") != request.creation_manifest_path:
        raise ValueError(
            "read model projection creation_manifest_path must match finalization receipt"
        )
    if record.get("writer_receipt_path") != request.writer_receipt_path:
        raise ValueError(
            "read model projection writer_receipt_path must match finalization receipt"
        )
    finalization = _require_dict(receipt, "finalization")
    final_state = finalization.get("final_state")
    if final_state not in {"complete", "failed"}:
        raise ValueError("read model projection finalization state is unsupported")
    evidence = _require_dict(finalization, "evidence")
    writer_ref = read_view.to_dict()["writer_receipt"]
    if evidence.get("read_view_classification") != read_view.classification:
        raise ValueError("read model projection read view classification must match finalization")
    if evidence.get("primary_data_path") != writer_ref["primary_data_path"]:
        raise ValueError("read model projection primary data path must match finalization")
    if evidence.get("primary_data_digest") != writer_ref["primary_data_digest"]:
        raise ValueError("read model projection primary data digest must match finalization")
    if evidence.get("rows_recorded") != writer_ref["rows_recorded"]:
        raise ValueError("read model projection rows recorded must match finalization")
    if evidence.get("table_row_count") != read_view.table["row_count"]:
        raise ValueError("read model projection table row count must match finalization")
    if final_state == "failed":
        validate_text(finalization.get("operator_reason"), "finalization operator_reason")


def _read_model(
    request: MeasurementRecordReadModelProjectionRequest,
    read_view: MeasurementRecordReadRun,
    *,
    manifest_digest: str,
    writer_receipt_digest: str,
    finalization_receipt: dict[str, Any],
    finalization_receipt_digest: str,
) -> dict[str, Any]:
    manifest_ref = read_view.to_dict()["record_manifest"]
    writer_ref = read_view.to_dict()["writer_receipt"]
    finalization = _require_dict(finalization_receipt, "finalization")
    final_state = finalization["final_state"]
    finalization_entry = {
        "final_state": final_state,
        "operator_reason": finalization.get("operator_reason"),
    }
    return {
        "schema": READ_MODEL_SCHEMA,
        "read_model_policy": {
            "authority": "derived_from_record_local_receipts",
            "canonical_storage_authority": "not_claimed",
            "manifest_replacement": "not_performed",
            "refresh": "not_performed",
        },
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "lifecycle_state": final_state,
            "creation_lifecycle_state": manifest_ref["lifecycle_state"],
        },
        "sources": {
            "creation_manifest": {
                "path": request.creation_manifest_path,
                "schema": manifest_ref["schema"],
                "digest": manifest_digest,
            },
            "writer_receipt": {
                "path": request.writer_receipt_path,
                "schema": writer_ref["schema"],
                "digest": writer_receipt_digest,
            },
            "finalization_receipt": {
                "path": request.finalization_receipt_path,
                "schema": finalization_receipt.get("schema"),
                "digest": finalization_receipt_digest,
            },
            "read_view": {
                "classification": read_view.classification,
            },
        },
        "primary_data": {
            "path": writer_ref["primary_data_path"],
            "format": read_view.table["format"],
            "digest": writer_ref["primary_data_digest"],
            "size_bytes": _require_dict(read_view.writer_receipt, "primary_data").get("size_bytes"),
            "declared_row_count": writer_ref["rows_recorded"],
            "observed_row_count": read_view.table["row_count"],
        },
        "table": {
            "classification": read_view.table["classification"],
            "columns": copy.deepcopy(read_view.table["columns"]),
            "preview": copy.deepcopy(read_view.table["preview"]),
        },
        "review": {
            "findings": [copy.deepcopy(finding) for finding in read_view.review_findings],
        },
        "finalization": finalization_entry,
        "projection": {
            "request_id": request.request_id,
            "read_model_path": request.read_model_path,
            "projection_kind": "derived_local_summary",
        },
        "does_not_claim": list(DOES_NOT_CLAIM),
    }


def _read_json_at(root: Path, relative_path: str, label: str) -> tuple[dict[str, Any], str]:
    _ensure_no_symlink_parents(root, relative_path, label)
    path = _path_under(root, relative_path)
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is required") from exc
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be utf-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed, _sha256(content)


def _write_read_model(
    root: Path,
    relative_path: str,
    content: bytes,
    model_writer: Callable[[Path, bytes], None],
) -> None:
    path = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "read model projection target")
    if path.exists() or path.is_symlink():
        raise _ProjectionWriteFailure("read model target already exists")
    try:
        model_writer(path, content)
    except Exception as exc:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise _ProjectionWriteFailure(f"read model write failed: {exc}") from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _json_bytes(content: dict[str, Any]) -> bytes:
    return (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _finalization_ref(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    finalization = _require_dict(receipt, "finalization")
    record = _require_dict(receipt, "record")
    return {
        "schema": receipt.get("schema"),
        "record_id": record.get("record_id"),
        "record_dir": record.get("record_dir"),
        "final_state": finalization.get("final_state"),
    }


class _ProjectionWriteFailure(RuntimeError):
    pass


def _existing_directory_root(root: Path, owner: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    return root.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(
        *Path(validate_relative_path(relative_path, "read model projection path")).parts
    )


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    parts = Path(validate_relative_path(relative_path, label)).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def _validate_strict_child_path(value: str, parent: str, owner: str) -> None:
    value_parts = Path(validate_relative_path(value, owner)).parts
    parent_parts = Path(validate_relative_path(parent, f"{owner} parent")).parts
    if len(value_parts) <= len(parent_parts) or value_parts[: len(parent_parts)] != parent_parts:
        raise ValueError(f"{owner} must stay under record_dir")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    if len(set(paths)) != len(paths):
        raise ValueError(f"{owner} must not overlap")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)
