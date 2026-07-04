"""Measurement record loading helpers."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from scopecat._storage.local import LocalRunStore
from scopecat._storage.refs import dataset_content_ref
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunDatasetEntry
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementDatasetSchema,
    MeasurementRecord,
    validate_measurement_records_against_schema,
)
from scopecat.runs.access import dataset_storage_ref, require_dataset

MEASUREMENT_DATASET_ID = "raw-measurements"
MEASUREMENT_DATASET_KIND = "measurement_dataset"
MEASUREMENT_DATA_REF = dataset_content_ref(
    dataset_id=MEASUREMENT_DATASET_ID,
    kind=MEASUREMENT_DATASET_KIND,
)


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
    selector: str = MEASUREMENT_DATASET_ID,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
    diagnostic_path: str | None = None,
) -> list[MeasurementRecord]:
    dataset = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=MEASUREMENT_DATASET_KIND,
    )
    return read_measurement_records(
        storage=storage,
        run_id=run_id,
        ref=dataset_storage_ref(dataset),
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
    dataset: RunDatasetEntry,
    diagnostics: MeasurementDatasetInputDiagnostics,
) -> MeasurementDataset:
    return read_measurement_dataset_path(
        path=storage.ref_path(run_id, dataset_storage_ref(dataset)),
        dataset_id=dataset.id,
        ref=dataset_storage_ref(dataset),
        schema_data=dataset.data_schema,
        metadata=dataset.metadata,
        diagnostics=diagnostics,
    )


def read_measurement_dataset_artifact(
    *,
    storage: LocalRunStore,
    run_id: str,
    selector: str = MEASUREMENT_DATASET_ID,
    diagnostics: MeasurementDatasetInputDiagnostics,
) -> MeasurementDataset:
    dataset = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=MEASUREMENT_DATASET_KIND,
    )
    return read_measurement_dataset(
        storage=storage,
        run_id=run_id,
        dataset=dataset,
        diagnostics=diagnostics,
    )


def read_measurement_dataset_path(
    *,
    path: Path,
    dataset_id: str,
    ref: str,
    schema_data: dict[str, object] | None,
    metadata: dict[str, object],
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

    row_diagnostics = validate_measurement_records_against_schema(
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

    return MeasurementDataset(
        dataset_id=dataset_id,
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
