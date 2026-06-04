"""Record declared measurement references without importing referenced payloads."""

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
    MANIFEST_SCHEMA,
    RECORD_MANIFEST_NAME,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)

RECORDED_REFERENCE_SCHEMA = "scopecat.measurement_record_recorded_reference.v0"
RECORDED_REFERENCE_RECEIPT_SCHEMA = "measurement_record_recorded_reference_receipt_v0"
RECORDED_REFERENCE_RECEIPT_DIR = "recorded-references"
RECORDED_REFERENCE_POLICY = {
    "workflow_authority": "approved_measurement_record_recorded_reference_request",
    "record_authority": "existing_measurement_record_creation_manifest",
    "reference_authority": "caller_declared_record_references",
    "payload_handling": "references_only",
    "receipt_materialization": "record_local_no_overwrite_receipt",
    "storage_mutation": "append_record_local_recorded_reference_receipt_only",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "final_storage_schema": "not_defined",
}
RECORDED_REFERENCE_REVIEW_POLICY = {
    "input_authority": "record_local_recorded_reference_receipts",
    "payload_handling": "references_only",
    "storage_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "final_storage_schema": "not_defined",
}
DOES_NOT_CLAIM = [
    "referenced_payload_import",
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
REFERENCE_FAMILIES = {
    "parameter_state",
    "setup_binding",
    "experiment_code",
    "managed_code_version",
    "derived_artifact",
    "supporting_evidence",
}
REFERENCE_ROLES = {
    "parameter_file",
    "parameter_snapshot",
    "setup_binding_file",
    "setup_binding_snapshot",
    "code_file",
    "code_directory",
    "code_snapshot",
    "preliminary_analysis_result",
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
REFERENCE_STATES = {"declared_available", "unavailable", "redacted"}


@dataclass(frozen=True)
class MeasurementRecordReference:
    """One declared reference recorded against a measurement record."""

    reference_id: str
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
        validate_public_identifier(self.reference_id, "recorded reference reference_id")
        if self.family not in REFERENCE_FAMILIES:
            raise ValueError("recorded reference family is unsupported")
        if self.role not in REFERENCE_ROLES:
            raise ValueError("recorded reference role is unsupported")
        if self.reference_kind not in REFERENCE_KINDS:
            raise ValueError("recorded reference reference_kind is unsupported")
        if self.reference_kind in {"workspace_relative_path", "package_relative_path"}:
            validate_relative_path(self.reference_value, "recorded reference reference_value")
        else:
            validate_text(self.reference_value, "recorded reference reference_value")
        if self.state not in REFERENCE_STATES:
            raise ValueError("recorded reference state is unsupported")
        if self.state != "declared_available" and not self.reason:
            raise ValueError("unavailable or redacted recorded reference requires reason")
        if self.state == "declared_available" and self.reason:
            raise ValueError("available recorded reference must not carry reason")
        if self.label is not None:
            validate_text(self.label, "recorded reference label")
        if self.digest is not None:
            _validate_sha256_digest(self.digest, "recorded reference digest")
        if self.size_bytes is not None:
            _validate_non_negative_integer(self.size_bytes, "recorded reference size_bytes")
        if self.preview is not None:
            validate_text(self.preview, "recorded reference preview")

    def to_dict(self) -> dict[str, Any]:
        result = {
            "reference_id": self.reference_id,
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
class MeasurementRecordReferenceRequest:
    """Approved request to add record-local recorded references."""

    request_id: str
    approval_state: str
    record_id: str
    record_dir: str
    reference_set_id: str
    references: tuple[MeasurementRecordReference, ...]
    reference_receipt_path: str | None = None
    previous_reference_receipt_path: str | None = None
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "recorded reference request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("recorded reference approval_state is unsupported")
        validate_public_identifier(self.record_id, "recorded reference record_id")
        validate_relative_path(self.record_dir, "recorded reference record_dir")
        validate_public_identifier(
            self.reference_set_id,
            "recorded reference reference_set_id",
        )
        validate_relative_path(self.creation_manifest_path, "recorded reference manifest_path")
        validate_relative_path(self.receipt_path, "recorded reference receipt_path")
        _validate_strict_child_path(
            self.receipt_path,
            self.record_dir,
            "recorded reference receipt_path",
        )
        if self.previous_reference_receipt_path is not None:
            validate_relative_path(
                self.previous_reference_receipt_path,
                "recorded reference previous_reference_receipt_path",
            )
            _validate_strict_child_path(
                self.previous_reference_receipt_path,
                self.record_dir,
                "recorded reference previous_reference_receipt_path",
            )
            _validate_non_overlapping_paths(
                (
                    self.creation_manifest_path,
                    self.receipt_path,
                    self.previous_reference_receipt_path,
                ),
                "recorded reference paths",
            )
        else:
            _validate_non_overlapping_paths(
                (self.creation_manifest_path, self.receipt_path),
                "recorded reference paths",
            )
        if not isinstance(self.references, tuple):
            raise ValueError("recorded references must be a tuple")
        if not self.references:
            raise ValueError("recorded reference request requires at least one reference")
        if len({reference.reference_id for reference in self.references}) != len(self.references):
            raise ValueError("recorded reference reference_id values must be unique")
        if self.operator_notes is not None:
            validate_text(self.operator_notes, "recorded reference operator_notes")

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def creation_manifest_path(self) -> str:
        return f"{self.record_dir}/{RECORD_MANIFEST_NAME}"

    @property
    def receipt_path(self) -> str:
        return (
            self.reference_receipt_path
            or f"{self.record_dir}/{RECORDED_REFERENCE_RECEIPT_DIR}/{self.reference_set_id}.json"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "creation_manifest_path": self.creation_manifest_path,
            "reference_set_id": self.reference_set_id,
            "reference_receipt_path": self.receipt_path,
            "previous_reference_receipt_path": self.previous_reference_receipt_path,
            "references": [reference.to_dict() for reference in self.references],
            "operator_notes": self.operator_notes,
        }


@dataclass(frozen=True)
class MeasurementRecordReferenceRun:
    """Local receipt for a record-local reference recording mutation."""

    request: MeasurementRecordReferenceRequest
    storage_root: Path
    receipt_digest: str | None = None
    receipt_size_bytes: int | None = None
    references_error: str | None = None

    @property
    def recorded(self) -> bool:
        return self.classification == "recorded_measurement_record_references"

    @property
    def classification(self) -> str:
        if self.references_error is not None:
            return "blocked_before_recorded_reference"
        if not self.request.approved:
            return "blocked_before_recorded_reference"
        return "recorded_measurement_record_references"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_measurement_record_recorded_reference_receipt_run",
            "recorded_reference_policy": copy.deepcopy(RECORDED_REFERENCE_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_recorded_reference_request",
                    *([] if not self.request.approved else ["read_creation_manifest"]),
                    *(
                        []
                        if (
                            not self.request.approved
                            or not self.request.previous_reference_receipt_path
                        )
                        else ["read_previous_recorded_reference_receipt"]
                    ),
                    *([] if not self.recorded else ["write_recorded_reference_receipt"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "receipt": {
                "saved": self.recorded,
                "storage_root": str(self.storage_root),
                "reference_receipt_path": self.request.receipt_path,
                "receipt_digest": self.receipt_digest,
                "receipt_size_bytes": self.receipt_size_bytes,
                "references_error": self.references_error,
            },
        }


def record_measurement_record_references(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordReferenceRun:
    """Record declared measurement references from a raw source."""

    request = _parse_source(source)
    return record_measurement_record_references_from_request(request, storage_root=storage_root)


def record_measurement_record_references_from_request(
    request: MeasurementRecordReferenceRequest,
    *,
    storage_root: str | Path,
    receipt_writer: Callable[[Path, bytes], None] | None = None,
) -> MeasurementRecordReferenceRun:
    """Write one record-local recorded reference receipt without touching read models."""

    root = _existing_directory_root(Path(storage_root), "recorded reference storage root")
    if not request.approved:
        return MeasurementRecordReferenceRun(request=request, storage_root=root)

    try:
        manifest = _read_creation_manifest(root, request)
        previous = _read_previous_reference_receipt(root, request)
        receipt = _recorded_reference_receipt(request, manifest, previous)
        content = _json_bytes(receipt)
        _write_receipt(root, request.receipt_path, content, receipt_writer or _write_new_file)
    except ValueError as exc:
        return MeasurementRecordReferenceRun(
            request=request,
            storage_root=root,
            references_error=str(exc),
        )

    return MeasurementRecordReferenceRun(
        request=request,
        storage_root=root,
        receipt_digest=_sha256(content),
        receipt_size_bytes=len(content),
    )


def list_measurement_record_references(
    *,
    storage_root: str | Path,
    records_dir: str = "records",
) -> dict[str, Any]:
    """Read record-local recorded reference receipts for local review."""

    validate_relative_path(records_dir, "recorded reference review records_dir")
    root = _existing_directory_root(Path(storage_root), "recorded reference review storage root")
    records_path = _path_under(root, records_dir)
    _ensure_no_symlink_parents(root, records_dir, "recorded reference review records dir")
    entries: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    if not records_path.exists():
        return _recorded_reference_review(entries, findings)
    if records_path.is_symlink():
        raise ValueError("recorded reference review records dir must not be a symlink")
    if not records_path.is_dir():
        raise ValueError("recorded reference review records dir must be a directory")

    for record_path in sorted(records_path.iterdir(), key=lambda item: item.name):
        record_rel = _relative_to_root(root, record_path)
        if record_path.is_symlink() or not record_path.is_dir():
            continue
        references_dir = record_path / RECORDED_REFERENCE_RECEIPT_DIR
        if not references_dir.exists():
            continue
        references_dir_rel = _relative_to_root(root, references_dir)
        if references_dir.is_symlink():
            findings.append(
                _finding(
                    "recorded_reference_dir_symlink_ignored",
                    references_dir_rel,
                    "Recorded reference directory is a symlink.",
                )
            )
            continue
        if not references_dir.is_dir():
            findings.append(
                _finding(
                    "recorded_reference_dir_invalid",
                    references_dir_rel,
                    "Recorded reference path is not a directory.",
                )
            )
            continue
        for receipt_path in sorted(references_dir.iterdir(), key=lambda item: item.name):
            receipt_rel = _relative_to_root(root, receipt_path)
            if receipt_path.is_symlink():
                findings.append(
                    _finding(
                        "recorded_reference_receipt_symlink_ignored",
                        receipt_rel,
                        "Recorded reference receipt is a symlink.",
                    )
                )
                continue
            if not receipt_path.is_file():
                findings.append(
                    _finding(
                        "recorded_reference_receipt_invalid",
                        receipt_rel,
                        "Recorded reference receipt candidate is not a file.",
                    )
                )
                continue
            try:
                content = receipt_path.read_bytes()
                receipt = _parse_recorded_reference_receipt(content)
                entry = _entry_from_receipt(receipt, receipt_rel, _sha256(content), len(content))
                if entry["record_dir"] != record_rel:
                    raise ValueError("Recorded reference receipt record_dir conflicts with scan.")
            except ValueError as exc:
                findings.append(
                    _finding(
                        "recorded_reference_receipt_invalid",
                        receipt_rel,
                        str(exc),
                    )
                )
                continue
            entries.append(entry)
    return _recorded_reference_review(entries, findings)


def _parse_source(source: dict[str, Any]) -> MeasurementRecordReferenceRequest:
    if source.get("recorded_reference_schema") != RECORDED_REFERENCE_SCHEMA:
        raise ValueError(f"recorded reference source schema must be {RECORDED_REFERENCE_SCHEMA}")
    if source.get("recorded_reference_policy") != RECORDED_REFERENCE_POLICY:
        raise ValueError("recorded reference source policy is unsupported")
    request = _require_dict(source, "recorded_reference_request")
    return MeasurementRecordReferenceRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        reference_set_id=_require_text(request, "reference_set_id"),
        reference_receipt_path=_optional_text(
            request,
            "reference_receipt_path",
            default=None,
        ),
        previous_reference_receipt_path=_optional_text(
            request,
            "previous_reference_receipt_path",
            default=None,
        ),
        references=tuple(
            MeasurementRecordReference(
                reference_id=_require_text(reference, "reference_id"),
                family=_require_text(reference, "family"),
                role=_require_text(reference, "role"),
                reference_kind=_require_text(reference, "reference_kind"),
                reference_value=_require_text(reference, "reference_value"),
                state=_optional_text(reference, "state", default="declared_available"),
                label=_optional_text(reference, "label", default=None),
                digest=_optional_text(reference, "digest", default=None),
                size_bytes=_optional_int(reference, "size_bytes"),
                preview=_optional_text(reference, "preview", default=None),
                reason=_optional_text(reference, "reason", default=None),
            )
            for reference in _require_list(request, "references")
        ),
        operator_notes=_optional_text(request, "operator_notes", default=None),
    )


def _read_creation_manifest(
    root: Path,
    request: MeasurementRecordReferenceRequest,
) -> dict[str, Any]:
    manifest = _read_json(root, request.creation_manifest_path, "recorded reference manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("recorded reference manifest schema is unsupported")
    record = _require_dict(manifest, "record")
    storage = _require_dict(manifest, "storage")
    if record.get("record_id") != request.record_id:
        raise ValueError("recorded reference record_id must match creation manifest")
    if storage.get("record_dir") != request.record_dir:
        raise ValueError("recorded reference record_dir must match creation manifest")
    if storage.get("manifest_path") != request.creation_manifest_path:
        raise ValueError("recorded reference manifest_path must match creation manifest")
    return manifest


def _read_previous_reference_receipt(
    root: Path,
    request: MeasurementRecordReferenceRequest,
) -> dict[str, Any] | None:
    if request.previous_reference_receipt_path is None:
        return None
    receipt = _read_json(
        root,
        request.previous_reference_receipt_path,
        "previous recorded reference receipt",
    )
    _validate_recorded_reference_receipt(receipt)
    record = _require_dict(receipt, "record")
    if record.get("record_id") != request.record_id:
        raise ValueError("previous recorded reference record_id must match request")
    if record.get("record_dir") != request.record_dir:
        raise ValueError("previous recorded reference record_dir must match request")
    return receipt


def _recorded_reference_receipt(
    request: MeasurementRecordReferenceRequest,
    manifest: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    previous_ref = None
    if previous is not None:
        previous_content = _json_bytes(previous)
        previous_ref = {
            "path": request.previous_reference_receipt_path,
            "digest": _sha256(previous_content),
            "reference_set_id": _require_dict(previous, "reference_set")["reference_set_id"],
        }
    return {
        "schema": RECORDED_REFERENCE_RECEIPT_SCHEMA,
        "artifact_posture": "local_measurement_record_recorded_reference_receipt",
        "recorded_reference_policy": copy.deepcopy(RECORDED_REFERENCE_POLICY),
        "record": {
            "record_id": request.record_id,
            "record_dir": request.record_dir,
            "creation_manifest_path": request.creation_manifest_path,
            "creation_lifecycle_state": record["lifecycle_state"],
            "reference_receipt_path": request.receipt_path,
        },
        "reference_set": {
            "reference_set_id": request.reference_set_id,
            "previous_reference_receipt": previous_ref,
            "operator_notes": request.operator_notes,
        },
        "references": [references.to_dict() for references in request.references],
        "workflow": {
            "request_id": request.request_id,
            "classification": "measurement_record_references_recorded_for_review",
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
    _ensure_no_symlink_parents(root, relative_path, "recorded reference receipt target")
    if path.exists() or path.is_symlink():
        raise ValueError("recorded reference receipt target already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        writer(path, content)
    except OSError as exc:
        raise ValueError(str(exc)) from exc


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)


def _parse_recorded_reference_receipt(content: bytes) -> dict[str, Any]:
    try:
        receipt = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Recorded reference receipt must be utf-8 JSON.") from exc
    if not isinstance(receipt, dict):
        raise ValueError("Recorded reference receipt must be a JSON object.")
    _validate_recorded_reference_receipt(receipt)
    return receipt


def _validate_recorded_reference_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != RECORDED_REFERENCE_RECEIPT_SCHEMA:
        raise ValueError("Recorded reference receipt schema is unsupported.")
    if receipt.get("artifact_posture") != "local_measurement_record_recorded_reference_receipt":
        raise ValueError("Recorded reference receipt posture is unsupported.")
    if receipt.get("recorded_reference_policy") != RECORDED_REFERENCE_POLICY:
        raise ValueError("Recorded reference receipt policy is unsupported.")
    workflow = _require_dict(receipt, "workflow")
    if workflow.get("does_not_claim") != DOES_NOT_CLAIM:
        raise ValueError("Recorded reference receipt non-claims are unsupported.")
    validate_public_identifier(workflow.get("request_id"), "recorded reference workflow request_id")
    record = _require_dict(receipt, "record")
    validate_public_identifier(record.get("record_id"), "recorded reference record_id")
    record_dir = validate_relative_path(record.get("record_dir"), "recorded reference record_dir")
    manifest_path = validate_relative_path(
        record.get("creation_manifest_path"),
        "recorded reference creation_manifest_path",
    )
    _validate_strict_child_path(
        manifest_path,
        record_dir,
        "recorded reference creation_manifest_path",
    )
    receipt_path = validate_relative_path(
        record.get("reference_receipt_path"),
        "recorded reference receipt_path",
    )
    _validate_strict_child_path(
        receipt_path,
        record_dir,
        "recorded reference receipt_path",
    )
    reference_set = _require_dict(receipt, "reference_set")
    validate_public_identifier(
        reference_set.get("reference_set_id"),
        "recorded reference reference_set_id",
    )
    if reference_set.get("operator_notes") is not None:
        validate_text(reference_set["operator_notes"], "recorded reference operator_notes")
    previous = reference_set.get("previous_reference_receipt")
    if previous is not None:
        if not isinstance(previous, dict):
            raise ValueError("previous recorded reference receipt must be an object")
        previous_path = validate_relative_path(
            previous.get("path"),
            "previous recorded reference path",
        )
        _validate_strict_child_path(
            previous_path,
            record_dir,
            "previous recorded reference path",
        )
        _validate_sha256_digest(previous.get("digest"), "previous recorded reference digest")
        validate_public_identifier(
            previous.get("reference_set_id"),
            "previous recorded reference reference_set_id",
        )
    references = _require_list(receipt, "references")
    if not references:
        raise ValueError("Recorded reference receipt requires references.")
    parsed = tuple(_references_from_dict(item) for item in references)
    if len({reference.reference_id for reference in parsed}) != len(parsed):
        raise ValueError("Recorded reference receipt reference ids must be unique.")


def _references_from_dict(source: dict[str, Any]) -> MeasurementRecordReference:
    if not isinstance(source, dict):
        raise ValueError("recorded reference item must be an object")
    return MeasurementRecordReference(
        reference_id=_require_text(source, "reference_id"),
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
    reference_set = _require_dict(receipt, "reference_set")
    references = _require_list(receipt, "references")
    return {
        "record_id": validate_public_identifier(
            record.get("record_id"),
            "recorded reference record_id",
        ),
        "record_dir": validate_relative_path(
            record.get("record_dir"),
            "recorded reference record_dir",
        ),
        "receipt": {
            "path": receipt_path,
            "digest": receipt_digest,
            "size_bytes": receipt_size_bytes,
        },
        "reference_set": {
            "reference_set_id": validate_public_identifier(
                reference_set.get("reference_set_id"),
                "recorded reference reference_set_id",
            ),
            "previous_reference_receipt": copy.deepcopy(
                reference_set.get("previous_reference_receipt")
            ),
            "operator_notes": reference_set.get("operator_notes"),
        },
        "references": [copy.deepcopy(reference) for reference in references],
        "reference_count": len(references),
    }


def _recorded_reference_review(
    entries: list[dict[str, Any]],
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "artifact_posture": "local_measurement_record_recorded_reference_review",
        "recorded_reference_review_policy": copy.deepcopy(RECORDED_REFERENCE_REVIEW_POLICY),
        "workflow": {
            "classification": (
                "measurement_record_recorded_reference_review_needed"
                if findings
                else "measurement_record_recorded_reference_review_ready"
            ),
            "steps": [
                "scan_record_local_recorded_reference_receipts",
                "project_recorded_reference_references",
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
    return _path_under_common(root, relative_path, "recorded reference path")


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
        raise ValueError(f"recorded reference {key} must be an object")
    return value


def _require_list(source: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = source.get(key)
    if not isinstance(value, list):
        raise ValueError(f"recorded reference {key} must be a list")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    return validate_text(source.get(key), f"recorded reference {key}")


def _optional_text(source: dict[str, Any], key: str, *, default: str | None) -> str | None:
    value = source.get(key, default)
    if value is None:
        return None
    return validate_text(value, f"recorded reference {key}")


def _optional_int(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    return _validate_non_negative_integer(value, f"recorded reference {key}")
