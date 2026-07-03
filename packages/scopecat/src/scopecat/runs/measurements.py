"""Measurement record loading helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scopecat._storage import ARTIFACTS_DIR
from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementDatasetSchema,
    MeasurementRecord,
    validate_measurement_records_against_schema,
)
from scopecat.runs.access import require_artifact

RAW_MEASUREMENTS_FILENAME = "raw-measurements.jsonl"
MEASUREMENT_DATA_REF = f"{ARTIFACTS_DIR}/{RAW_MEASUREMENTS_FILENAME}"


def read_measurement_records(
    *,
    storage: LocalRunStore,
    run_id: str,
    ref: str = MEASUREMENT_DATA_REF,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
    diagnostic_path: str | None = None,
) -> list[MeasurementRecord]:
    path = storage.ref_path(run_id, ref)
    return read_measurement_records_path(
        path=path,
        ref=ref,
        missing_code=missing_code,
        empty_code=empty_code,
        invalid_code=invalid_code,
        noun=noun,
        diagnostic_path=diagnostic_path or ref,
    )


def read_measurement_records_artifact(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str = MEASUREMENT_DATA_REF,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
    diagnostic_path: str | None = None,
) -> list[MeasurementRecord]:
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="measurement_dataset",
    )
    return read_measurement_records(
        storage=storage,
        run_id=run_id,
        ref=artifact.path,
        missing_code=missing_code,
        empty_code=empty_code,
        invalid_code=invalid_code,
        noun=noun,
        diagnostic_path=diagnostic_path,
    )


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


def read_measurement_dataset(
    *,
    storage: LocalRunStore,
    run_id: str,
    artifact: Artifact,
    diagnostics: MeasurementDatasetInputDiagnostics,
) -> MeasurementDataset:
    return read_measurement_dataset_path(
        path=storage.ref_path(run_id, artifact.path),
        artifact_id=artifact.id,
        ref=artifact.path,
        metadata=artifact.metadata,
        diagnostics=diagnostics,
    )


def read_measurement_dataset_artifact(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str = MEASUREMENT_DATA_REF,
    diagnostics: MeasurementDatasetInputDiagnostics,
) -> MeasurementDataset:
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="measurement_dataset",
    )
    return read_measurement_dataset(
        storage=storage,
        run_id=run_id,
        artifact=artifact,
        diagnostics=diagnostics,
    )


def read_measurement_dataset_path(
    *,
    path: Path,
    artifact_id: str,
    ref: str,
    metadata: dict[str, Any],
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
    schema_data = metadata.get("dataset_schema")
    if schema_data is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    diagnostics.missing_schema_code,
                    f"{diagnostics.noun} metadata is missing dataset_schema: {ref}",
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

    if schema.dataset_id != artifact_id:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )
    if metadata.get("dataset_role") != schema.dataset_role:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )
    if metadata.get("record_schema") != schema.record_schema:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )

    row_diagnostics = validate_measurement_records_against_schema(
        records=records,
        schema=schema,
        dataset_id=artifact_id,
        dataset_role=schema.dataset_role,
    )
    if row_diagnostics:
        raise _invalid_dataset_schema(
            diagnostics=diagnostics,
            ref=ref,
            diagnostic_path=diagnostic_path,
        )

    return MeasurementDataset(
        artifact_id=artifact_id,
        ref=ref,
        schema=schema,
        records=records,
        metadata=dict(metadata),
    )


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
