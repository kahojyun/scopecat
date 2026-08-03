from __future__ import annotations

from typing import Literal

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
    with pytest.raises(ValidationError, match="dimension ids must be unique"):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[
                MeasurementDimension(id="point", kind="point", size=1),
                MeasurementDimension(id="point", kind="point", size=1),
            ],
        )

    with pytest.raises(ValidationError, match="unknown dimensions"):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    dims=["point", "missing"],
                )
            ],
        )


def test_measurement_dimensions_and_variables_have_distinct_ids() -> None:
    with pytest.raises(ValidationError, match="distinct ids"):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[
                MeasurementDimension(id="point", kind="point", size=1),
                MeasurementDimension(id="sample", kind="sample", size=2),
            ],
            variables=[
                MeasurementVariable(
                    id="sample",
                    role="coordinate",
                    dtype="float64",
                    dims=["point", "sample"],
                )
            ],
        )


@pytest.mark.parametrize(
    "dimensions",
    [
        [],
        [MeasurementDimension(id="point", kind="batch", size=1)],
        [
            MeasurementDimension(id="point", kind="point", size=1),
            MeasurementDimension(id="sample", kind="point", size=2),
        ],
    ],
)
def test_measurement_dataset_schema_requires_one_canonical_point_dimension(
    dimensions: list[MeasurementDimension],
) -> None:
    with pytest.raises(ValidationError, match="exactly one point dimension"):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=dimensions,
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    dims=["point"],
                )
            ],
        )


def test_measurement_dataset_schema_requires_point_without_variables() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        MeasurementDatasetSchema.model_validate({"dataset_id": "bad"})


@pytest.mark.parametrize(
    ("dims", "message"),
    [
        ([], "at least 1 item"),
        (["shot", "point"], "first dimension"),
        (["point", "point"], "dimensions must be unique"),
    ],
)
def test_measurement_variables_require_unique_point_first_dimensions(
    dims: list[str],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[
                MeasurementDimension(id="point", kind="point", size=1),
                MeasurementDimension(id="shot", kind="shot", size=3),
            ],
            variables=[
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    dims=dims,
                )
            ],
        )


@pytest.mark.parametrize(
    ("field", "role"),
    [
        ("primary_coordinates", "coordinate"),
        ("primary_observables", "observable"),
    ],
)
def test_measurement_dataset_primary_ids_are_unique(
    field: Literal["primary_coordinates", "primary_observables"],
    role: Literal["coordinate", "observable"],
) -> None:
    with pytest.raises(ValidationError, match="ids must be unique"):
        MeasurementDatasetSchema(
            dataset_id="bad",
            dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
            variables=[
                MeasurementVariable(
                    id="sample",
                    role=role,
                    dtype="float64",
                    dims=["point"],
                )
            ],
            primary_coordinates=(
                ["sample", "sample"] if field == "primary_coordinates" else []
            ),
            primary_observables=(
                ["sample", "sample"] if field == "primary_observables" else []
            ),
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
            ),
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=["point"],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
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
            MeasurementDimension(id="shot", kind="shot", size=3),
        ],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit="GHz",
                dims=["point"],
            ),
            MeasurementVariable(
                id="i0",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point", "shot"],
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


def test_validate_schema_derives_inner_shape_from_dimensions() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=1),
            MeasurementDimension(id="shot", kind="shot", size=3),
        ],
        variables=[
            MeasurementVariable(
                id="i0",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point", "shot"],
            )
        ],
        primary_observables=["i0"],
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "i0": MeasurementArray.create(
                dtype="float64",
                unit="ratio",
                shape=[2],
                values=[0.1, 0.2],
            )
        },
    )

    problems = validate_measurement_records_against_schema(
        [record],
        schema,
        "raw-measurements",
    )

    assert [item.code for item in problems] == ["measurement_record_shape_mismatch"]
    assert problems[0].message.endswith("incompatible shape (2,), expected (3,)")


def test_variable_extent_preserves_array_rank_validation() -> None:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=1),
            MeasurementDimension(id="sample", kind="sample", size=None),
        ],
        variables=[
            MeasurementVariable(
                id="trace",
                role="observable",
                dtype="float64",
                dims=["point", "sample"],
            )
        ],
        primary_observables=["trace"],
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "trace": MeasurementArray.create(
                dtype="float64",
                shape=(2, 2),
                values=((0.1, 0.2), (0.3, 0.4)),
            )
        },
    )

    problems = validate_measurement_records_against_schema(
        [record], schema, "raw-measurements"
    )

    assert [problem.code for problem in problems] == [
        "measurement_record_shape_mismatch"
    ]
    assert problems[0].message.endswith("incompatible shape (2, 2), expected (None,)")


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
            ),
            MeasurementVariable(
                id="shot_index",
                role="coordinate",
                dtype="int64",
                unit="count",
                dims=["point"],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
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
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
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
            ),
            MeasurementVariable(
                id="status",
                role="observable",
                dtype="string",
                dims=["point"],
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
