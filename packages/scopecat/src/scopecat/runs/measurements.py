"""Measurement record loading helpers."""

from __future__ import annotations

from scopecat.kernel.errors import DataIntegrityError
from scopecat.kernel.problems import ProblemCategory
from scopecat.measurements.datasets import (
    MEASUREMENT_DATASET_KIND,
    assemble_measurement_dataset,
    measurement_records_error,
)
from scopecat.measurements.results import (
    MeasurementDataset,
    MeasurementDatasetReadContract,
    MeasurementRecord,
)
from scopecat.records.artifact import RunDatasetEntry
from scopecat.runs.access import dataset_storage_ref, require_dataset
from scopecat.runs.refs import dataset_content_ref
from scopecat.runs.repository import RunRepository

MEASUREMENT_DATASET_ID = "raw-measurements"
MEASUREMENT_DATA_REF = dataset_content_ref(
    dataset_id=MEASUREMENT_DATASET_ID,
    kind=MEASUREMENT_DATASET_KIND,
)


def read_measurement_records(
    *,
    storage: RunRepository,
    run_id: str,
    ref: str = MEASUREMENT_DATA_REF,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
) -> list[MeasurementRecord]:
    if not storage.exists(run_id, ref):
        raise measurement_records_error(
            missing_code,
            f"{noun} is missing: {ref}",
            ref=ref,
            category=ProblemCategory.NOT_FOUND,
        )
    try:
        records = storage.read_jsonl(run_id, ref, MeasurementRecord)
    except DataIntegrityError as error:
        raise measurement_records_error(
            invalid_code,
            f"{noun} is not valid measurement data: {ref}",
            ref=ref,
        ) from error
    if not records:
        raise measurement_records_error(
            empty_code,
            f"{noun} is empty: {ref}",
            ref=ref,
        )
    return records


def read_measurement_records_artifact(
    *,
    storage: RunRepository,
    run_id: str,
    selector: str = MEASUREMENT_DATASET_ID,
    missing_code: str,
    empty_code: str,
    invalid_code: str,
    noun: str,
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
    )


def read_measurement_dataset(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: RunDatasetEntry,
    contract: MeasurementDatasetReadContract,
) -> MeasurementDataset:
    ref = dataset_storage_ref(dataset)
    records = read_measurement_records(
        storage=storage,
        run_id=run_id,
        ref=ref,
        missing_code=contract.missing_code,
        empty_code=contract.empty_code,
        invalid_code=contract.invalid_code,
        noun=contract.noun,
    )
    return assemble_measurement_dataset(
        records=records,
        dataset_id=dataset.id,
        ref=ref,
        schema_data=dataset.data_schema,
        metadata=dataset.metadata,
        contract=contract,
    )


def read_measurement_dataset_artifact(
    *,
    storage: RunRepository,
    run_id: str,
    selector: str = MEASUREMENT_DATASET_ID,
    contract: MeasurementDatasetReadContract,
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
        contract=contract,
    )
