"""Measurement record loading helpers."""

from __future__ import annotations

from pydantic import ValidationError

from scopecat.kernel.errors import DataIntegrityError, NotFound
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    StorageLocation,
    problem,
)
from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementRecord,
)
from scopecat.runs.access import dataset_storage_ref
from scopecat.runs.repository import RunRepository


def _read_measurement_records(
    *, storage: RunRepository, run_id: str, ref: str
) -> list[MeasurementRecord]:
    if not storage.exists(run_id, ref):
        raise _not_found(
            "run.measurement_dataset.missing",
            f"run measurement dataset is missing: {ref}",
            ref=ref,
        )
    try:
        records = storage.read_measurement_records(run_id, ref)
    except DataIntegrityError as error:
        raise _integrity_error(
            "run.measurement_dataset.invalid",
            f"run measurement dataset is not valid measurement data: {ref}",
            ref=ref,
        ) from error
    return records


def read_measurement_dataset(
    *,
    storage: RunRepository,
    run_id: str,
    dataset: RunContentEntry,
) -> MeasurementDataset:
    ref = dataset_storage_ref(dataset)
    records = _read_measurement_records(storage=storage, run_id=run_id, ref=ref)
    if dataset.data_schema is None:
        raise _integrity_error(
            "run.measurement_dataset.schema_missing",
            f"run measurement dataset ref is missing schema: {ref}",
            ref=ref,
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(dataset.data_schema)
    except ValidationError as error:
        raise _invalid_schema(ref) from error
    if validate_measurement_records_against_schema(
        records,
        schema,
        dataset.id,
        allow_partial=dataset.metadata.get("partial") is True,
    ):
        raise _invalid_schema(ref)
    return MeasurementDataset(
        dataset_schema=schema,
        records=records,
        metadata=dataset.metadata,
    )


def _invalid_schema(ref: str) -> DataIntegrityError:
    return _integrity_error(
        "run.measurement_dataset.schema_invalid",
        f"run measurement dataset schema is invalid: {ref}",
        ref=ref,
    )


def _integrity_error(code: str, message: str, *, ref: str) -> DataIntegrityError:
    return DataIntegrityError((_problem(code, message, ref=ref),))


def _not_found(code: str, message: str, *, ref: str) -> NotFound:
    return NotFound((_problem(code, message, ref=ref),))


def _problem(code: str, message: str, *, ref: str) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.PERSISTENCE,
        location=StorageLocation(ref=ref),
    )
