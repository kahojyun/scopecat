from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.kernel.problems import model_location
from scopecat.measurements.results import validate_measurement_records_against_schema
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementVariable,
)
from tests.testkit.measurement_models import signal_record


def test_measurement_dataset_schema_validates_references() -> None:
    with pytest.raises(ValidationError):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[
                MeasurementDimension(id="point", kind="point"),
                MeasurementDimension(id="point", kind="point"),
            ],
        )

    with pytest.raises(ValidationError):
        MeasurementDatasetSchema(
            dataset_id="bad",
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
                    "shot_index": MeasurementScalar.create(
                        dtype="int64",
                        unit="count",
                        value=0,
                    ),
                }
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "raw-measurements",
    )

    assert problems == []


def test_validate_schema_accepts_point_local_arrays() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
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
        coordinates={
            "drive_frequency": MeasurementScalar.create(
                dtype="float64",
                unit="GHz",
                value=5.0,
            )
        },
        observables={
            "i0": MeasurementArray.create(
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
    )

    assert problems == []


def test_validate_measurement_records_against_schema_reports_contract_errors() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
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
        ],
        primary_coordinates=["drive_frequency", "shot_index"],
        primary_observables=["signal"],
    )
    records = [
        signal_record().model_copy(
            update={
                "coordinates": {
                    "drive_frequency": MeasurementScalar.create(
                        dtype="float64",
                        unit="GHz",
                        value=5.0,
                    ),
                    "extra_coordinate": MeasurementScalar.create(
                        dtype="float64",
                        unit="count",
                        value=1.0,
                    ),
                },
                "observables": {
                    "extra_observable": MeasurementScalar.create(
                        dtype="float64",
                        unit="ratio",
                        value=2.0,
                    ),
                },
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "other-id",
    )
    codes = {problem.code for problem in problems}

    assert {
        "measurement_dataset_id_mismatch",
        "measurement_dataset_record_count_mismatch",
        "measurement_dataset_variable_shape_mismatch",
        "measurement_record_missing_coordinate",
        "measurement_record_missing_observable",
        "measurement_record_unexpected_coordinate",
        "measurement_record_unexpected_observable",
    }.issubset(codes)


def test_validate_measurement_records_against_schema_reports_unit_and_dtype() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
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
                "coordinates": {
                    "shot_index": MeasurementScalar.create(
                        dtype="float64",
                        unit="count",
                        value=0.5,
                    )
                },
                "observables": {
                    "signal": MeasurementScalar.create(
                        dtype="float64",
                        unit="GHz",
                        value=0.5,
                    )
                },
            }
        )
    ]

    problems = validate_measurement_records_against_schema(
        records,
        schema,
        "raw-measurements",
    )
    codes = {problem.code for problem in problems}

    assert "measurement_record_dtype_mismatch" in codes
    assert "measurement_record_unit_mismatch" in codes


def test_validate_schema_accepts_bool_and_string_values() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
        variables=[
            MeasurementVariable(
                id="valid",
                role="coordinate",
                dtype="bool",
                dims=["point"],
                shape=[1],
            ),
            MeasurementVariable(
                id="status",
                role="observable",
                dtype="string",
                dims=["point"],
                shape=[1],
            ),
        ],
        primary_coordinates=["valid"],
        primary_observables=["status"],
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={
            "valid": MeasurementScalar.create(dtype="bool", unit=None, value=True),
        },
        observables={
            "status": MeasurementScalar.create(
                dtype="string", unit=None, value="ready"
            ),
        },
    )

    problems = validate_measurement_records_against_schema(
        [record],
        schema,
        "raw-measurements",
    )

    assert problems == []


def test_validate_schema_reports_unexpected_unit_for_unitless_variable() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
        variables=[
            MeasurementVariable(
                id="sample",
                role="observable",
                dtype="float64",
                unit=None,
                dims=["point"],
                shape=[1],
            )
        ],
        primary_observables=["sample"],
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "sample": MeasurementScalar.create(
                dtype="float64",
                unit="ratio",
                value=0.5,
            )
        },
    )

    problems = validate_measurement_records_against_schema(
        [record],
        schema,
        "raw-measurements",
    )

    assert [item.code for item in problems] == ["measurement_record_unit_mismatch"]
    assert problems[0].location == model_location(
        "measurement_dataset",
        "records",
        0,
        "observables",
        "sample",
        "unit",
    )
