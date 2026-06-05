"""Internal primary-data commit artifact construction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from scopecat.measurement_records._contracts import (
    FINALIZATION_RECEIPT_SCHEMA,
    MANIFEST_SCHEMA,
    WRITER_RECEIPT_SCHEMA,
)
from scopecat.measurement_records._storage import sha256
from scopecat.measurement_records.read_model_shared import READ_MODEL_SCHEMA


class PrimaryDataCommitSource(Protocol):
    declared_digest: str
    rows_recorded: int
    primary_data_format: str

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PrimaryDataCommitArtifacts:
    writer_receipt_content: bytes
    finalization_receipt_content: bytes
    read_model_content: bytes
    primary_digest: str
    read_model_digest: str


def build_primary_data_commit_artifacts(
    *,
    request_id: str,
    record_id: str,
    record_dir: str,
    creation_manifest_path: str,
    primary_data_path: str,
    writer_receipt_path: str,
    finalization_receipt_path: str,
    manifest: dict[str, Any],
    import_source: PrimaryDataCommitSource,
    primary_content: bytes,
    table: dict[str, Any],
) -> PrimaryDataCommitArtifacts:
    """Build shared writer, finalization, and read-model artifacts."""

    record = _require_dict(manifest, "record")
    primary_digest = sha256(primary_content)
    writer_receipt_content = _json_bytes(
        _writer_receipt(
            request_id=request_id,
            record_id=record_id,
            record_dir=record_dir,
            creation_manifest_path=creation_manifest_path,
            primary_data_path=primary_data_path,
            writer_receipt_path=writer_receipt_path,
            creation_lifecycle_state=record["lifecycle_state"],
            import_source=import_source,
            primary_content=primary_content,
        )
    )
    finalization_receipt_content = _json_bytes(
        _finalization_receipt(
            request_id=request_id,
            record_id=record_id,
            record_dir=record_dir,
            creation_manifest_path=creation_manifest_path,
            writer_receipt_path=writer_receipt_path,
            primary_data_path=primary_data_path,
            import_source=import_source,
            primary_digest=primary_digest,
            table=table,
        )
    )
    read_model_content = _json_bytes(
        _read_model(
            record_id=record_id,
            record_dir=record_dir,
            creation_manifest_path=creation_manifest_path,
            writer_receipt_path=writer_receipt_path,
            finalization_receipt_path=finalization_receipt_path,
            primary_data_path=primary_data_path,
            creation_lifecycle_state=record["lifecycle_state"],
            manifest_digest=sha256(_json_bytes(manifest)),
            writer_receipt_digest=sha256(writer_receipt_content),
            finalization_receipt_digest=sha256(finalization_receipt_content),
            import_source=import_source,
            primary_size=len(primary_content),
            table=table,
        )
    )
    return PrimaryDataCommitArtifacts(
        writer_receipt_content=writer_receipt_content,
        finalization_receipt_content=finalization_receipt_content,
        read_model_content=read_model_content,
        primary_digest=primary_digest,
        read_model_digest=sha256(read_model_content),
    )


def _writer_receipt(
    *,
    request_id: str,
    record_id: str,
    record_dir: str,
    creation_manifest_path: str,
    primary_data_path: str,
    writer_receipt_path: str,
    creation_lifecycle_state: str,
    import_source: PrimaryDataCommitSource,
    primary_content: bytes,
) -> dict[str, Any]:
    return {
        "schema": WRITER_RECEIPT_SCHEMA,
        "record": {
            "record_id": record_id,
            "record_dir": record_dir,
            "creation_manifest_path": creation_manifest_path,
            "creation_lifecycle_state": creation_lifecycle_state,
        },
        "writer_request": {
            "request_id": f"{request_id}-write",
            "primary_data_path": primary_data_path,
            "writer_receipt_path": writer_receipt_path,
            "primary_data_format": import_source.primary_data_format,
            "expected_rows": import_source.rows_recorded,
        },
        "primary_data": {
            "path": primary_data_path,
            "format": import_source.primary_data_format,
            "digest": sha256(primary_content),
            "size_bytes": len(primary_content),
            "rows_recorded": import_source.rows_recorded,
        },
        "source": import_source.to_dict(),
    }


def _finalization_receipt(
    *,
    request_id: str,
    record_id: str,
    record_dir: str,
    creation_manifest_path: str,
    writer_receipt_path: str,
    primary_data_path: str,
    import_source: PrimaryDataCommitSource,
    primary_digest: str,
    table: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": FINALIZATION_RECEIPT_SCHEMA,
        "record": {
            "record_id": record_id,
            "record_dir": record_dir,
            "creation_manifest_path": creation_manifest_path,
            "writer_receipt_path": writer_receipt_path,
        },
        "finalization": {
            "request_id": f"{request_id}-finalize",
            "final_state": "complete",
            "operator_reason": None,
            "evidence": {
                "primary_table_classification": table["classification"],
                "primary_data_path": primary_data_path,
                "primary_data_digest": primary_digest,
                "rows_recorded": import_source.rows_recorded,
                "table_row_count": table["row_count"],
            },
        },
    }


def _read_model(
    *,
    record_id: str,
    record_dir: str,
    creation_manifest_path: str,
    writer_receipt_path: str,
    finalization_receipt_path: str,
    primary_data_path: str,
    creation_lifecycle_state: str,
    manifest_digest: str,
    writer_receipt_digest: str,
    finalization_receipt_digest: str,
    import_source: PrimaryDataCommitSource,
    primary_size: int,
    table: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": READ_MODEL_SCHEMA,
        "record": {
            "record_id": record_id,
            "record_dir": record_dir,
            "lifecycle_state": "complete",
            "creation_lifecycle_state": creation_lifecycle_state,
        },
        "sources": {
            "creation_manifest": {
                "path": creation_manifest_path,
                "schema": MANIFEST_SCHEMA,
                "digest": manifest_digest,
            },
            "writer_receipt": {
                "path": writer_receipt_path,
                "schema": WRITER_RECEIPT_SCHEMA,
                "digest": writer_receipt_digest,
            },
            "finalization_receipt": {
                "path": finalization_receipt_path,
                "schema": FINALIZATION_RECEIPT_SCHEMA,
                "digest": finalization_receipt_digest,
            },
            "primary_table_read": {
                "classification": table["classification"],
            },
        },
        "primary_data": {
            "path": primary_data_path,
            "format": table["format"],
            "digest": import_source.declared_digest,
            "size_bytes": primary_size,
            "declared_row_count": import_source.rows_recorded,
            "observed_row_count": table["row_count"],
        },
        "table": {
            "classification": table["classification"],
            "columns": table["columns"],
            "preview": table["preview"],
        },
        "review": {
            "findings": [],
        },
        "finalization": {
            "final_state": "complete",
            "operator_reason": None,
        },
    }


def _json_bytes(content: dict[str, Any]) -> bytes:
    return (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise ValueError(f"{field} must be an object")
    return item
