"""Measurement record loading helpers."""

from __future__ import annotations

from pathlib import Path

from scopecat._measurement_storage import (
    MEASUREMENT_DATASET_KIND,
)
from scopecat._measurement_storage import (
    read_measurement_dataset_path as _read_measurement_dataset_path,
)
from scopecat._measurement_storage import (
    read_measurement_records_path as _read_measurement_records_path,
)
from scopecat._storage.local import LocalRunStore
from scopecat._storage.refs import dataset_content_ref
from scopecat.models.artifact import RunDatasetEntry
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementRecord,
)
from scopecat.runs.access import dataset_storage_ref, require_dataset

MEASUREMENT_DATASET_ID = "raw-measurements"
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
    return _read_measurement_records_path(
        path=path,
        ref=ref,
        missing_code=missing_code,
        empty_code=empty_code,
        invalid_code=invalid_code,
        noun=noun,
        diagnostic_path=diagnostic_path,
    )


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
    return _read_measurement_dataset_path(
        path=path,
        dataset_id=dataset_id,
        ref=ref,
        schema_data=schema_data,
        metadata=metadata,
        diagnostics=diagnostics,
    )
