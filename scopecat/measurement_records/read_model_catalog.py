"""Read-only catalog over projected measurement-record read models."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.measurement_records.creation import (
    validate_public_identifier,
    validate_relative_path,
    validate_text,
)
from scopecat.measurement_records.read_model_projection import READ_MODEL_SCHEMA

READ_MODEL_CATALOG_SCHEMA = "scopecat.measurement_record_read_model_catalog.v0"
READ_MODEL_CATALOG_POLICY = {
    "catalog_authority": "record_local_projected_read_models",
    "record_authority": "derived_read_model_not_canonical_storage",
    "source_consistency_check": "declared_source_digests_only",
    "primary_data_revalidation": "not_performed",
    "storage_mutation": "not_performed",
    "read_model_refresh": "not_performed",
    "manifest_replacement": "not_performed",
    "final_storage_schema": "not_defined",
}
DOES_NOT_CLAIM = [
    "canonical_storage_authority",
    "manifest_replacement",
    "read_model_refresh",
    "stale_read_model_repair",
    "primary_data_revalidation",
    "conflict_resolution",
    "crash_recovery",
    "database_index",
    "public_export_schema",
    "gui_review_state",
]
LIFECYCLE_STATES = {"complete", "failed"}
SOURCE_KINDS = ("creation_manifest", "writer_receipt", "finalization_receipt")


@dataclass(frozen=True)
class MeasurementRecordCatalogRequest:
    """Request to scan projected measurement-record read models."""

    request_id: str
    records_dir: str = "records"
    verify_source_digests: bool = True

    def __post_init__(self) -> None:
        validate_public_identifier(self.request_id, "catalog request request_id")
        validate_relative_path(self.records_dir, "catalog request records_dir")
        if not isinstance(self.verify_source_digests, bool):
            raise ValueError("catalog request verify_source_digests must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "records_dir": self.records_dir,
            "verify_source_digests": self.verify_source_digests,
        }


@dataclass(frozen=True)
class MeasurementRecordCatalogRun:
    """Read-only catalog result for projected measurement records."""

    request: MeasurementRecordCatalogRequest
    storage_root: Path
    entries: tuple[dict[str, Any], ...] = ()
    review_findings: tuple[dict[str, str], ...] = ()

    @property
    def classification(self) -> str:
        if self.review_findings:
            return "read_model_catalog_review_needed"
        return "read_model_catalog_ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_record_read_model_catalog",
            "read_model_catalog_policy": copy.deepcopy(READ_MODEL_CATALOG_POLICY),
            "workflow": {
                "classification": self.classification,
                "steps": [
                    "scan_records_dir",
                    "read_record_read_models",
                    *(
                        ["verify_declared_source_digests"]
                        if self.request.verify_source_digests
                        else []
                    ),
                ],
                "does_not_claim": list(DOES_NOT_CLAIM),
            },
            "request": self.request.to_dict(),
            "storage_root": str(self.storage_root),
            "entries": [copy.deepcopy(entry) for entry in self.entries],
            "review_findings": [copy.deepcopy(finding) for finding in self.review_findings],
        }


def catalog_measurement_record_read_models(
    source: dict[str, Any],
    *,
    storage_root: str | Path,
) -> MeasurementRecordCatalogRun:
    """Scan projected read models from a raw catalog source."""

    request = _parse_source(source)
    return catalog_measurement_record_read_models_from_request(
        request,
        storage_root=storage_root,
    )


def catalog_measurement_record_read_models_from_request(
    request: MeasurementRecordCatalogRequest,
    *,
    storage_root: str | Path,
) -> MeasurementRecordCatalogRun:
    """Scan projected read models from a typed catalog request."""

    root = _existing_directory_root(Path(storage_root), "read model catalog storage root")
    records_path = _path_under(root, request.records_dir)
    _ensure_no_symlink_parents(root, request.records_dir, "read model catalog records dir")
    if records_path.is_symlink():
        raise ValueError("read model catalog records dir must not be a symlink")
    if not records_path.exists():
        return MeasurementRecordCatalogRun(request=request, storage_root=root)
    if not records_path.is_dir():
        raise ValueError("read model catalog records dir must be a directory")

    entries: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    for record_path in sorted(records_path.iterdir(), key=lambda item: item.name):
        record_rel = _relative_to_root(root, record_path)
        if record_path.is_symlink():
            findings.append(
                _finding(
                    "record_dir_symlink_ignored",
                    record_rel,
                    "Record directory candidate is a symlink.",
                )
            )
            continue
        if not record_path.is_dir():
            findings.append(
                _finding(
                    "non_record_entry_ignored",
                    record_rel,
                    "Records directory contains a non-directory entry.",
                )
            )
            continue
        entry, entry_findings = _catalog_record_dir(
            root,
            record_rel,
            request.verify_source_digests,
        )
        if entry is not None:
            entries.append(entry)
        findings.extend(entry_findings)

    return MeasurementRecordCatalogRun(
        request=request,
        storage_root=root,
        entries=tuple(entries),
        review_findings=tuple(findings),
    )


def _parse_source(source: dict[str, Any]) -> MeasurementRecordCatalogRequest:
    if source.get("read_model_catalog_schema") != READ_MODEL_CATALOG_SCHEMA:
        raise ValueError(f"read model catalog source schema must be {READ_MODEL_CATALOG_SCHEMA}")
    if source.get("read_model_catalog_policy") != READ_MODEL_CATALOG_POLICY:
        raise ValueError("read model catalog source policy is unsupported")
    request = _require_dict(source, "catalog_request")
    return MeasurementRecordCatalogRequest(
        request_id=_require_text(request, "request_id"),
        records_dir=_optional_text(request, "records_dir", default="records"),
        verify_source_digests=_optional_bool(
            request,
            "verify_source_digests",
            default=True,
        ),
    )


def _catalog_record_dir(
    root: Path,
    record_dir: str,
    verify_source_digests: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    read_model_path = f"{record_dir}/record-read-model.json"
    target = _path_under(root, read_model_path)
    if target.is_symlink():
        return (
            None,
            [
                _finding(
                    "read_model_symlink_ignored",
                    read_model_path,
                    "Projected read model is a symlink.",
                )
            ],
        )
    if not target.exists():
        return (
            None,
            [
                _finding(
                    "read_model_missing",
                    read_model_path,
                    "Record directory has no projected read model.",
                )
            ],
        )

    try:
        content = target.read_bytes()
        model = _parse_read_model(content)
        entry = _entry_from_read_model(model, read_model_path, _sha256(content), len(content))
        _validate_entry_against_scan(entry, model, record_dir, read_model_path)
    except ValueError as exc:
        return (
            None,
            [
                _finding(
                    "read_model_invalid",
                    read_model_path,
                    str(exc),
                )
            ],
        )

    findings = []
    if verify_source_digests:
        findings.extend(_source_digest_findings(root, model, record_dir))
    return entry, findings


def _parse_read_model(content: bytes) -> dict[str, Any]:
    try:
        model = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Projected read model must be utf-8 JSON.") from exc
    if not isinstance(model, dict):
        raise ValueError("Projected read model must be a JSON object.")
    if model.get("schema") != READ_MODEL_SCHEMA:
        raise ValueError("Projected read model schema is unsupported.")
    return model


def _entry_from_read_model(
    model: dict[str, Any],
    read_model_path: str,
    read_model_digest: str,
    read_model_size_bytes: int,
) -> dict[str, Any]:
    record = _require_dict(model, "record")
    sources = _require_dict(model, "sources")
    primary_data = _require_dict(model, "primary_data")
    table = _require_dict(model, "table")
    finalization = _require_dict(model, "finalization")
    review = _require_dict(model, "review")

    record_id = validate_public_identifier(record.get("record_id"), "read model record_id")
    record_dir = validate_relative_path(record.get("record_dir"), "read model record_dir")
    lifecycle_state = validate_text(record.get("lifecycle_state"), "read model lifecycle_state")
    if lifecycle_state not in LIFECYCLE_STATES:
        raise ValueError("Projected read model lifecycle state is unsupported.")
    final_state = validate_text(finalization.get("final_state"), "read model final_state")
    if final_state != lifecycle_state:
        raise ValueError("Projected read model lifecycle state must match finalization.")
    if final_state == "failed":
        validate_text(finalization.get("operator_reason"), "read model finalization reason")

    primary_path = validate_relative_path(primary_data.get("path"), "read model primary_data path")
    _validate_strict_child_path(primary_path, record_dir, "read model primary_data path")
    primary_digest = _validate_sha256_digest(
        primary_data.get("digest"),
        "read model primary_data digest",
    )
    declared_row_count = _validate_non_negative_integer(
        primary_data.get("declared_row_count"),
        "read model primary_data declared_row_count",
    )
    observed_row_count = _validate_non_negative_integer(
        primary_data.get("observed_row_count"),
        "read model primary_data observed_row_count",
    )
    _validate_non_negative_integer(
        primary_data.get("size_bytes"),
        "read model primary_data size_bytes",
    )
    columns = _require_list(table, "columns")
    preview = _require_dict(table, "preview")
    review_findings = _require_list(review, "findings")

    source_entries = {}
    for kind in SOURCE_KINDS:
        source = _require_dict(sources, kind)
        source_path = validate_relative_path(source.get("path"), f"read model {kind} path")
        _validate_strict_child_path(source_path, record_dir, f"read model {kind} path")
        source_entries[kind] = {
            "path": source_path,
            "schema": validate_text(source.get("schema"), f"read model {kind} schema"),
            "digest": _validate_sha256_digest(
                source.get("digest"),
                f"read model {kind} digest",
            ),
        }

    return {
        "record_id": record_id,
        "record_dir": record_dir,
        "lifecycle_state": lifecycle_state,
        "read_model": {
            "path": read_model_path,
            "digest": read_model_digest,
            "size_bytes": read_model_size_bytes,
        },
        "primary_data": {
            "path": primary_path,
            "format": validate_text(primary_data.get("format"), "read model primary_data format"),
            "digest": primary_digest,
            "declared_row_count": declared_row_count,
            "observed_row_count": observed_row_count,
        },
        "table": {
            "classification": validate_text(
                table.get("classification"),
                "read model table classification",
            ),
            "column_count": len(columns),
            "preview_row_count": len(_require_list(preview, "rows")),
        },
        "finalization": {
            "final_state": final_state,
            "operator_reason": finalization.get("operator_reason"),
        },
        "sources": source_entries,
        "review_finding_count": len(review_findings),
    }


def _validate_entry_against_scan(
    entry: dict[str, Any],
    model: dict[str, Any],
    scanned_record_dir: str,
    read_model_path: str,
) -> None:
    if entry["record_dir"] != scanned_record_dir:
        raise ValueError("Projected read model record_dir conflicts with scanned directory.")
    projection = _require_dict(model, "projection")
    if projection.get("read_model_path") != read_model_path:
        raise ValueError("Projected read model path conflicts with scanned file.")
    policy = _require_dict(model, "read_model_policy")
    if policy.get("canonical_storage_authority") != "not_claimed":
        raise ValueError("Projected read model claims canonical storage authority.")
    if policy.get("refresh") != "not_performed":
        raise ValueError("Projected read model claims refresh behavior.")


def _source_digest_findings(
    root: Path,
    model: dict[str, Any],
    record_dir: str,
) -> list[dict[str, str]]:
    findings = []
    sources = _require_dict(model, "sources")
    for kind in SOURCE_KINDS:
        source = _require_dict(sources, kind)
        path = validate_relative_path(source.get("path"), f"read model {kind} path")
        _validate_strict_child_path(path, record_dir, f"read model {kind} path")
        target = _path_under(root, path)
        if target.is_symlink():
            findings.append(
                _finding(
                    "read_model_source_symlink",
                    path,
                    f"Projected read model {kind} source is a symlink.",
                )
            )
            continue
        try:
            content = target.read_bytes()
        except FileNotFoundError:
            findings.append(
                _finding(
                    "read_model_source_missing",
                    path,
                    f"Projected read model {kind} source is missing.",
                )
            )
            continue
        actual_digest = _sha256(content)
        if actual_digest != source["digest"]:
            findings.append(
                _finding(
                    "read_model_source_digest_mismatch",
                    path,
                    f"Projected read model {kind} source digest does not match.",
                )
            )
    return findings


def _finding(code: str, target: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "review",
        "target": target,
        "message": message,
        "does_not_claim": "read_model_refresh_or_repair",
    }


def _existing_directory_root(root: Path, owner: str) -> Path:
    if root.is_symlink():
        raise ValueError(f"{owner} must not be a symlink")
    if not root.is_dir():
        raise ValueError(f"{owner} must be an existing directory")
    return root.resolve()


def _path_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(
        *Path(validate_relative_path(relative_path, "read model catalog path")).parts
    )


def _relative_to_root(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


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


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item


def _require_list(value: dict[str, Any], field: str) -> list[Any]:
    item = value.get(field)
    if not isinstance(item, list):
        raise ValueError(f"{field} must be a list")
    return item


def _require_text(value: dict[str, Any], field: str) -> str:
    return validate_text(value.get(field), field)


def _optional_text(value: dict[str, Any], field: str, *, default: str) -> str:
    if field not in value:
        return default
    return validate_text(value[field], field)


def _optional_bool(value: dict[str, Any], field: str, *, default: bool) -> bool:
    if field not in value:
        return default
    if not isinstance(value[field], bool):
        raise ValueError(f"{field} must be boolean")
    return value[field]
