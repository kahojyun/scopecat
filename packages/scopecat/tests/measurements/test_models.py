from __future__ import annotations

from typing import cast

from scopecat.records.measurement import (
    MEASUREMENT_DATASET_FORMAT_VERSION,
    MEASUREMENT_RECORD_SCHEMA_VERSION,
    ComplexQuantity,
    MeasurementArray,
    MeasurementDataset,
    MeasurementRecord,
)
from scopecat.records.parameter import Quantity
from tests.testkit.measurement_models import signal_point_schema, signal_record
from tests.testkit.records import assert_model_round_trip


def test_measurement_record_round_trip() -> None:
    measurement = signal_record().model_copy(update={"metadata": {"source": "test"}})

    restored = assert_model_round_trip(measurement)

    assert restored.point_index == 0
    signal = restored.observables["signal"]
    assert isinstance(signal, Quantity)
    assert signal.value == 0.5


def test_measurement_array_record_round_trip() -> None:
    measurement = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "i0": MeasurementArray(
                dtype="float64",
                unit="ratio",
                shape=[3],
                values=[0.1, 0.2, 0.3],
            )
        },
    )

    restored = assert_model_round_trip(measurement)
    i0 = restored.observables["i0"]

    assert isinstance(i0, MeasurementArray)
    assert i0.shape == [3]
    assert i0.values == [0.1, 0.2, 0.3]


def test_typed_measurement_array_leaves_survive_record_round_trip() -> None:
    measurement = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "iq": MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[1, 2],
                values=[
                    [
                        ComplexQuantity(real=0.1, imag=-0.2, unit="ratio"),
                        ComplexQuantity(real=0.3, imag=-0.4, unit="ratio"),
                    ]
                ],
            ),
            "probability": MeasurementArray(
                dtype="float64",
                unit="ratio",
                shape=[2],
                values=[
                    Quantity(value=0.25, unit="ratio"),
                    Quantity(value=0.75, unit="ratio"),
                ],
            ),
        },
    )

    restored = assert_model_round_trip(measurement)
    iq = restored.observables["iq"]
    probability = restored.observables["probability"]
    original_iq = measurement.observables["iq"]
    original_probability = measurement.observables["probability"]

    assert isinstance(iq, MeasurementArray)
    assert isinstance(original_iq, MeasurementArray)
    assert isinstance(cast("list[object]", iq.values[0])[0], ComplexQuantity)
    assert iq.values == original_iq.values
    assert isinstance(probability, MeasurementArray)
    assert isinstance(original_probability, MeasurementArray)
    assert all(isinstance(value, Quantity) for value in probability.values)
    assert probability.values == original_probability.values


def test_complex_measurement_record_round_trip() -> None:
    measurement = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "raw_iq": ComplexQuantity(real=0.3, imag=-0.4, unit="ratio"),
        },
    )

    restored = assert_model_round_trip(measurement)
    raw_iq = restored.observables["raw_iq"]

    assert isinstance(raw_iq, ComplexQuantity)
    assert raw_iq.real == 0.3
    assert raw_iq.imag == -0.4


def test_measurement_dataset_schema_round_trip() -> None:
    schema = signal_point_schema(size=3)

    restored = assert_model_round_trip(schema)

    assert restored.format_version == MEASUREMENT_DATASET_FORMAT_VERSION
    assert restored.record_schema == MEASUREMENT_RECORD_SCHEMA_VERSION
    assert restored.primary_coordinates == ["drive_frequency"]
    assert restored.primary_observables == ["signal"]


def test_measurement_dataset_round_trip() -> None:
    record = signal_record()
    schema = signal_point_schema()
    dataset = MeasurementDataset(
        schema=schema,
        records=[record],
        metadata={"dataset_role": "raw"},
    )
    restored = assert_model_round_trip(dataset)

    assert restored.dataset_schema.dataset_id == "raw-measurements"
    assert restored.dataset_schema.primary_observables == ["signal"]
    assert restored.records[0].point_index == 0
    assert dataset.model_dump(mode="json", by_alias=True)["schema"]["dataset_id"] == (
        "raw-measurements"
    )
