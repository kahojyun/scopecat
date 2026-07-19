"""Measurement record loading helpers."""

from __future__ import annotations

from scopecat.kernel.errors import DataIntegrityError
from scopecat.kernel.problems import ProblemCategory
from scopecat.measurements.datasets import (
    assemble_measurement_dataset,
    measurement_records_error,
)
from scopecat.measurements.results import (
    MeasurementDataset,
    MeasurementDatasetReadContract,
    MeasurementRecord,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.runs.access import dataset_storage_ref
from scopecat.runs.repository import RunRepository


def read_measurement_records(
    *,
    storage: RunRepository,
    run_id: str,
    ref: str,
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
        records = storage.read_measurement_records(run_id, ref)
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


def read_measurement_dataset(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: RunContentEntry,
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
