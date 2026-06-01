"""Attach declared context and analysis references to measurement records."""

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
    CANDIDATE_MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)

CONTEXT_ATTACHMENT_SCHEMA = "scopecat.measurement_record_context_attachment.v0"
CONTEXT_ATTACHMENT_RECEIPT_SCHEMA = "measurement_record_context_attachment_receipt_v0"
CONTEXT_ATTACHMENT_RECEIPT_DIR = "context-attachments"
CONTEXT_ATTACHMENT_POLICY = {
    "workflow_authority": "approved_measurement_record_context_attachment_request",
    "record_authority": "existing_measurement_record_creation_manifest",
    "attachment_authority": "caller_declared_context_and_evidence_references",
    "payload_handling": "references_only",
    "receipt_materialization": "record_local_no_overwrite_receipt",
    "storage_mutation": "append_record_local_context_attachment_receipt_only",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "final_storage_schema": "not_defined",
}
CONTEXT_ATTACHMENT_REVIEW_POLICY = {
    "input_authority": "record_local_context_attachment_receipts",
    "payload_handling": "references_only",
    "storage_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "final_storage_schema": "not_defined",
}
DOES_NOT_CLAIM = [
    "context_payload_import",
    "file_observation",
    "checksum_verification_against_target",
    "parameter_file_parsing",
    "setup_binding_payload_parsing",
    "code_snapshot_capture",
    "code_execution",
    "analysis_execution",
    "analysis_validity",
    "parameter_write_back",
    "hardware_control",
    "read_model_refresh",
    "manifest_replacement",
    "final_storage_schema",
    "gui_review_state",
]
APPROVAL_STATES = {"approved", "rejected", "needs_review"}
ATTACHMENT_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "experiment_code",
    "managed_code_version",
    "preliminary_analysis",
    "supporting_evidence",
}
ATTACHMENT_ROLES = {
    "parameter_file",
    "parameter_snapshot",
    "setup_binding_file",
    "setup_binding_snapshot",
    "code_file",
    "code_directory",
    "code_snapshot",
    "analysis_result",
    "analysis_summary",
    "debug_evidence",
    "operator_selected_context",
    "run_start_context",
}
REFERENCE_KINDS = {
    "record_reference",
    "workspace_relative_path",
    "package_relative_path",
    "opaque_reference",
    "external_reference",
}
ATTACHMENT_STATES = {"declared_available", "unavailable", "redacted"}


@dataclass(frozen=True)
class MeasurementRecordContextAttachment:
    """One declared reference attached to a measurement record."""

    attachment_id: str
    family: str
    role: str
    reference_kind: str
    reference_value: str
    state: str = "declared_available"
    label: str | None = None
    digest: str | None = None
    size_bytes: int | None = None
    preview: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.attachment_id, "context attachment attachment_id")
        if self.family not in ATTACHMENT_FAMILIES:
            raise ValueError("context attachment family is unsupported")
        if self.role not in ATTACHMENT_ROLES:
            raise ValueError("context attachment role is unsupported")
        if self.reference_kind not in REFERENCE_KINDS:
            raise ValueError("context attachment reference_kind is unsupported")
        if self.reference_kind in {"workspace_relative_path", "package_relative_path"}:
            validate_relative_path(self.reference_value, "context attachment reference_value")
        else:
            validate_text(self.reference_value, "context attachment reference_value")
        if self.state not in ATTACHMENT_STATES:
            raise ValueError("context attachment state is unsupported")
        if self.state != "declared_available" and not self.reason:
            raise ValueError("unavailable or redacted context attachment requires reason")
        if self.state == "declared_available" and self.reason:
            raise ValueError("available context attachment must not carry reason")
        if self.label is not None:
            validate_text(self.label, "context attachment label")
        if self.digest is not None:
            _validate_sha256_digest(self.digest, "context attachment digest")
        if self.size_bytes is not None:
            _validate_non_negative_integer(self.size_bytes, "context attachment size_bytes")
        if self.preview is not None:
            validate_text(self.preview, "context attachment preview")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "attachment_id": self.attachment_id,
            "family": self.family,
            "role": self.role,
            "reference_kind": self.reference_kind,
            "reference_value": self.reference_value,
            "state": self.state,
            "label": self.label,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "preview": self.preview,
            "reason": self.reason,
        }
        return result


@dataclass(frozen=True)
class MeasurementRecordContextAttachmentRequest:
    """Approved request to add record-local context attachment references."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    attachment_set_id: str
    attachments: tuple[MeasurementRecordContextAttachment, ...]
    attachment_receipt_path: str | None = None
    previous_attachment_receipt_path: str | None = None
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "context attachment request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("context attachment approval_state is unsupported")
        validate_public_identifier(self.record_id, "context attachment record_id")
        validate_relative_path(self.record_dir, "context attachment record_dir")
        validate_public_identifier(
            self.attachment_set_id,
            "context attachment attachment_set_id",
        )
        validate_relative_path(self.creation_manifest_path, "context attachment manifest_path")
        validate_relative_path(self.receipt_path, "context attachment receipt_path")
        _validate_strict_child_path(
            self.receipt_path,
            self.record_dir,
            "context attachment receipt_path",
        )
        if self.previous_attachment_receipt_path is not None:
            validate_relative_path(
                self.previous_attachment_receipt_path,
                "context attachment previous_attachment_receipt_path",
            )
            _validate_strict_child_path(
                self.previous_attachment_receipt_path,
                self.record_dir,
                "context attachment previous_attachment_receipt_path",
            )
            _validate_non_overlapping_paths(
                (
                    self.creation_manifest_path,
                    self.receipt_path,
                    self.previous_attachment_receipt_path,
                ),
                "context attachment paths",
            )
        else:
            _validate_non_overlapping_paths(
                (self.creation_manifest_path, self.receipt_path),
                "context attachment paths",
            )
        if not isinstance(self.attachments, tuple):
            raise ValueError("context attachment attachments must be a tuple")
        if not self.attachments:
            raise ValueError("context attachment request requires at least one attachment")
        if len({attachment.attachment_id for attachment in self.attachments}) != len(
            self.attachments
        ):
            raise ValueError("context attachment attachment_id values must be unique")
        if self.operator_notes is not None:
            validate_text(self.operator_notes, "context attachment operator_notes")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    @property
    def receipt_path(self) -> str:
        return (
            self.attachment_receipt_path
            or f"{self.record_dir}/{CONTEXT_ATTACHMENT_RECEIPT_DIR}/{self.attachment_set_id}.json"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "attachment_set_id": self.attachment_set_id,
            "attachment_receipt_path": self.receipt_path,
            "previous_attachment_receipt_path": self.previous_attachment_receipt_path,
            "attachments": [attachment.to_dict() for attachment in self.attachments],
            "operator_notes": self.operator_notes,
        }


@dataclass(frozen=True)
class MeasurementRecordContextAttachmentRun:
    """Local receipt for a context-attachment storage mutation."""

    request: MeasurementRecordContextAttachmentRequest
    storage_root: Path
    receipt_digest: str | None = None
    receipt_size_bytes: int | None = None
    attachment_error: str | None = None

    @property
    def attached(self) -> bool:
        return self.classification == "attached_measurement_record_context"

    @property
    def classification(self) -> str:
        if self.attachment_error is not None:
            return "blocked_before_context_attachment"
        if not self.request.approved:
            return "blocked_before_context_attachment"
        return "attached_measurement_record_context"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_measurement_record_context_attachment_receipt_run",
            "context_attachment_policy": copy.deepcopy(CONTEXT_ATTACHMENT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_context_attachment_request",
                    *([] if not self.request.approved else ["read_creation_manifest"]),
                    *(
                        []
                        if (
                            not self.request.approved
                            or not self.request.previous_attachment_receipt_path
                        )
                        else ["read_previous_context_attachment_receipt"]
                    ),
                    *([] if not self.attached else ["write_context_attachment_receipt"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "receipt": {
                "saved": self.attached,
                "storage_root": str(self.storage_root),
                "attachment_receipt_path": self.request.receipt_path,
                "receipt_digest": self.receipt_digest,
                "receipt_size_bytes": self.receipt_size_bytes,
                "attachment_error": self.attachment_error,
            },
        }


def attach_measurement_record_context(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordContextAttachmentRun:
    """Attach declared context references from a raw source."""

    request = _parse_source(source)
    return attach_measurement_record_context_from_request(request, storage_root=storage_root)


def attach_measurement_record_context_from_request(
    request: MeasurementRecordContextAttachmentRequest,
    *,
    storage_root: str | Path,
    receipt_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordContextAttachmentRun:
    """Write one record-local context attachment receipt without touching read models."""

    root = _existing_directory_root(Path(storage_root), "context attachment storage root")
    if not request.approved:
        return MeasurementRecordContextAttachmentRun(request=request, storage_root=root)

    try:
        manifest = _read_creation_manifest(root, request)
        previous = _read_previous_attachment_receipt(root, request)
        receipt = _context_attachment_receipt(request, manifest, previous)
        content = _json_bytes(receipt)
        _write_receipt(root, request.receipt_path, content, receipt_writer or _write_new_file)
    except ValueError as exc:
        return MeasurementRecordContextAttachmentRun(
            request=request,
            storage_root=root,
            attachment_error=str(exc),
        )

    return MeasurementRecordContextAttachmentRun(
        request=request,
        storage_root=root,
        receipt_digest=_sha256(content),
        receipt_size_bytes=len(content),
    )


def list_measurement_record_context_attachments(
    *,
    storage_root: str | Path,
    records_dir: str = "records",
) -> dict[str, Any]:
    """Read record-local context attachment receipts for local review."""

    validate_relative_path(records_dir, "context attachment review records_dir")
    root = _existing_directory_root(Path(storage_root), "context attachment review storage root")
    records_path = _path_under(root, records_dir)
    _ensure_no_symlink_parents(root, records_dir, "context attachment review records dir")
    entries: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    if not records_path.exists():
        return _context_attachment_review(entries, findings)
    if records_path.is_symlink():
        raise ValueError("context attachment review records dir must not be a symlink")
    if not records_path.is_dir():
        raise ValueError("context attachment review records dir must be a directory")

    for record_path in sorted(records_path.iterdir(), key=lambda item: item.name):
        record_rel = _relative_to_root(root, record_path)
        if record_path.is_symlink() or not record_path.is_dir():
            continue
        attachment_dir = record_path / CONTEXT_ATTACHMENT_RECEIPT_DIR
        if not attachment_dir.exists():
            continue
        attachment_dir_rel = _relative_to_root(root, attachment_dir)
        if attachment_dir.is_symlink():
            findings.append(
                _finding(
                    "context_attachment_dir_symlink_ignored",
                    attachment_dir_rel,
                    "Context attachment directory is a symlink.",
                )
            )
            continue
        if not attachment_dir.is_dir():
            findings.append(
                _finding(
                    "context_attachment_dir_invalid",
                    attachment_dir_rel,
                    "Context attachment path is not a directory.",
                )
            )
            continue
        for receipt_path in sorted(attachment_dir.iterdir(), key=lambda item: item.name):
            receipt_rel = _relative_to_root(root, receipt_path)
            if receipt_path.is_symlink():
                findings.append(
                    _finding(
                        "context_attachment_receipt_symlink_ignored",
                        receipt_rel,
                        "Context attachment receipt is a symlink.",
                    )
                )
                continue
            if not receipt_path.is_file():
                findings.append(
                    _finding(
                        "context_attachment_receipt_invalid",
                        receipt_rel,
                        "Context attachment receipt candidate is not a file.",
                    )
                )
                continue
            try:
                content = receipt_path.read_bytes()
                receipt = _parse_context_attachment_receipt(content)
                entry = _entry_from_receipt(receipt, receipt_rel, _sha256(content), len(content))
                if entry["record_dir"] != record_rel:
                    raise ValueError("Context attachment receipt record_dir conflicts with scan.")
            except ValueError as exc:
                findings.append(
                    _finding(
                        "context_attachment_receipt_invalid",
                        receipt_rel,
                        str(exc),
                    )
                )
                continue
            entries.append(entry)
    return _context_attachment_review(entries, findings)


def _parse_source(source: dict[str, Any]) -> MeasurementRecordContextAttachmentRequest:
    if source.get("context_attachment_schema") != CONTEXT_ATTACHMENT_SCHEMA:
        raise ValueError(f"context attachment source schema must be {CONTEXT_ATTACHMENT_SCHEMA}")
    if source.get("context_attachment_policy") != CONTEXT_ATTACHMENT_POLICY:
        raise ValueError("context attachment source policy is unsupported")
    request = _require_dict(source, "context_attachment_request")
    return MeasurementRecordContextAttachmentRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        attachment_set_id=_require_text(request, "attachment_set_id"),
        attachment_receipt_path=_optional_text(
            request,
            "attachment_receipt_path",
            default=None,
        ),
        previous_attachment_receipt_path=_optional_text(
            request,
            "previous_attachment_receipt_path",
            default=None,
        ),
        attachments=tuple(
            MeasurementRecordContextAttachment(
                attachment_id=_require_text(attachment, "attachment_id"),
                family=_require_text(attachment, "family"),
                role=_require_text(attachment, "role"),
                reference_kind=_require_text(attachment, "reference_kind"),
                reference_value=_require_text(attachment, "reference_value"),
                state=_optional_text(attachment, "state", default="declared_available"),
                label=_optional_text(attachment, "label", default=None),
                digest=_optional_text(attachment, "digest", default=None),
                size_bytes=_optional_int(attachment, "size_bytes"),
                preview=_optional_text(attachment, "preview", default=None),
                reason=_optional_text(attachment, "reason", default=None),
            )
            for attachment in _require_list(request, "attachments")
        ),
        operator_notes=_optional_text(request, "operator_notes", default=None),
    )


def _read_creation_manifest(
    root: Path,
    request: MeasurementRecordContextAttachmentRequest,
) -> dict[str, Any]:
    manifest = _read_json(root, request.creation_manifest_path, "context attachment manifest")
    if manifest.get("schema") != CANDIDATE_MANIFEST_SCHEMA:
        raise ValueError("context attachment manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    storage = _require_dict(manifest, "storage")
    if record.get("record_id") != request.record_id:
        raise ValueError("context attachment record_id must match creation manifest")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("context attachment record_dir must match creation manifest")
    if storage.get("manifest_path") != request.creation_manifest_path:
        raise ValueError("context attachment manifest_path must match creation manifest")
    return manifest


def _read_previous_attachment_receipt(
    root: Path,
    request: MeasurementRecordContextAttachmentRequest,
) -> dict[str, Any] | None:
    if request.previous_attachment_receipt_path is None:
        return None
    receipt = _read_json(
        root,
        request.previous_attachment_receipt_path,
        "previous context attachment receipt",
    )
    _validate_context_attachment_receipt(receipt)
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("previous context attachment record_id must match request")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("previous context attachment record_dir must match request")
    return receipt


def _context_attachment_receipt(
    request: MeasurementRecordContextAttachmentRequest,
    manifest: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    previous_ref = None
    if previous is not None:
        previous_content = _json_bytes(previous)
        previous_ref = {
            "path": request.previous_attachment_receipt_path,
            "digest": _sha256(previous_content),
            "attachment_set_id": _require_dict(previous, "attachment_set")["attachment_set_id"],
        }
    return {
        "schema": CONTEXT_ATTACHMENT_RECEIPT_SCHEMA,
        "artifact_posture": "local_measurement_record_context_attachment_receipt",
        "context_attachment_policy": copy.deepcopy(CONTEXT_ATTACHMENT_POLICY),
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "creation_lifecycle_state": record["lifecycle_state"],
            "attachment_receipt_path": request.receipt_path,
        },
        "attachment_set": {
            "attachment_set_id": request.attachment_set_id,
            "previous_attachment_receipt": previous_ref,
            "operator_notes": request.operator_notes,
        },
        "attachments": [attachment.to_dict() for attachment in request.attachments],
        "workflow": {
            "request_id": request.request_id,
            "classification": "measurement_record_context_attached_for_review",
            "does_not_claim": list(DOES_NOT_CLAIM),
        },
    }


def _write_receipt(
    root: Path,
    relative_path: str,
    content: bytes,
    writer: Callable[[Path, bytes], None],
) -> None:
    path = _path_under(root, relative_path)
    _ensure_no_symlink_parents(root, relative_path, "context attachment receipt target")
    if path.exists() or path.is_symlink():
        raise ValueError("context attachment receipt target already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        writer(path, content)
    except OSError as exc:
        raise ValueError(str(exc)) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _parse_context_attachment_receipt(content: bytes) -> dict[str, Any]:
    try:
        receipt = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Context attachment receipt must be utf-8 JSON.") from exc
    if not isinstance(receipt, dict):
        raise ValueError("Context attachment receipt must be a JSON object.")
    _validate_context_attachment_receipt(receipt)
    return receipt


def _validate_context_attachment_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != CONTEXT_ATTACHMENT_RECEIPT_SCHEMA:
        raise ValueError("Context attachment receipt schema is unsupported.")
    if receipt.get("artifact_posture") != "local_measurement_record_context_attachment_receipt":
        raise ValueError("Context attachment receipt posture is unsupported.")
    if receipt.get("context_attachment_policy") != CONTEXT_ATTACHMENT_POLICY:
        raise ValueError("Context attachment receipt policy is unsupported.")
    workflow = _require_dict(receipt, "workflow")
    if workflow.get("does_not_claim") != DOES_NOT_CLAIM:
        raise ValueError("Context attachment receipt non-claims are unsupported.")
    validate_public_identifier(workflow.get("request_id"), "context attachment workflow request_id")
    record = _require_dict(receipt, "record")
    validate_public_identifier(record.get("record_id"), "context attachment record_id")
    record_dir = validate_relative_path(record.get("record_dir"), "context attachment record_dir")
    manifest_path = validate_relative_path(
        record.get("creation_manifest_path"),
        "context attachment creation_manifest_path",
    )
    _validate_strict_child_path(
        manifest_path,
        record_dir,
        "context attachment creation_manifest_path",
    )
    receipt_path = validate_relative_path(
        record.get("attachment_receipt_path"),
        "context attachment receipt_path",
    )
    _validate_strict_child_path(
        receipt_path,
        record_dir,
        "context attachment receipt_path",
    )
    attachment_set = _require_dict(receipt, "attachment_set")
    validate_public_identifier(
        attachment_set.get("attachment_set_id"),
        "context attachment attachment_set_id",
    )
    if attachment_set.get("operator_notes") is not None:
        validate_text(attachment_set["operator_notes"], "context attachment operator_notes")
    previous = attachment_set.get("previous_attachment_receipt")
    if previous is not None:
        if not isinstance(previous, dict):
            raise ValueError("previous context attachment receipt must be an object")
        previous_path = validate_relative_path(
            previous.get("path"),
            "previous context attachment path",
        )
        _validate_strict_child_path(
            previous_path,
            record_dir,
            "previous context attachment path",
        )
        _validate_sha256_digest(previous.get("digest"), "previous context attachment digest")
        validate_public_identifier(
            previous.get("attachment_set_id"),
            "previous context attachment attachment_set_id",
        )
    attachments = _require_list(receipt, "attachments")
    if not attachments:
        raise ValueError("Context attachment receipt requires attachments.")
    parsed = tuple(_attachment_from_dict(item) for item in attachments)
    if len({attachment.attachment_id for attachment in parsed}) != len(parsed):
        raise ValueError("Context attachment receipt attachment ids must be unique.")


def _attachment_from_dict(source: dict[str, Any]) -> MeasurementRecordContextAttachment:
    if not isinstance(source, dict):
        raise ValueError("context attachment item must be an object")
    return MeasurementRecordContextAttachment(
        attachment_id=_require_text(source, "attachment_id"),
        family=_require_text(source, "family"),
        role=_require_text(source, "role"),
        reference_kind=_require_text(source, "reference_kind"),
        reference_value=_require_text(source, "reference_value"),
        state=_optional_text(source, "state", default="declared_available"),
        label=_optional_text(source, "label", default=None),
        digest=_optional_text(source, "digest", default=None),
        size_bytes=_optional_int(source, "size_bytes"),
        preview=_optional_text(source, "preview", default=None),
        reason=_optional_text(source, "reason", default=None),
    )


def _entry_from_receipt(
    receipt: dict[str, Any],
    receipt_path: str,
    receipt_digest: str,
    receipt_size_bytes: int,
) -> dict[str, Any]:
    record = _require_dict(receipt, "record")
    attachment_set = _require_dict(receipt, "attachment_set")
    attachments = _require_list(receipt, "attachments")
    return {
        "record_id": validate_public_identifier(
            record.get("record_id"),
            "context attachment record_id",
        ),
        "record_dir": validate_relative_path(
            record.get("record_dir"),
            "context attachment record_dir",
        ),
        "receipt": {
            "path": receipt_path,
            "digest": receipt_digest,
            "size_bytes": receipt_size_bytes,
        },
        "attachment_set": {
            "attachment_set_id": validate_public_identifier(
                attachment_set.get("attachment_set_id"),
                "context attachment attachment_set_id",
            ),
            "previous_attachment_receipt": copy.deepcopy(
                attachment_set.get("previous_attachment_receipt")
            ),
            "operator_notes": attachment_set.get("operator_notes"),
        },
        "attachments": [copy.deepcopy(attachment) for attachment in attachments],
        "attachment_count": len(attachments),
    }


def _context_attachment_review(
    entries: list[dict[str, Any]],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "artifact_posture": "local_measurement_record_context_attachment_review",
        "context_attachment_review_policy": copy.deepcopy(CONTEXT_ATTACHMENT_REVIEW_POLICY),
        "workflow": {
            "classification": (
                "measurement_record_context_attachment_review_needed"
                if findings
                else "measurement_record_context_attachment_review_ready"
            ),
            "steps": [
                "scan_record_local_context_attachment_receipts",
                "project_context_attachment_references",
            ],
            "does_not_claim": list(DOES_NOT_CLAIM),
        },
        "entries": entries,
        "review_findings": findings,
    }


def _read_json(root: Path, relative_path: str, owner: str) -> dict[str, Any]:
    _ensure_no_symlink_parents(root, relative_path, owner)
    target = _path_under(root, relative_path)
    if target.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{owner} is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{owner} must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _finding(code: str, target: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
        "does_not_claim": "record_repair_or_payload_observation",
    }


def _path_under(root: Path, relative_path: str) -> Path:
    return _path_under_common(root, relative_path, "context attachment path")


def _relative_to_root(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _validate_non_overlapping_paths(paths: tuple[str, ...], owner: str) -> None:
    _validate_non_overlapping_paths_common(paths, owner, reject_parent_child=True)


def _validate_sha256_digest(value: Any, owner: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value.removeprefix("sha256:"))
    ):
        raise ValueError(f"{owner} must be a sha256-prefixed hex digest")
    return value


def _validate_non_negative_integer(value: Any, owner: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{owner} must be a non-negative integer")
    return value


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"context attachment {key} must be an object")
    return value


def _require_list(source: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = source.get(key)
    if not isinstance(value, list):
        raise ValueError(f"context attachment {key} must be a list")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    return validate_text(source.get(key), f"context attachment {key}")


def _optional_text(source: dict[str, Any], key: str, *, default: str | None) -> str | None:
    value = source.get(key, default)
    if value is None:
        return None
    return validate_text(value, f"context attachment {key}")


def _optional_int(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    return _validate_non_negative_integer(value, f"context attachment {key}")
