"""Measurement dataset storage codec.

The current backend is newline-delimited JSON records. Callers should go
through this module instead of depending on that representation directly.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from scopecat._storage.local.io import encode_model_json, ensure_durable_directory
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunDatasetEntry
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
    infer_measurement_dataset_schema,
    validate_measurement_records_against_schema,
)

MEASUREMENT_DATASET_KIND = "measurement_dataset"
MEASUREMENT_DATASET_MEDIA_TYPE = "application/x-ndjson"


def measurement_dataset_schema(
    *,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> MeasurementDatasetSchema:
    if expected_schema is None:
        return infer_measurement_dataset_schema(
            dataset_id=dataset_id,
            dataset_role=dataset_role,
            records=records,
            metadata=metadata,
        )
    if not metadata:
        return expected_schema
    return expected_schema.model_copy(
        update={"metadata": dict(expected_schema.metadata) | dict(metadata)}
    )


def validate_measurement_dataset_records(
    *,
    records: Sequence[MeasurementRecord],
    schema: MeasurementDatasetSchema | None,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
) -> list[Diagnostic]:
    if schema is None:
        return []
    return validate_measurement_records_against_schema(
        records=records,
        schema=schema,
        dataset_id=dataset_id,
        dataset_role=dataset_role,
    )


def measurement_dataset_entry(
    *,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None = None,
    media_type: str | None = MEASUREMENT_DATASET_MEDIA_TYPE,
    metadata: Mapping[str, JsonValue] | None = None,
) -> RunDatasetEntry:
    schema = measurement_dataset_schema(
        dataset_id=dataset_id,
        dataset_role=dataset_role,
        records=records,
        expected_schema=expected_schema,
        metadata=metadata,
    )
    return RunDatasetEntry(
        id=dataset_id,
        kind=MEASUREMENT_DATASET_KIND,
        media_type=media_type,
        role=dataset_role,
        schema=schema.model_dump(mode="json"),
        metadata=dict(metadata or {}),
    )


def write_measurement_records_path(
    *,
    path: Path,
    records: Sequence[MeasurementRecord],
) -> None:
    ensure_durable_directory(path.parent)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary_path.open("w") as data_file:
            for record in records:
                data_file.write(encode_model_json(record) + "\n")
            data_file.flush()
            os.fsync(data_file.fileno())
        temporary_path.replace(path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def read_measurement_records_path(
    *,
    path: Path,
    ref: str,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
    diagnostic_path: str,
) -> list[MeasurementRecord]:
    if not path.is_file():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    missing_code,
                    f"{noun} is missing: {ref}",
                    diagnostic_path,
                )
            ]
        )

    lines = [line for line in path.read_text().splitlines() if line.strip()]
    if not lines:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    empty_code,
                    f"{noun} is empty: {ref}",
                    diagnostic_path,
                )
            ]
        )

    measurements: list[MeasurementRecord] = []
    for index, line in enumerate(lines, start=1):
        try:
            json.loads(line)
            measurements.append(MeasurementRecord.model_validate_json(line))
        except (json.JSONDecodeError, ValidationError) as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        invalid_code,
                        f"{noun} line {index} is not a valid measurement record",
                        diagnostic_path,
                    )
                ]
            ) from error
    return measurements


def read_measurement_dataset_path(
    *,
    path: Path,
    dataset_id: str,
    ref: str,
    schema_data: dict[str, object] | None,
    metadata: Mapping[str, object],
    diagnostics: MeasurementDatasetInputDiagnostics,
) -> MeasurementDataset:
    diagnostic_path = diagnostics.diagnostic_path or ref
    records = read_measurement_records_path(
        path=path,
        ref=ref,
        missing_code=diagnostics.missing_code,
        empty_code=diagnostics.empty_code,
        invalid_code=diagnostics.invalid_code,
        noun=diagnostics.noun,
        diagnostic_path=diagnostic_path,
    )
    if schema_data is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    diagnostics.missing_schema_code,
                    f"{diagnostics.noun} ref is missing schema: {ref}",
                    diagnostic_path,
                )
            ]
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(schema_data)
    except ValidationError as error:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        ) from error

    if schema.dataset_id != dataset_id:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )

    row_diagnostics = validate_measurement_dataset_records(
        records=records,
        schema=schema,
        dataset_id=dataset_id,
        dataset_role=schema.dataset_role,
    )
    if row_diagnostics:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )

    try:
        return MeasurementDataset.model_validate(
            {
                "dataset_id": dataset_id,
                "schema": schema,
                "records": records,
                "metadata": dict(metadata),
            }
        )
    except ValidationError as error:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        ) from error


def _invalid_dataset_schema(
    *,
    diagnostics: MeasurementDatasetInputDiagnostics,
    ref: str,
    diagnostic_path: str,
) -> ValidationFailed:
    return ValidationFailed(
        [
            _diagnostic(
                "error",
                diagnostics.invalid_schema_code,
                f"{diagnostics.noun} dataset_schema is invalid: {ref}",
                diagnostic_path,
            )
        ]
    )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "MEASUREMENT_DATASET_KIND",
    "MEASUREMENT_DATASET_MEDIA_TYPE",
    "measurement_dataset_entry",
    "measurement_dataset_schema",
    "read_measurement_dataset_path",
    "read_measurement_records_path",
    "validate_measurement_dataset_records",
    "write_measurement_records_path",
]
