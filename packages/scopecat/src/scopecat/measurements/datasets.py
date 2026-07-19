"""Pure measurement-dataset assembly and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue, ValidationError

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import DataIntegrityError, NotFound
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.measurements.results import (
    MeasurementDataset,
    MeasurementDatasetReadContract,
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementRecord,
    infer_measurement_dataset_schema,
    validate_measurement_records_against_schema,
)
from scopecat.records.artifact import RunContentEntry

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
) -> RunContentEntry:
    schema = measurement_dataset_schema(
        dataset_id=dataset_id,
        dataset_role=dataset_role,
        records=records,
        expected_schema=expected_schema,
        metadata=metadata,
    )
    return RunContentEntry(
        role="dataset",
        id=dataset_id,
        kind=MEASUREMENT_DATASET_KIND,
        media_type=media_type,
        dataset_role=dataset_role,
        schema=schema.model_dump(mode="json"),
        content_hash=stable_content_hash(content_fingerprint(tuple(records))),
        metadata=dict(metadata or {}),
    )


def assemble_measurement_dataset(
    *,
    records: Sequence[MeasurementRecord],
    dataset_id: str,
    ref: str,
    schema_data: dict[str, object] | None,
    metadata: Mapping[str, object],
    contract: MeasurementDatasetReadContract,
) -> MeasurementDataset:
    """Bind already-decoded records to their durable dataset contract."""

    if not records:
        raise measurement_records_error(
            contract.empty_code,
            f"{contract.noun} is empty: {ref}",
            ref=ref,
        )
    if schema_data is None:
        raise measurement_records_error(
            contract.missing_schema_code,
            f"{contract.noun} ref is missing schema: {ref}",
            ref=ref,
        )
    try:
        schema = MeasurementDatasetSchema.model_validate(schema_data)
    except ValidationError as error:
        raise invalid_measurement_dataset(contract=contract, ref=ref) from error
    if schema.dataset_id != dataset_id:
        raise invalid_measurement_dataset(contract=contract, ref=ref)
    if validate_measurement_dataset_records(
        records=records,
        schema=schema,
        dataset_id=dataset_id,
        dataset_role=schema.dataset_role,
    ):
        raise invalid_measurement_dataset(contract=contract, ref=ref)
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
        raise invalid_measurement_dataset(contract=contract, ref=ref) from error


def invalid_measurement_dataset(
    *, contract: MeasurementDatasetReadContract, ref: str
) -> DataIntegrityError | NotFound:
    return measurement_records_error(
        contract.invalid_schema_code,
        f"{contract.noun} dataset_schema is invalid: {ref}",
        ref=ref,
    )


def measurement_records_error(
    code: str,
    message: str,
    *,
    ref: str,
    category: ProblemCategory = ProblemCategory.DATA_INTEGRITY,
) -> DataIntegrityError | NotFound:
    problem = blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.PERSISTENCE,
        location=StorageLocation(ref=ref),
    )
    if category == ProblemCategory.NOT_FOUND:
        return NotFound((problem,))
    return DataIntegrityError((problem,))
