from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementVariable,
    validate_measurement_records_against_schema,
)
from scopecat.records.parameter import Quantity
from tests.testkit.measurement_models import signal_record


def test_measurement_dataset_schema_validates_references() -> None:
    with pytest.raises(ValidationError):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dataset_role="raw",
            dimensions=[
                MeasurementDimension(id="point", kind="point"),
                MeasurementDimension(id="point", kind="point"),
            ],
        )

    with pytest.raises(ValidationError):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dataset_role="raw",
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    dims=["point"],
                    shape=[1],
                )
            ],
        )


def test_validate_measurement_records_against_schema_accepts_compatible_units() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="MHz",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
                shape=[1],
            ),
        ],
        primary_coordinates=["drive_frequency", "shot_index"],
        primary_observables=["signal"],
    )
    record = signal_record()
    records = [
        record.model_copy(
            update={
                "coordinates": {
                    **record.coordinates,
                    "shot_index": Quantity(value=0.0, unit="count"),
                }
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "raw-measurements",
        "raw",
    )

    assert problems == []


def test_validate_schema_accepts_point_local_arrays() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=1),
            MeasurementDimension(id="shot", kind="shot", size=3, unit="count"),
        ],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="GHz",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="i0",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point", "shot"],
                shape=[1, 3],
            ),
        ],
        primary_coordinates=["drive_frequency"],
        primary_observables=["i0"],
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={"drive_frequency": Quantity(value=5.0, unit="GHz")},
        observables={
            "i0": MeasurementArray(
                dtype="float64",
                unit="ratio",
                shape=[3],
                values=[0.1, 0.2, 0.3],
            )
        },
    )

    problems = validate_measurement_records_against_schema(
        [record],
        schema,
        "raw-measurements",
        "raw",
    )

    assert problems == []


def test_validate_measurement_records_against_schema_reports_contract_errors() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        dimensions=[MeasurementDimension(id="point", kind="point", size=2)],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="GHz",
                dims=["point"],
                shape=[2],
            ),
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=["point"],
                shape=[2],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
                shape=[2],
            ),
            MeasurementVariable(
                id="quality",
                role="status",
                dtype="bool",
                dims=["point"],
                shape=[2],
            ),
        ],
        primary_coordinates=["drive_frequency", "shot_index"],
        primary_observables=["signal"],
    )
    records = [
        signal_record().model_copy(
            update={
                "coordinates": {
                    "drive_frequency": Quantity(value=5.0, unit="GHz"),
                    "extra_coordinate": Quantity(value=1.0, unit="count"),
                },
                "observables": {
                    "extra_observable": Quantity(value=2.0, unit="ratio"),
                },
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "other-id",
        "derived",
    )
    codes = {problem.code for problem in problems}

    assert {
        "measurement_dataset_id_mismatch",
        "measurement_dataset_role_mismatch",
        "measurement_dataset_record_count_mismatch",
        "measurement_dataset_variable_shape_mismatch",
        "measurement_dataset_unsupported_variable_role",
        "measurement_dataset_unsupported_dtype",
        "measurement_record_missing_coordinate",
        "measurement_record_missing_observable",
        "measurement_record_unexpected_coordinate",
        "measurement_record_unexpected_observable",
    }.issubset(codes)


def test_validate_measurement_records_against_schema_reports_unit_and_dtype() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dataset_role="raw",
        dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
        variables=[
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
                shape=[1],
            ),
        ],
        primary_coordinates=["shot_index"],
        primary_observables=["signal"],
    )
    records = [
        signal_record().model_copy(
            update={
                "coordinates": {"shot_index": Quantity(value=0.5, unit="count")},
                "observables": {"signal": Quantity(value=0.5, unit="GHz")},
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "raw-measurements",
        "raw",
    )
    codes = {problem.code for problem in problems}

    assert "measurement_record_dtype_mismatch" in codes
    assert "measurement_record_unit_mismatch" in codes
