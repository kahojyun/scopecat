"""Measurement dataset storage codec.

The current backend is newline-delimited JSON records. Callers should go
through this module instead of depending on that representation directly.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from scopecat._storage.local.io import encode_model_json, ensure_durable_directory
from scopecat.errors import DataIntegrityError, NotFound, StorageError
from scopecat.models.artifact import RunDatasetEntry
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.results import (
    MeasurementDataset,
    MeasurementDatasetReadContract,
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
) -> list[Problem]:
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
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        ensure_durable_directory(path.parent)
        with temporary_path.open("w") as data_file:
            for record in records:
                data_file.write(encode_model_json(record) + "\n")
            data_file.flush()
            os.fsync(data_file.fileno())
        temporary_path.replace(path)
        _fsync_directory(path.parent)
    except OSError as error:
        raise StorageError(
            [
                _storage_problem(
                    "measurement_records_write_failed",
                    "measurement records could not be written durably",
                    ref=str(path),
                )
            ]
        ) from error
    finally:
        with suppress(OSError):
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
) -> list[MeasurementRecord]:
    try:
        content = path.read_text()
    except FileNotFoundError as error:
        raise NotFound(
            [
                _storage_problem(
                    missing_code,
                    f"{noun} is missing: {ref}",
                    ref=ref,
                    category=ProblemCategory.NOT_FOUND,
                )
            ]
        ) from error
    except IsADirectoryError as error:
        raise DataIntegrityError(
            [
                _storage_problem(
                    invalid_code,
                    f"{noun} is not a readable file: {ref}",
                    ref=ref,
                    category=ProblemCategory.DATA_INTEGRITY,
                )
            ]
        ) from error
    except OSError as error:
        raise StorageError(
            [
                _storage_problem(
                    "measurement_records_read_failed",
                    f"{noun} could not be read",
                    ref=ref,
                )
            ]
        ) from error
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        raise DataIntegrityError(
            [
                _storage_problem(
                    empty_code,
                    f"{noun} is empty: {ref}",
                    ref=ref,
                    category=ProblemCategory.DATA_INTEGRITY,
                )
            ]
        )

    measurements: list[MeasurementRecord] = []
    for index, line in enumerate(lines, start=1):
        try:
            json.loads(line)
            measurements.append(MeasurementRecord.model_validate_json(line))
        except (json.JSONDecodeError, ValidationError) as error:
            raise DataIntegrityError(
                [
                    _storage_problem(
                        invalid_code,
                        f"{noun} line {index} is not a valid measurement record",
                        ref=ref,
                        category=ProblemCategory.DATA_INTEGRITY,
                        details={"line": index},
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
    contract: MeasurementDatasetReadContract,
) -> MeasurementDataset:
    records = read_measurement_records_path(
        path=path,
        ref=ref,
        missing_code=contract.missing_code,
        empty_code=contract.empty_code,
        invalid_code=contract.invalid_code,
        noun=contract.noun,
    )
    if schema_data is None:
        raise DataIntegrityError(
            [
                _storage_problem(
                    contract.missing_schema_code,
                    f"{contract.noun} ref is missing schema: {ref}",
                    ref=ref,
                    category=ProblemCategory.DATA_INTEGRITY,
                )
            ]
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(schema_data)
    except ValidationError as error:
        raise _invalid_dataset_schema(
            contract=contract,
            ref=ref,
        ) from error

    if schema.dataset_id != dataset_id:
        raise _invalid_dataset_schema(
            contract=contract,
            ref=ref,
        )

    row_problems = validate_measurement_dataset_records(
        records=records,
        schema=schema,
        dataset_id=dataset_id,
        dataset_role=schema.dataset_role,
    )
    if row_problems:
        raise _invalid_dataset_schema(
            contract=contract,
            ref=ref,
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
            contract=contract,
            ref=ref,
        ) from error


def _invalid_dataset_schema(
    *,
    contract: MeasurementDatasetReadContract,
    ref: str,
) -> DataIntegrityError:
    return DataIntegrityError(
        [
            _storage_problem(
                contract.invalid_schema_code,
                f"{contract.noun} dataset_schema is invalid: {ref}",
                ref=ref,
                category=ProblemCategory.DATA_INTEGRITY,
            )
        ]
    )


def _storage_problem(
    code: str,
    message: str,
    *,
    ref: str,
    category: ProblemCategory = ProblemCategory.STORAGE,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.PERSISTENCE,
        location=StorageLocation(ref=ref),
        details={} if details is None else details,
    )


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
