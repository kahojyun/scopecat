"""Record declared legacy-run information in Measurement Records storage."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
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
from scopecat.measurement_records._storage import (
    sha256 as _sha256,
)
from scopecat.measurement_records._storage import (
    validate_non_overlapping_paths as _validate_non_overlapping_paths_common,
)
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)

LEGACY_RUN_RECEIPT_SCHEMA = "measurement_record_legacy_run_receipt_v0"
LEGACY_RUN_RECEIPT_NAME = "legacy-run-receipt.json"
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
LOCATOR_KINDS = {"workspace_relative_path", "opaque_reference"}
LOCATOR_ROLES = {"primary_data", "notebook"}


@dataclass(frozen=True)
class LegacyRunLocator:
    """Declared legacy locator kept as a reference, not imported payload."""

    locator_id: str
    kind: str
    role: str
    value: str

    def __post_init__(self) -> None:
        validate_public_identifier(self.locator_id, "legacy locator locator_id")
        if self.kind not in LOCATOR_KINDS:
            raise ValueError("legacy locator kind is unsupported")
        if self.role not in LOCATOR_ROLES:
            raise ValueError("legacy locator role is unsupported")
        if self.kind == "workspace_relative_path":
            validate_relative_path(self.value, "legacy locator value")
        else:
            validate_text(self.value, "legacy locator value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
        }


@dataclass(frozen=True)
class LegacyRunRecordRequest:
    """Approved request to record legacy-run facts in local storage."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    legacy_system_id: str
    legacy_run_id: str
    legacy_receipt_path: str | None = None
    created_at: str | None = None
    label: str | None = None
    experiment_type: str | None = None
    run_started_at: str | None = None
    run_completed_at: str | None = None
    locators: tuple[LegacyRunLocator, ...] = ()
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "legacy run request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("legacy run approval_state is unsupported")
        validate_public_identifier(self.record_id, "legacy run record_id")
        validate_relative_path(self.record_dir, "legacy run record_dir")
        validate_public_identifier(self.legacy_system_id, "legacy system id")
        validate_public_identifier(self.legacy_run_id, "legacy run id")
        validate_relative_path(self.receipt_path, "legacy run receipt_path")
        _validate_strict_child_path(
            self.receipt_path,
            self.record_dir,
            "legacy run receipt_path",
        )
        _validate_non_overlapping_paths(
            (self.creation_manifest_path, self.receipt_path),
            "legacy run output paths",
        )
        for value, owner in (
            (self.created_at, "legacy run created_at"),
            (self.label, "legacy run label"),
            (self.experiment_type, "legacy run experiment_type"),
            (self.run_started_at, "legacy run run_started_at"),
            (self.run_completed_at, "legacy run run_completed_at"),
            (self.operator_notes, "legacy run operator_notes"),
        ):
            if value is not None:
                validate_text(value, owner)
        if not isinstance(self.locators, tuple):
            raise ValueError("legacy run locators must be a tuple")
        if len({locator.locator_id for locator in self.locators}) != len(self.locators):
            raise ValueError("legacy run locators must have unique locator_id values")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    @property
    def receipt_path(self) -> str:
        return self.legacy_receipt_path or f"{self.record_dir}/{LEGACY_RUN_RECEIPT_NAME}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "legacy_receipt_path": self.receipt_path,
            "legacy_system_id": self.legacy_system_id,
            "legacy_run_id": self.legacy_run_id,
            "created_at": self.created_at,
            "label": self.label,
            "experiment_type": self.experiment_type,
            "run_started_at": self.run_started_at,
            "run_completed_at": self.run_completed_at,
            "locators": [locator.to_dict() for locator in self.locators],
            "operator_notes": self.operator_notes,
        }


@dataclass(frozen=True)
class LegacyRunRecordRun:
    """Local receipt for a legacy-run storage mutation."""

    request: LegacyRunRecordRequest
    storage_root: Path
    created_paths: tuple[str, ...] = ()
    legacy_receipt_digest: str | None = None
    legacy_receipt_size_bytes: int | None = None
    rollback_performed: bool = False
    record_error: str | None = None

    @property
    def recorded(self) -> bool:
        return self.classification == "recorded_legacy_run"

    @property
    def classification(self) -> str:
        if self.record_error is not None:
            if self.rollback_performed:
                return "rolled_back_after_legacy_receipt_failure"
            return "blocked_before_legacy_run_record"
        if not self.request.approved:
            return "blocked_before_legacy_run_record"
        return "recorded_legacy_run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "request": self.request.to_dict(),
            "creation": {
                "performed": bool(self.created_paths),
                "record_id": self.request.record_id,
                "record_dir": self.request.record_dir,
                "manifest_path": self.request.creation_manifest_path,
                "created_paths": list(self.created_paths),
            },
            "legacy_receipt": {
                "performed": self.recorded,
                "path": self.request.receipt_path,
                "digest": self.legacy_receipt_digest,
                "size_bytes": self.legacy_receipt_size_bytes,
                "rollback_performed": self.rollback_performed,
                "record_error": self.record_error,
            },
        }


def record_legacy_measurement_run_from_request(
    request: LegacyRunRecordRequest,
    *,
    storage_root: str | Path,
    receipt_writer: Callable[[Path, bytes], None] | None = None,
) -> LegacyRunRecordRun:
    """Create a record shell and write one record-local legacy receipt."""

    root = _existing_directory_root(Path(storage_root), "legacy run storage root")
    if not request.approved:
        return LegacyRunRecordRun(request=request, storage_root=root)

    try:
        created_paths = _write_record_shell(root, request)
    except _LegacyRecordShellFailure as exc:
        return LegacyRunRecordRun(
            request=request,
            storage_root=root,
            rollback_performed=exc.rollback_performed,
            record_error=str(exc),
        )

    content = _json_bytes(_legacy_receipt(request))
    writer = receipt_writer or _write_new_file
    try:
        _write_legacy_receipt(root, request.receipt_path, content, writer)
    except _LegacyReceiptWriteFailure as exc:
        rollback_performed = _remove_record_dir(root, request.record_dir)
        return LegacyRunRecordRun(
            request=request,
            storage_root=root,
            created_paths=tuple(created_paths),
            rollback_performed=rollback_performed,
            record_error=str(exc),
        )

    return LegacyRunRecordRun(
        request=request,
        storage_root=root,
        created_paths=tuple(created_paths),
        legacy_receipt_digest=_sha256(content),
        legacy_receipt_size_bytes=len(content),
    )


def _write_record_shell(root: Path, request: LegacyRunRecordRequest) -> list[str]:
    if os.path.lexists(_path_under(root, request.record_dir)):
        raise _LegacyRecordShellFailure(
            "legacy run record_dir target already exists",
            rollback_performed=False,
        )
    _ensure_no_symlink_parents(root, request.record_dir, "legacy run record_dir")

    created_dirs: list[str] = []
    created_manifest = False
    try:
        created_dirs = _create_directory_chain(root, request.record_dir)
        manifest_path = _path_under(root, request.creation_manifest_path)
        _write_new_file(manifest_path, _json_bytes(_record_manifest(request)))
        created_manifest = True
    except Exception as exc:
        if created_manifest:
            try:
                _path_under(root, request.creation_manifest_path).unlink()
            except FileNotFoundError:
                pass
        _remove_created_dirs(root, created_dirs)
        if isinstance(exc, _LegacyRecordShellFailure):
            raise exc
        raise _LegacyRecordShellFailure(
            f"legacy run record shell write failed: {exc}",
            rollback_performed=bool(created_dirs) or created_manifest,
        ) from exc
    return [*created_dirs, request.creation_manifest_path]


def _record_manifest(request: LegacyRunRecordRequest) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": request.record_id,
        "lifecycle_state": "created",
    }
    if request.created_at is not None:
        record["created_at"] = request.created_at
    if request.label is not None:
        record["label"] = request.label
    if request.experiment_type is not None:
        record["experiment_type"] = request.experiment_type
    return {
        "schema": MANIFEST_SCHEMA,
        "record": record,
        "creation": {
            "request_id": request.request_id,
            "source_kind": "legacy_system",
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


def _legacy_receipt(request: LegacyRunRecordRequest) -> dict[str, Any]:
    return {
        "schema": LEGACY_RUN_RECEIPT_SCHEMA,
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "legacy_receipt_path": request.receipt_path,
        },
        "legacy_run": {
            "legacy_system_id": request.legacy_system_id,
            "legacy_run_id": request.legacy_run_id,
            "run_started_at": request.run_started_at,
            "run_completed_at": request.run_completed_at,
            "operator_notes": request.operator_notes,
        },
        "declared_locators": [locator.to_dict() for locator in request.locators],
        "operation": {
            "request_id": request.request_id,
            "classification": "legacy_run_recorded_for_review",
        },
    }


def _write_legacy_receipt(
    root: Path,
    relative_path: str,
    content: bytes,
    writer: Callable[[Path, bytes], None],
) -> None:
    path = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "legacy run receipt target")
    if path.exists() or path.is_symlink():
        raise _LegacyReceiptWriteFailure("legacy run receipt target already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        writer(path, content)
    except OSError as exc:
        raise _LegacyReceiptWriteFailure(str(exc)) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _create_directory_chain(root: Path, relative_dir: str) -> list[str]:
    current = root
    created_dirs: list[str] = []
    current_parts: list[str] = []
    try:
        for part in Path(validate_relative_path(relative_dir, "legacy run record_dir")).parts:
            current_parts.append(part)
            current = current / part
            if current.is_symlink():
                raise ValueError("legacy run record_dir parent is a symlink")
            if current.exists():
                if not current.is_dir():
                    raise ValueError("legacy run record_dir parent is not a directory")
                continue
            current.mkdir()
            created_dirs.append("/".join(current_parts))
    except Exception:
        _remove_created_dirs(root, created_dirs)
        raise
    return created_dirs


def _remove_created_dirs(root: Path, created_dirs: list[str]) -> None:
    for relative_path in reversed(created_dirs):
        try:
            _path_under(root, relative_path).rmdir()
        except OSError:
            pass


def _remove_record_dir(root: Path, record_dir: str) -> bool:
    target = _path_under(root, record_dir)
    if target.exists() and target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
        return True
    return False


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "legacy run path")


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"legacy run {key} must be an object")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    validate_text(value, f"legacy run {key}")
    return value


def _optional_text(source: dict[str, Any], key: str, *, default: str | None) -> str | None:
    value = source.get(key, default)
    if value is None:
        return None
    validate_text(value, f"legacy run {key}")
    return value


class _LegacyReceiptWriteFailure(RuntimeError):
    """Receipt write failed after record shell creation."""


class _LegacyRecordShellFailure(RuntimeError):
    def __init__(self, message: str, *, rollback_performed: bool) -> None:
        super().__init__(message)
        self.rollback_performed = rollback_performed
