"""Export one stored Measurement Record to a handoff package."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.handoff._contracts import (
    HANDOFF_PACKAGE_CREATED_BY,
    MANIFEST_AUTHORITY,
    validate_handoff_package_identity,
    validate_handoff_preview_ready_metadata,
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.handoff.writer import HandoffPackageWriteReceipt, write_package
from scopecat.measurement_records._storage import (
    ensure_no_symlink_parents as _ensure_no_symlink_parents,
)
from scopecat.measurement_records._storage import (
    existing_directory_root as _existing_directory_root,
)
from scopecat.measurement_records._storage import path_under as _path_under
from scopecat.measurement_records._storage import (
    validate_strict_child_path as _validate_strict_child_path,
)
from scopecat.measurement_records.read_model_shared import READ_MODEL_SCHEMA

SELECTED_RECORD_EXPORT_POLICY = {
    "workflow_authority": "approved_selected_measurement_record_export_request",
    "record_authority": "stored_measurement_record_read_model_and_receipts",
    "source_authority": "caller_provided_storage_root_plus_record_local_paths",
    "package_authority": "delegated_handoff_package_writer",
    "primary_data_materialization": "copy_record_local_primary_data",
    "linked_context_materialization": "reference_only",
    "portable_export_boundary": "handoff_package_manifest_and_primary_data",
    "record_storage_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "schema_inference": "not_performed",
    "recursive_relation_traversal": "not_performed",
    "package_import_acceptance": "not_performed",
}
DOES_NOT_CLAIM = [
    "shared_measurement_schema",
    "read_model_refresh",
    "existing_record_update",
    "linked_context_payload_packaging",
    "reference_resolution",
    "schema_inference",
    "scientific_validity",
    "archive_creation",
    "signature_or_authenticity_validation",
    "package_import_acceptance",
]
APPROVAL_STATES = {"approved", "rejected", "needs_review"}


@dataclass(frozen=True)
class SelectedMeasurementRecordExportLinkedContext:
    """Reference-only context to expose in the handoff manifest."""

    link_id: str
    kind: str
    label: str
    relation: str
    reason: str
    context_reference: dict[str, str] | None = None

    def __post_init__(self) -> None:
        validate_public_identifier(self.link_id, "selected record export linked context link_id")
        validate_public_identifier(self.kind, "selected record export linked context kind")
        validate_text(self.label, "selected record export linked context label")
        validate_public_identifier(self.relation, "selected record export linked context relation")
        validate_text(self.reason, "selected record export linked context reason")
        if self.context_reference is not None and not isinstance(self.context_reference, dict):
            raise ValueError("selected record export context_reference must be an object")

    def to_writer_item(self, *, measurement_record_id: str) -> dict[str, Any]:
        item = {
            "link_id": self.link_id,
            "kind": self.kind,
            "label": self.label,
            "package_path": None,
            "include_status": "visible_excluded",
            "relation": self.relation,
            "authority": MANIFEST_AUTHORITY,
            "package_state": "not_packaged_visible_reference",
            "reason": self.reason,
            "linked_measurement_record_ids": [measurement_record_id],
        }
        if self.context_reference is not None:
            item["context_reference"] = copy.deepcopy(self.context_reference)
        return item


@dataclass(frozen=True)
class SelectedMeasurementRecordExportRequest:
    """Approved request to export one stored record through the handoff writer."""

    request_id: str
    approval_state: str
    package_id: str
    display_name: str
    source_export_summary_id: str
    display_path: str
    record_id: str
    record_dir: str
    read_model_path: str
    legacy_data_id: int
    target: str
    declared_preview_metadata: dict[str, Any]
    linked_context: tuple[SelectedMeasurementRecordExportLinkedContext, ...] = ()

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "selected record export request_id")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("selected record export approval_state is unsupported")
        identity = {
            "package_id": self.package_id,
            "display_name": self.display_name,
            "created_by": HANDOFF_PACKAGE_CREATED_BY,
            "source_export_summary_id": self.source_export_summary_id,
            "display_path": self.display_path,
            "local_path_redacted": True,
        }
        validate_handoff_package_identity(identity, display_path="required")
        validate_public_identifier(self.record_id, "selected record export record_id")
        validate_relative_path(self.record_dir, "selected record export record_dir")
        validate_relative_path(self.read_model_path, "selected record export read_model_path")
        if self.read_model_path != f"{self.record_dir}/record-read-model.json":
            raise ValueError("selected record export read_model_path must be record-local")
        if not isinstance(self.legacy_data_id, int) or isinstance(self.legacy_data_id, bool):
            raise ValueError("selected record export legacy_data_id must be an integer")
        if self.legacy_data_id < 0:
            raise ValueError("selected record export legacy_data_id must be non-negative")
        validate_public_identifier(self.target, "selected record export target")
        if not isinstance(self.declared_preview_metadata, dict):
            raise ValueError("selected record export declared_preview_metadata must be an object")
        validate_handoff_preview_ready_metadata(
            self.declared_preview_metadata,
            primary_path=f"measurements/{self.record_id}/primary.csv",
            owner="selected record export preview",
        )

    @property
    def approved(self) -> bool:
        return self.approval_state == "approved"

    @property
    def package_dir(self) -> str:
        return self.package_id

    @property
    def manifest_path(self) -> str:
        return f"{self.package_dir}/package-manifest.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approval_state": self.approval_state,
            "package_id": self.package_id,
            "display_name": self.display_name,
            "source_export_summary_id": self.source_export_summary_id,
            "display_path": self.display_path,
            "record_id": self.record_id,
            "record_dir": self.record_dir,
            "read_model_path": self.read_model_path,
            "legacy_data_id": self.legacy_data_id,
            "target": self.target,
            "declared_preview_metadata": copy.deepcopy(self.declared_preview_metadata),
            "linked_context": [
                item.to_writer_item(measurement_record_id=self.record_id)
                for item in self.linked_context
            ],
        }


@dataclass(frozen=True)
class SelectedMeasurementRecordExportRun:
    """Local review run for selected-record package export."""

    request: SelectedMeasurementRecordExportRequest
    storage_root: Path
    package_root: Path
    read_model: dict[str, Any] | None = None
    record_manifest: dict[str, Any] | None = None
    writer_receipt: dict[str, Any] | None = None
    package_write: HandoffPackageWriteReceipt | None = None
    export_error: str | None = None

    @property
    def exported(self) -> bool:
        return self.classification == "exported_selected_measurement_record"

    @property
    def classification(self) -> str:
        if self.export_error is not None:
            return "blocked_before_export"
        if not self.request.approved:
            return "blocked_before_export"
        return "exported_selected_measurement_record"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_selected_record_export_receipt",
            "selected_record_export_policy": copy.deepcopy(SELECTED_RECORD_EXPORT_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "validate_selected_record_export_request",
                    *([] if not self.request.approved else ["read_record_read_model"]),
                    *([] if self.record_manifest is None else ["read_record_creation_manifest"]),
                    *([] if self.writer_receipt is None else ["read_record_writer_receipt"]),
                    *([] if self.package_write is None else ["write_handoff_package"]),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "record": _record_ref(self.read_model, self.record_manifest, self.writer_receipt),
            "package_write": None if self.package_write is None else self.package_write.to_dict(),
            "export": {
                "performed": self.exported,
                "storage_root": str(self.storage_root),
                "package_root": str(self.package_root),
                "package_dir": self.request.package_dir if self.exported else None,
                "export_error": self.export_error,
            },
        }


def export_selected_measurement_record(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordExportRun:
    """Export one stored Measurement Record from a raw route-local source."""

    request = _parse_source(source)
    return export_selected_measurement_record_from_request(
        request,
        storage_root=storage_root,
        package_root=package_root,
    )


def export_selected_measurement_record_from_request(
    request: SelectedMeasurementRecordExportRequest,
    *,
    storage_root: str | Path,
    package_root: str | Path,
) -> SelectedMeasurementRecordExportRun:
    """Export one stored Measurement Record using existing package writer behavior."""

    storage = _existing_directory_root(Path(storage_root), "selected record export storage root")
    packages = _existing_directory_root(Path(package_root), "selected record export package root")
    if not request.approved:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
        )

    try:
        read_model = _read_read_model(storage, request)
        manifest = _read_json(
            storage, f"{request.record_dir}/record-manifest.json", "record manifest"
        )
        writer_receipt_path = _writer_receipt_path(read_model)
        writer_receipt = _read_json(storage, writer_receipt_path, "writer receipt")
        writer_source = _writer_source(request, read_model, manifest, writer_receipt)
        package_write = write_package(writer_source, source_root=storage, package_root=packages)
    except ValueError as exc:
        return SelectedMeasurementRecordExportRun(
            request=request,
            storage_root=storage,
            package_root=packages,
            export_error=str(exc),
        )

    return SelectedMeasurementRecordExportRun(
        request=request,
        storage_root=storage,
        package_root=packages,
        read_model=read_model,
        record_manifest=manifest,
        writer_receipt=writer_receipt,
        package_write=package_write,
    )


def _parse_source(source: dict[str, Any]) -> SelectedMeasurementRecordExportRequest:
    if source.get("selected_record_export_policy") != SELECTED_RECORD_EXPORT_POLICY:
        raise ValueError("selected record export policy is unsupported")
    request = _require_dict(source, "selected_record_export_request")
    linked_context = tuple(
        _parse_linked_context(item)
        for item in _optional_list(request, "linked_context", default=[])
    )
    return SelectedMeasurementRecordExportRequest(
        request_id=_require_text(request, "request_id"),
        approval_state=_require_text(request, "approval_state"),
        package_id=_require_text(request, "package_id"),
        display_name=_require_text(request, "display_name"),
        source_export_summary_id=_require_text(request, "source_export_summary_id"),
        display_path=_require_text(request, "display_path"),
        record_id=_require_text(request, "record_id"),
        record_dir=_require_text(request, "record_dir"),
        read_model_path=_require_text(request, "read_model_path"),
        legacy_data_id=_require_int(request, "legacy_data_id"),
        target=_require_text(request, "target"),
        declared_preview_metadata=_require_dict(request, "declared_preview_metadata"),
        linked_context=linked_context,
    )


def _parse_linked_context(item: Any) -> SelectedMeasurementRecordExportLinkedContext:
    item = _require_mapping(item, "selected record export linked_context item")
    context_reference = item.get("context_reference")
    if context_reference is not None:
        context_reference = _require_mapping(
            context_reference,
            "selected record export context_reference",
        )
    return SelectedMeasurementRecordExportLinkedContext(
        link_id=_require_text(item, "link_id"),
        kind=_require_text(item, "kind"),
        label=_require_text(item, "label"),
        relation=_require_text(item, "relation"),
        reason=_require_text(item, "reason"),
        context_reference=copy.deepcopy(context_reference),
    )


def _writer_source(
    request: SelectedMeasurementRecordExportRequest,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
) -> dict[str, Any]:
    record = _require_dict(manifest, "record")
    primary_data = _require_dict(read_model, "primary_data")
    primary_path = _require_text(primary_data, "path")
    validate_relative_path(primary_path, "selected record export primary data path")
    _validate_strict_child_path(
        primary_path,
        request.record_dir,
        "selected record export primary data path",
    )
    digest = _require_text(primary_data, "digest")
    size_bytes = _require_int(primary_data, "size_bytes")
    label = record.get("label") or request.record_id
    experiment_type = record.get("experiment_type") or "unspecified"
    validate_public_identifier(experiment_type, "selected record export experiment_type")
    _validate_record_continuity(request, read_model, manifest, writer_receipt)

    package_primary_path = f"measurements/{request.record_id}/primary.csv"
    primary = {
        "kind": "primary_data",
        "label": "Stored primary data",
        "source_path": primary_path,
        "expected_digest": digest,
        "expected_size_bytes": size_bytes,
        "package_path": package_primary_path,
        "include_status": "included_by_default",
        "relation": "selected_measurement_source",
        "authority": MANIFEST_AUTHORITY,
        "format": "csv_table",
        "package_state": "packaged",
        "reason": None,
    }
    return {
        "package_write_policy": {
            "write_authority": "approved_handoff_package_write_request",
            "source_authority": "caller_provided_source_root_plus_declared_relative_paths",
            "destination_authority": "caller_provided_package_root_plus_declared_package_paths",
            "package_format": "directory_manifest",
            "overwrite_behavior": "no_overwrite",
            "checksum_algorithm": "sha256",
            "primary_data_materialization": "copy_declared_primary_data",
            "linked_context_materialization": "declared_reference_or_payload",
            "archive_creation": "not_performed",
            "package_acceptance": "not_performed",
            "source_mutation": "not_performed",
            "schema_inference": "not_performed",
            "recursive_relation_traversal": "not_performed",
            "gui_workflow": "not_defined",
            "shared_measurement_schema": "not_defined",
        },
        "package_write_request": {
            "request_id": request.request_id,
            "approval_state": "approved",
            "package_dir": request.package_dir,
            "manifest_path": request.manifest_path,
            "collision_policy": "no_overwrite",
        },
        "package_identity": {
            "package_id": request.package_id,
            "display_name": request.display_name,
            "created_by": HANDOFF_PACKAGE_CREATED_BY,
            "source_export_summary_id": request.source_export_summary_id,
            "display_path": request.display_path,
            "local_path_redacted": True,
        },
        "selected_measurements": [
            {
                "measurement_record_id": request.record_id,
                "legacy_data_id": request.legacy_data_id,
                "label": label,
                "experiment_type": experiment_type,
                "target": request.target,
                "primary_data": primary,
                "declared_preview_metadata": copy.deepcopy(request.declared_preview_metadata),
                "default_bundle": [
                    {
                        "item_id": f"{request.record_id}-primary",
                        "kind": "primary_data",
                        "label": primary["label"],
                        "package_path": package_primary_path,
                        "include_status": "included_by_default",
                        "relation": "selected_measurement_source",
                        "authority": MANIFEST_AUTHORITY,
                        "package_state": "packaged",
                        "reason": None,
                    }
                ],
            }
        ],
        "linked_context": [
            item.to_writer_item(measurement_record_id=request.record_id)
            for item in request.linked_context
        ],
    }


def _validate_record_continuity(
    request: SelectedMeasurementRecordExportRequest,
    read_model: dict[str, Any],
    manifest: dict[str, Any],
    writer_receipt: dict[str, Any],
) -> None:
    read_model_record = _require_dict(read_model, "record")
    manifest_record = _require_dict(manifest, "record")
    writer_record = _require_dict(writer_receipt, "record")
    if read_model_record.get("record_id") != request.record_id:
        raise ValueError("selected record export read model record_id must match request")
    if read_model_record.get("record_dir") != request.record_dir:
        raise ValueError("selected record export read model record_dir must match request")
    if read_model_record.get("lifecycle_state") != "complete":
        raise ValueError("selected record export requires complete read model lifecycle")
    if manifest_record.get("record_id") != request.record_id:
        raise ValueError("selected record export manifest record_id must match request")
    if writer_record.get("record_id") != request.record_id:
        raise ValueError("selected record export writer receipt record_id must match request")
    if writer_record.get("record_dir") != request.record_dir:
        raise ValueError("selected record export writer receipt record_dir must match request")
    writer_primary = _require_dict(writer_receipt, "primary_data")
    model_primary = _require_dict(read_model, "primary_data")
    if writer_primary.get("path") != model_primary.get("path"):
        raise ValueError("selected record export primary data path must match writer receipt")
    if writer_primary.get("digest") != model_primary.get("digest"):
        raise ValueError("selected record export primary data digest must match writer receipt")
    if writer_primary.get("size_bytes") != model_primary.get("size_bytes"):
        raise ValueError("selected record export primary data size must match writer receipt")


def _read_read_model(root: Path, request: SelectedMeasurementRecordExportRequest) -> dict[str, Any]:
    read_model = _read_json(root, request.read_model_path, "record read model")
    if read_model.get("schema") != READ_MODEL_SCHEMA:
        raise ValueError("selected record export read model schema is unsupported")
    return read_model


def _writer_receipt_path(read_model: dict[str, Any]) -> str:
    sources = _require_dict(read_model, "sources")
    writer = _require_dict(sources, "writer_receipt")
    return _require_text(writer, "path")


def _record_ref(
    read_model: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    writer_receipt: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if read_model is None:
        return None
    record = _require_dict(read_model, "record")
    primary = _require_dict(read_model, "primary_data")
    result = {
        "record_id": record.get("record_id"),
        "record_dir": record.get("record_dir"),
        "lifecycle_state": record.get("lifecycle_state"),
        "primary_data_path": primary.get("path"),
        "primary_data_digest": primary.get("digest"),
        "primary_data_size_bytes": primary.get("size_bytes"),
    }
    if manifest is not None:
        manifest_record = _require_dict(manifest, "record")
        result["label"] = manifest_record.get("label")
        result["experiment_type"] = manifest_record.get("experiment_type")
    if writer_receipt is not None:
        writer_request = _require_dict(writer_receipt, "writer_request")
        result["writer_receipt_path"] = writer_request.get("writer_receipt_path")
    return result


def _read_json(root: Path, relative_path: str, label: str) -> dict[str, Any]:
    validate_relative_path(relative_path, f"selected record export {label}")
    _ensure_no_symlink_parents(root, relative_path, f"selected record export {label}")
    path = _path_under(root, relative_path, f"selected record export {label}")
    if path.is_symlink():
        raise ValueError(f"selected record export {label} must not be a symlink")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"selected record export {label} is required") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"selected record export {label} must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"selected record export {label} must be an object")
    return parsed


def _require_mapping(value: Any, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _require_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    return _require_mapping(source.get(key), key)


def _optional_list(source: dict[str, Any], key: str, *, default: list[Any]) -> list[Any]:
    value = source.get(key, default)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _require_text(source: dict[str, Any], key: str) -> str:
    return validate_text(source.get(key), key)


def _require_int(source: dict[str, Any], key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value
