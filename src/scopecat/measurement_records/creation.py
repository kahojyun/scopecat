"""Durable measurement-record creation prototype."""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

PUBLIC_IDENTIFIER_MAX_LENGTH = 128
CREATION_SCHEMA = "scopecat.measurement_record_creation.v0"
CANDIDATE_MANIFEST_SCHEMA = "measurement_record_creation_candidate_v0"
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
INITIAL_LIFECYCLE_STATES = {"created", "in_progress", "review_needed"}
CREATION_SOURCE_KINDS = {"manual", "writer", "import", "handoff", "legacy_system"}
RECORD_MANIFEST_NAME = "record-manifest.json"
CREATION_POLICY = {
    "workflow_authority": "approved_measurement_record_creation_request",
    "storage_authority": "caller_provided_storage_root",
    "record_identity": "caller_declared_public_safe_record_id",
    "record_directory": "caller_declared_relative_record_directory",
    "manifest": "write_initial_record_manifest",
    "collision_policy": "no_overwrite",
    "rollback": "best_effort_synchronous_cleanup",
    "storage_root_concurrency": "not_supported",
    "final_storage_schema": "not_defined",
    "import_acceptance": "not_performed",
    "existing_record_update": "not_performed",
}
DOES_NOT_CLAIM = [
    "final_storage_schema",
    "final_record_id_generation_policy",
    "import_acceptance",
    "existing_record_update",
    "conflict_resolution",
    "read_model_refresh",
    "crash_recovery",
    "concurrent_storage_root_mutation",
    "archive_extraction",
    "external_authenticity_or_trust_validation",
    "linked_context_payload_import",
    "scientific_validity",
]

_PUBLIC_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PRIVATE_PATH_SEGMENTS = {"Users", "private"}
_PRIVATE_PATH_MARKERS = tuple(f"/{part}/" for part in _PRIVATE_PATH_SEGMENTS)


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
        _validate_public_path_segments(self.record_dir, "creation request record_dir")
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
            "creation_policy": copy.deepcopy(CREATION_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_creation_request",
                    *([] if not self.created else ["write_initial_record_manifest"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
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


def create_measurement_record(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordCreationRun:
    """Create a measurement-record shell from a raw creation source."""

    request = _parse_source(source)
    return create_measurement_record_from_request(request, storage_root=storage_root)


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


def _parse_source(source: dict[str, Any]) -> MeasurementRecordCreationRequest:
    if source.get("creation_schema") != CREATION_SCHEMA:
        raise ValueError(f"creation source schema must be {CREATION_SCHEMA}")
    if source.get("creation_policy") != CREATION_POLICY:
        raise ValueError("creation source policy is unsupported")
    request = _require_dict(source, "creation_request")
    return MeasurementRecordCreationRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        initial_lifecycle_state=_optional_text(
            request,
            "initial_lifecycle_state",
            default="created",
        ),
        creation_source_kind=_optional_text(request, "creation_source_kind", default="manual"),
        created_at=_optional_text(request, "created_at", default=None),
        label=_optional_text(request, "label", default=None),
        experiment_type=_optional_text(request, "experiment_type", default=None),
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
        "schema": CANDIDATE_MANIFEST_SCHEMA,
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
        "does_not_claim": list(DOES_NOT_CLAIM),
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


def validate_public_identifier(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > PUBLIC_IDENTIFIER_MAX_LENGTH
        or value in {".", ".."}
        or not _PUBLIC_IDENTIFIER.fullmatch(value)
        or value.startswith(("/", "~"))
        or "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(marker in value for marker in _PRIVATE_PATH_MARKERS)
    ):
        raise ValueError(f"{owner} must be a public-safe identifier")
    return value


def validate_relative_path(value: Any, owner: str) -> str:
    if not _path_is_relative(value):
        raise ValueError(f"{owner} path must be relative")
    return value


def relative_path_parts(value: Any, owner: str = "path") -> tuple[str, ...]:
    return PurePosixPath(validate_relative_path(value, owner)).parts


def validate_text(value: Any, owner: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{owner} must be text")
    return value


def _path_is_relative(path: Any) -> bool:
    if not isinstance(path, str):
        return False
    parsed = PurePosixPath(path)
    raw_parts = path.split("/")
    return (
        bool(path)
        and path != "."
        and "\\" not in path
        and not re.match(r"^[A-Za-z]:", path)
        and not parsed.is_absolute()
        and not any(part in {"", ".", ".."} for part in raw_parts)
    )


def _validate_public_path_segments(value: str, owner: str) -> None:
    for segment in relative_path_parts(value, owner):
        if segment in _PRIVATE_PATH_SEGMENTS:
            raise ValueError(f"{owner} path segments must be public-safe")
        try:
            validate_public_identifier(segment, f"{owner} path segment")
        except ValueError as exc:
            raise ValueError(f"{owner} path segments must be public-safe") from exc


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(
    value: dict[str, Any],
    field: str,
    *,
    default: str | None,
) -> str | None:
    if field not in value:
        return default
    return validate_text(value[field], field)
