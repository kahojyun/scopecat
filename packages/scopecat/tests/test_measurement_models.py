from __future__ import annotations

from scopecat.models.measurement import (
    MEASUREMENT_DATASET_SCHEMA_VERSION,
    MEASUREMENT_RECORD_SCHEMA_VERSION,
    MeasurementDataset,
    MeasurementDatasetInputDiagnostics,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementVariable,
    infer_measurement_dataset_artifact_metadata,
    infer_measurement_dataset_schema,
    measurement_dataset_artifact_metadata,
)
from tests.support.measurement_models import signal_point_schema, signal_record
from tests.support.records import assert_model_round_trip


def test_measurement_record_round_trip() -> None:
    measurement = signal_record().model_copy(update={"metadata": {"source": "test"}})

    restored = assert_model_round_trip(
        measurement,
        schema_version="scopecat.measurement_record.v0",
    )

    assert restored.point_index == 0
    assert restored.observables["signal"].value == 0.5


def test_measurement_dataset_schema_round_trip() -> None:
    schema = signal_point_schema(size=3)

    restored = assert_model_round_trip(
        schema,
        schema_version=MEASUREMENT_DATASET_SCHEMA_VERSION,
    )

    assert restored.record_schema == MEASUREMENT_RECORD_SCHEMA_VERSION
    assert restored.primary_coordinates == ["drive_frequency"]
    assert restored.primary_observables == ["signal"]


def test_infer_measurement_dataset_schema_from_records() -> None:
    records = [
        signal_record(point_index=0, drive_frequency=5.0, signal=0.5),
        signal_record(point_index=1, drive_frequency=5.1, signal=0.6),
    ]

    schema = infer_measurement_dataset_schema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        records=records,
    )
    variables = {variable.id: variable for variable in schema.variables}

    assert schema.dimensions[0].id == "point"
    assert schema.dimensions[0].size == 2
    assert schema.primary_coordinates == ["drive_frequency"]
    assert schema.primary_observables == ["signal"]
    assert variables["drive_frequency"].role == "coordinate"
    assert variables["drive_frequency"].unit == "GHz"
    assert variables["drive_frequency"].shape == [2]
    assert variables["signal"].role == "observable"
    assert variables["signal"].unit == "ratio"


def test_infer_measurement_dataset_artifact_metadata_from_records() -> None:
    metadata = infer_measurement_dataset_artifact_metadata(
        dataset_id="derived-sample",
        dataset_role="derived",
        records=[signal_record()],
        source_step="fake-processing",
        source_artifact_ids=["raw-measurements"],
    )

    assert metadata["dataset_role"] == "derived"
    assert metadata["record_schema"] == MEASUREMENT_RECORD_SCHEMA_VERSION
    assert metadata["source_step"] == "fake-processing"
    assert metadata["source_artifact_ids"] == ["raw-measurements"]
    assert metadata["dataset_schema"]["dataset_id"] == "derived-sample"
    assert metadata["dataset_schema"]["primary_observables"] == ["signal"]


def test_measurement_dataset_artifact_metadata_uses_expected_schema() -> None:
    expected_schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        dimensions=[MeasurementDimension(id="shot", kind="shot", size=1)],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="GHz",
                dims=["shot"],
                shape=[1],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["shot"],
                shape=[1],
            ),
        ],
        primary_coordinates=["drive_frequency"],
        primary_observables=["signal"],
    )

    metadata = measurement_dataset_artifact_metadata(
        dataset_id="raw-measurements",
        dataset_role="raw",
        records=[signal_record()],
        expected_schema=expected_schema,
    )

    dataset_schema = MeasurementDatasetSchema.model_validate(metadata["dataset_schema"])
    assert dataset_schema == expected_schema
    assert dataset_schema.dimensions[0].id == "shot"


def test_measurement_dataset_round_trip() -> None:
    record = signal_record()
    schema = infer_measurement_dataset_schema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        records=[record],
    )
    dataset = MeasurementDataset(
        artifact_id="raw-measurements",
        ref="artifacts/raw-measurements.jsonl",
        schema=schema,
        records=[record],
        metadata={"dataset_role": "raw"},
    )
    restored = assert_model_round_trip(dataset)

    assert restored.artifact_id == "raw-measurements"
    assert restored.ref == "artifacts/raw-measurements.jsonl"
    assert restored.dataset_schema.primary_observables == ["signal"]
    assert restored.records[0].point_index == 0
    assert dataset.model_dump(mode="json", by_alias=True)["schema"]["dataset_id"] == (
        "raw-measurements"
    )


def test_measurement_dataset_input_diagnostics_is_typed() -> None:
    diagnostics = MeasurementDatasetInputDiagnostics(
        missing_code="missing",
        empty_code="empty",
        invalid_code="invalid",
        missing_schema_code="missing_schema",
        invalid_schema_code="invalid_schema",
        noun="measurement dataset",
        diagnostic_path="input",
    )

    assert diagnostics.missing_schema_code == "missing_schema"
