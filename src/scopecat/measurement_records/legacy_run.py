"""Record declared legacy-run information in Measurement Records storage."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records._contracts import (
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
from scopecat.measurement_records.creation import (
    MeasurementRecordCreationRequest,
    MeasurementRecordCreationRun,
    create_measurement_record_from_request,
)

LEGACY_RUN_RECEIPT_SCHEMA = "measurement_record_legacy_run_receipt_v0"
LEGACY_RUN_RECEIPT_NAME = "legacy-run-receipt.json"
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
LOCATOR_KINDS = {"workspace_relative_path", "package_relative_path", "opaque_reference"}
LOCATOR_ROLES = {
    "primary_data",
    "source_code",
    "notebook",
    "configuration",
    "debug_log",
    "supporting_evidence",
    "operator_note",
    "other",
}
LOCATOR_STATES = {"declared_available", "unavailable", "redacted"}
CONTEXT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "managed_code_version",
    "declared_environment",
    "analysis_choice",
    "artifact",
}
CONTEXT_ROLES = {
    "run_start_context",
    "calibration_context",
    "comparison_reference",
    "operator_selected_context",
}
CONTEXT_STATES = {"declared", "unavailable", "redacted"}


@dataclass(frozen=True)
class LegacyRunLocator:
    """Declared legacy locator kept as a reference, not imported payload."""

    locator_id: str
    kind: str
    role: str
    value: str
    state: str = "declared_available"
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.locator_id, "legacy locator locator_id")
        if self.kind not in LOCATOR_KINDS:
            raise ValueError("legacy locator kind is unsupported")
        if self.role not in LOCATOR_ROLES:
            raise ValueError("legacy locator role is unsupported")
        if self.kind in {"workspace_relative_path", "package_relative_path"}:
            validate_relative_path(self.value, "legacy locator value")
        else:
            validate_text(self.value, "legacy locator value")
        if self.state not in LOCATOR_STATES:
            raise ValueError("legacy locator state is unsupported")
        if self.state != "declared_available" and not self.reason:
            raise ValueError("unavailable or redacted legacy locator requires reason")
        if self.state == "declared_available" and self.reason:
            raise ValueError("available legacy locator must not carry reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator_id": self.locator_id,
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LegacyRunContextReference:
    """Optional declared context reference associated with a legacy run."""

    context_family: str
    context_id: str
    role: str
    state: str = "declared"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.context_family not in CONTEXT_FAMILIES:
            raise ValueError("legacy context reference family is unsupported")
        validate_public_identifier(self.context_id, "legacy context reference context_id")
        if self.role not in CONTEXT_ROLES:
            raise ValueError("legacy context reference role is unsupported")
        if self.state not in CONTEXT_STATES:
            raise ValueError("legacy context reference state is unsupported")
        if self.state != "declared" and not self.reason:
            raise ValueError("unavailable or redacted legacy context requires reason")
        if self.state == "declared" and self.reason:
            raise ValueError("declared legacy context must not carry reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_family": self.context_family,
            "context_id": self.context_id,
            "role": self.role,
            "state": self.state,
            "reason": self.reason,
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
    context_references: tuple[LegacyRunContextReference, ...] = ()
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
        if not isinstance(self.context_references, tuple):
            raise ValueError("legacy run context_references must be a tuple")
        if len({locator.locator_id for locator in self.locators}) != len(self.locators):
            raise ValueError("legacy run locators must have unique locator_id values")
        if len(
            {
                (reference.context_family, reference.context_id, reference.role)
                for reference in self.context_references
            }
        ) != len(self.context_references):
            raise ValueError("legacy run context references must be unique")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/record-manifest.json"

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
            "context_references": [reference.to_dict() for reference in self.context_references],
            "operator_notes": self.operator_notes,
        }


@dataclass(frozen=True)
class LegacyRunRecordRun:
    """Local receipt for a legacy-run storage mutation."""

    request: LegacyRunRecordRequest
    storage_root: Path
    creation_run: MeasurementRecordCreationRun | None = None
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
            "artifact_posture": "local_legacy_run_record_receipt",
            "classification": self.classification,
            "request": self.request.to_dict(),
            "creation": None if self.creation_run is None else self.creation_run.to_dict(),
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

    creation_request = MeasurementRecordCreationRequest(
        request_id=request.request_id,
        approval_state=request.approval_state,
        record_id=request.record_id,
        record_dir=request.record_dir,
        initial_lifecycle_state="created",
        creation_source_kind="legacy_system",
        created_at=request.created_at,
        label=request.label,
        experiment_type=request.experiment_type,
    )
    creation_run = create_measurement_record_from_request(
        creation_request,
        storage_root=root,
    )
    if not creation_run.created:
        return LegacyRunRecordRun(
            request=request,
            storage_root=root,
            creation_run=creation_run,
            record_error=creation_run.creation_error or "record shell was not created",
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
            creation_run=creation_run,
            rollback_performed=rollback_performed,
            record_error=str(exc),
        )

    return LegacyRunRecordRun(
        request=request,
        storage_root=root,
        creation_run=creation_run,
        legacy_receipt_digest=_sha256(content),
        legacy_receipt_size_bytes=len(content),
    )


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
        "context_references": [reference.to_dict() for reference in request.context_references],
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


def _optional_list(source: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = source.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"legacy run {key} must be a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"legacy run {key} entries must be objects")
    return value


class _LegacyReceiptWriteFailure(RuntimeError):
    """Receipt write failed after record shell creation."""
