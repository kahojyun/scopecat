"""Durable measurement-record creation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
    APPROVAL_STATES,
    CREATION_SOURCE_KINDS,
    INITIAL_LIFECYCLE_STATES,
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    relative_path_parts,
    validate_public_identifier,
    validate_public_path_segments,
    validate_relative_path,
    validate_text,
)


@dataclass(frozen=True)
class MeasurementRecordCreationRequest:
    """Request to create the first durable measurement-record shell."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    initial_lifecycle_state: str = "created"
    creation_source_kind: str = "manual"
    created_at: str | None = None
    label: str | None = None
    experiment_type: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "creation request request_id")
        validate_public_identifier(self.record_id, "creation request record_id")
        validate_relative_path(self.record_dir, "creation request record_dir")
        validate_public_path_segments(self.record_dir, "creation request record_dir")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("creation request approval_state is unsupported")
        if self.initial_lifecycle_state not in INITIAL_LIFECYCLE_STATES:
            raise ValueError("creation request initial_lifecycle_state is unsupported")
        if self.creation_source_kind not in CREATION_SOURCE_KINDS:
            raise ValueError("creation request creation_source_kind is unsupported")
        if self.created_at is not None:
            validate_text(self.created_at, "creation request created_at")
        if self.label is not None:
            validate_text(self.label, "creation request label")
        if self.experiment_type is not None:
            validate_text(self.experiment_type, "creation request experiment_type")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    def to_dict(self) -> dict[str, Any]:
        request = {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "manifest_path": self.manifest_path,
            "initial_lifecycle_state": self.initial_lifecycle_state,
            "creation_source_kind": self.creation_source_kind,
        }
        if self.created_at is not None:
            request["created_at"] = self.created_at
        if self.label is not None:
            request["label"] = self.label
        if self.experiment_type is not None:
            request["experiment_type"] = self.experiment_type
        return request


@dataclass(frozen=True)
class MeasurementRecordCreationRun:
    """Local receipt for the first measurement-record creation mutation."""

    request: MeasurementRecordCreationRequest
    storage_root: Path
    created_paths: tuple[str, ...] = ()
    rollback_performed: bool = False
    creation_error: str | None = None

    @property
    def created(self) -> bool:
        return self.classification == "created_record"

    @property
    def classification(self) -> str:
        if self.creation_error is not None:
            if self.rollback_performed:
                return "rolled_back_after_creation_failure"
            return "blocked_before_creation"
        if not self.request.approved:
            return "blocked_before_creation"
        return "created_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_creation_receipt",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "creation": {
                "performed": self.created,
                "rollback_performed": self.rollback_performed,
                "creation_error": self.creation_error,
                "storage_root": str(self.storage_root),
                "record_id": self.request.record_id,
                "record_dir": self.request.record_dir,
                "manifest_path": self.request.manifest_path,
                "created_paths": list(self.created_paths),
            },
        }


def create_measurement_record_from_request(
    request: MeasurementRecordCreationRequest,
    *,
    storage_root: str | Path,
    manifest_writer: Callable[[Path, dict[str, Any]], None] | None = None,
) -> MeasurementRecordCreationRun:
    """Create a measurement-record shell from an already typed request."""

    root = _existing_storage_root(Path(storage_root))
    if not request.approved:
        return MeasurementRecordCreationRun(request=request, storage_root=root)

    manifest = _build_manifest(request)
    writer = manifest_writer or _write_json_new_file
    try:
        created_paths = _create_record_shell(root, request, manifest, writer)
    except _CreationWriteFailure as exc:
        return MeasurementRecordCreationRun(
            request=request,
            storage_root=root,
            rollback_performed=exc.rollback_performed,
            creation_error=str(exc),
        )

    return MeasurementRecordCreationRun(
        request=request,
        storage_root=root,
        created_paths=tuple(created_paths),
    )


def _build_manifest(request: MeasurementRecordCreationRequest) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_id": request.record_id,
        "lifecycle_state": request.initial_lifecycle_state,
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
            "source_kind": request.creation_source_kind,
            "source_kind_authority": "declared_provenance_only",
        },
        "storage": {
            "record_dir": request.record_dir,
            "manifest_path": request.manifest_path,
        },
        "primary_data": {
            "state": "not_recorded",
            "references": [],
        },
    }


def _existing_storage_root(storage_root: Path) -> Path:
    if storage_root.is_symlink():
        raise ValueError("measurement record creation storage root must not be a symlink")
    if not storage_root.is_dir():
        raise ValueError("measurement record creation requires an existing storage root")
    return storage_root.resolve()


def _create_record_shell(
    root: Path,
    request: MeasurementRecordCreationRequest,
    manifest: dict[str, Any],
    manifest_writer: Callable[[Path, dict[str, Any]], None],
) -> list[str]:
    if _target_exists(root, request.record_dir):
        raise _CreationWriteFailure(
            "measurement record creation record_dir target already exists",
            rollback_performed=False,
        )
    _ensure_no_symlink_parents(root, request.record_dir, "measurement record creation record_dir")

    created_dirs: list[str] = []
    created_manifest = False
    try:
        created_dirs = _create_directory_chain(root, request.record_dir)
        manifest_path = _path_under(root, request.manifest_path)
        manifest_writer(manifest_path, manifest)
        created_manifest = True
    except Exception as exc:
        if created_manifest:
            try:
                _path_under(root, request.manifest_path).unlink()
            except FileNotFoundError:
                pass
        _remove_created_dirs(root, created_dirs)
        if isinstance(exc, _CreationWriteFailure):
            raise exc
        raise _CreationWriteFailure(
            f"measurement record creation write failed: {exc}",
            rollback_performed=bool(created_dirs) or created_manifest,
        ) from exc

    return [*created_dirs, request.manifest_path]


def _write_json_new_file(path: Path, content: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*relative_path_parts(relative_path, "measurement record creation path"))


def _target_exists(root: Path, relative_path: str) -> bool:
    return os.path.lexists(_path_under(root, relative_path))


def _ensure_no_symlink_parents(root: Path, relative_path: str, label: str) -> None:
    current = root
    for part in relative_path_parts(relative_path, label)[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} parent is a symlink")
        if current.exists() and not current.is_dir():
            raise ValueError(f"{label} parent is not a directory")


def _create_directory_chain(root: Path, relative_dir: str) -> list[str]:
    current = root
    created_dirs: list[str] = []
    current_parts: list[str] = []
    try:
        for part in relative_path_parts(relative_dir, "measurement record creation record_dir"):
            current_parts.append(part)
            current = current / part
            if current.is_symlink():
                raise ValueError("measurement record creation record_dir parent is a symlink")
            if current.exists():
                if not current.is_dir():
                    raise ValueError(
                        "measurement record creation record_dir parent is not a directory"
                    )
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


class _CreationWriteFailure(RuntimeError):
    def __init__(self, message: str, *, rollback_performed: bool) -> None:
        super().__init__(message)
        self.rollback_performed = rollback_performed
