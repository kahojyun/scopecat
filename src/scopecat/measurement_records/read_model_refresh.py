"""Refresh a derived measurement-record read model by atomic replacement."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    validate_public_identifier,
    validate_relative_path,
    validate_sha256_digest,
)
from scopecat.measurement_records.read_model_shared import (
    _ensure_no_symlink_parents,
    _existing_directory_root,
    _finalization_ref,
    _json_bytes,
    _path_under,
    _read_json_at,
    _read_model,
    _sha256,
    _validate_canonical_read_model_path,
    _validate_finalization_receipt,
    _validate_non_overlapping_paths,
    _validate_request_against_read_view,
    _validate_strict_child_path,
)
from scopecat.measurement_records.read_view import MeasurementRecordReadRun

APPROVAL_STATES = {"approved", "rejected", "needs_review"}
TARGET_CONDITIONS = {"missing", "replace_existing"}


@dataclass(frozen=True)
class MeasurementRecordReadModelRefreshRequest:
    """Approved request to refresh a derived record-local read model."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    writer_receipt_path: str
    finalization_receipt_path: str
    read_model_path: str
    expected_target_condition: str
    expected_current_read_model_digest: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "read model refresh request request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("read model refresh request approval_state is unsupported")
        validate_public_identifier(self.record_id, "read model refresh request record_id")
        validate_relative_path(self.record_dir, "read model refresh request record_dir")
        validate_relative_path(
            self.writer_receipt_path,
            "read model refresh request writer_receipt_path",
        )
        validate_relative_path(
            self.finalization_receipt_path,
            "read model refresh request finalization_receipt_path",
        )
        validate_relative_path(self.read_model_path, "read model refresh request read_model_path")
        _validate_strict_child_path(
            self.writer_receipt_path,
            self.record_dir,
            "read model refresh request writer_receipt_path",
        )
        _validate_strict_child_path(
            self.finalization_receipt_path,
            self.record_dir,
            "read model refresh request finalization_receipt_path",
        )
        _validate_strict_child_path(
            self.read_model_path,
            self.record_dir,
            "read model refresh request read_model_path",
        )
        _validate_canonical_read_model_path(
            self.read_model_path,
            self.record_dir,
            "read model refresh request read_model_path",
        )
        if self.expected_target_condition not in TARGET_CONDITIONS:
            raise ValueError("read model refresh request expected_target_condition is unsupported")
        if self.expected_target_condition == "replace_existing":
            validate_sha256_digest(
                self.expected_current_read_model_digest,
                "read model refresh request expected_current_read_model_digest",
            )
        elif self.expected_current_read_model_digest is not None:
            raise ValueError(
                "read model refresh request expected_current_read_model_digest "
                "requires replace_existing"
            )
        _validate_non_overlapping_paths(
            (
                self.creation_manifest_path,
                self.writer_receipt_path,
                self.finalization_receipt_path,
                self.read_model_path,
                self.temp_read_model_path,
            ),
            "read model refresh request paths",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

    @property
    def temp_read_model_path(self) -> str:
        return f"{self.record_dir}/record-read-model.refresh-{self.request_id}.tmp"


@dataclass(frozen=True)
class MeasurementRecordReadModelRefreshRun:
    """Local receipt for read-model refresh."""

    request: MeasurementRecordReadModelRefreshRequest
    read_view: MeasurementRecordReadRun
    storage_root: Path
    finalization_receipt: dict[str, Any] | None = None
    previous_read_model_digest: str | None = None
    refreshed_read_model_digest: str | None = None
    refreshed_read_model_size_bytes: int | None = None
    replacement_performed: bool = False
    cleanup_performed: bool = False
    refresh_error: str | None = None

    @property
    def refreshed(self) -> bool:
        return self.classification == "refreshed_read_model"

    @property
    def classification(self) -> str:
        if self.refresh_error is not None:
            if self.replacement_performed:
                return "refresh_replaced_with_error"
            return "blocked_before_refresh"
        if not self.request.approved:
            return "blocked_before_refresh"
        return "refreshed_read_model"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_read_model_refresh_receipt",
            "classification": self.classification,
            "request": _request_ref(self.request),
            "read_view": {
                "classification": self.read_view.classification,
                "review_findings": [
                    copy.deepcopy(finding) for finding in self.read_view.review_findings
                ],
            },
            "finalization_receipt": _finalization_ref(self.finalization_receipt),
            "refresh": {
                "performed": self.refreshed,
                "replacement_performed": self.replacement_performed,
                "cleanup_performed": self.cleanup_performed,
                "refresh_error": self.refresh_error,
                "storage_root": str(self.storage_root),
                "read_model_path": self.request.read_model_path,
                "temp_read_model_path": self.request.temp_read_model_path,
                "previous_read_model_digest": self.previous_read_model_digest,
                "refreshed_read_model_digest": self.refreshed_read_model_digest,
                "refreshed_read_model_size_bytes": self.refreshed_read_model_size_bytes,
            },
        }


def refresh_measurement_record_read_model_from_read_view(
    request: MeasurementRecordReadModelRefreshRequest,
    *,
    read_view: MeasurementRecordReadRun,
    storage_root: str | Path,
    model_writer: Callable[[Path, bytes], None] | None = None,
    model_replacer: Callable[[Path, Path], None] | None = None,
) -> MeasurementRecordReadModelRefreshRun:
    """Refresh a record read model from an already computed read view."""

    root = _existing_directory_root(Path(storage_root), "read model refresh storage root")
    _validate_request_against_read_view(request, read_view)
    if not request.approved:
        return MeasurementRecordReadModelRefreshRun(
            request=request,
            read_view=read_view,
            storage_root=root,
        )

    previous_digest = None
    finalization_receipt = None
    try:
        previous_digest = _validate_target_condition(root, request)
        model_content, finalization_receipt = _build_refresh_content(
            root,
            request,
            read_view,
        )
        writer = model_writer or _write_new_file
        replacer = model_replacer or _replace_file
        _write_temp_then_replace(
            root,
            request,
            model_content,
            writer,
            replacer,
        )
    except _RefreshFailure as exc:
        return MeasurementRecordReadModelRefreshRun(
            request=request,
            read_view=read_view,
            storage_root=root,
            finalization_receipt=exc.finalization_receipt or finalization_receipt,
            previous_read_model_digest=exc.previous_read_model_digest or previous_digest,
            replacement_performed=exc.replacement_performed,
            cleanup_performed=exc.cleanup_performed,
            refresh_error=str(exc),
        )

    return MeasurementRecordReadModelRefreshRun(
        request=request,
        read_view=read_view,
        storage_root=root,
        finalization_receipt=finalization_receipt,
        previous_read_model_digest=previous_digest,
        refreshed_read_model_digest=_sha256(model_content),
        refreshed_read_model_size_bytes=len(model_content),
        replacement_performed=True,
    )


def _request_ref(request: MeasurementRecordReadModelRefreshRequest) -> dict[str, Any]:
    result = {
        "request_id": request.request_id,
        "approval_state": request.approval_state,
        "record_id": request.record_id,
        "record_dir": request.record_dir,
        "creation_manifest_path": request.creation_manifest_path,
        "writer_receipt_path": request.writer_receipt_path,
        "finalization_receipt_path": request.finalization_receipt_path,
        "read_model_path": request.read_model_path,
        "temp_read_model_path": request.temp_read_model_path,
        "expected_target_condition": request.expected_target_condition,
    }
    if request.expected_current_read_model_digest is not None:
        result["expected_current_read_model_digest"] = request.expected_current_read_model_digest
    return result


def _validate_target_condition(
    root: Path,
    request: MeasurementRecordReadModelRefreshRequest,
) -> str | None:
    target = _path_under(root, request.read_model_path)
    _ensure_no_symlink_parents(root, request.read_model_path, "read model refresh target")
    if target.is_symlink():
        raise _RefreshFailure("read model refresh target must not be a symlink")
    if request.expected_target_condition == "missing":
        if target.exists():
            raise _RefreshFailure("read model refresh target already exists")
        return None
    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise _RefreshFailure("read model refresh target is missing") from exc
    digest = _sha256(content)
    if digest != request.expected_current_read_model_digest:
        raise _RefreshFailure("read model refresh target digest does not match")
    return digest


def _build_refresh_content(
    root: Path,
    request: MeasurementRecordReadModelRefreshRequest,
    read_view: MeasurementRecordReadRun,
) -> tuple[bytes, dict[str, Any]]:
    manifest, manifest_digest = _read_json_at(
        root,
        request.creation_manifest_path,
        "read model refresh creation manifest",
    )
    if manifest != read_view.record_manifest:
        raise ValueError("read model refresh creation manifest must match read view")
    writer_receipt, writer_digest = _read_json_at(
        root,
        request.writer_receipt_path,
        "read model refresh writer receipt",
    )
    if writer_receipt != read_view.writer_receipt:
        raise ValueError("read model refresh writer receipt must match read view")
    finalization_receipt, finalization_digest = _read_json_at(
        root,
        request.finalization_receipt_path,
        "read model refresh finalization receipt",
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
    model["refresh"] = {
        "request_id": request.request_id,
        "expected_target_condition": request.expected_target_condition,
        "previous_read_model_authority": "overwrite_guard_only",
    }
    return _json_bytes(model), finalization_receipt


def _write_temp_then_replace(
    root: Path,
    request: MeasurementRecordReadModelRefreshRequest,
    content: bytes,
    model_writer: Callable[[Path, bytes], None],
    model_replacer: Callable[[Path, Path], None],
) -> None:
    temp = _path_under(root, request.temp_read_model_path)
    target = _path_under(root, request.read_model_path)
    _ensure_no_symlink_parents(root, request.temp_read_model_path, "read model refresh temp")
    if temp.exists() or temp.is_symlink():
        raise _RefreshFailure("read model refresh temp target already exists")
    cleanup_performed = False
    try:
        model_writer(temp, content)
    except Exception as exc:
        cleanup_performed = _cleanup_temp(temp)
        raise _RefreshFailure(
            f"read model refresh write failed: {exc}",
            cleanup_performed=cleanup_performed,
        ) from exc
    try:
        model_replacer(temp, target)
    except Exception as exc:
        replacement_performed = _target_contains_content(target, content)
        cleanup_performed = _cleanup_temp(temp)
        raise _RefreshFailure(
            f"read model refresh replace failed: {exc}",
            replacement_performed=replacement_performed,
            cleanup_performed=cleanup_performed,
        ) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _replace_file(temp: Path, target: Path) -> None:
    temp.replace(target)


def _cleanup_temp(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _target_contains_content(path: Path, content: bytes) -> bool:
    try:
        return path.read_bytes() == content
    except OSError:
        return False


class _RefreshFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        finalization_receipt: dict[str, Any] | None = None,
        previous_read_model_digest: str | None = None,
        replacement_performed: bool = False,
        cleanup_performed: bool = False,
    ) -> None:
        super().__init__(message)
        self.finalization_receipt = finalization_receipt
        self.previous_read_model_digest = previous_read_model_digest
        self.replacement_performed = replacement_performed
        self.cleanup_performed = cleanup_performed


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError(f"{field} must be text")
    return item


def _optional_text(value: dict[str, Any], field: str) -> str | None:
    if field not in value:
        return None
    return _require_text(value, field)
