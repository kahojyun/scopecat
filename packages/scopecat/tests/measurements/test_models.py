from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import (
    MEASUREMENT_DATASET_FORMAT_VERSION,
    MEASUREMENT_RECORD_SCHEMA_VERSION,
    ComplexQuantity,
    MeasurementArray,
    MeasurementDataset,
    MeasurementRecord,
)
from tests.testkit.measurement_models import signal_point_schema, signal_record
from tests.testkit.records import assert_model_round_trip


def test_measurement_values_round_trip_through_one_record() -> None:
    measurement = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={
            "signal": Quantity(value=0.5, unit="ratio"),
            "raw_iq": ComplexQuantity(real=0.3, imag=-0.4, unit="ratio"),
            "samples": MeasurementArray(
                dtype="float64",
                unit="ratio",
                shape=[3],
                values=[0.1, 0.2, 0.3],
            ),
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

    assert restored == measurement
    assert isinstance(restored.observables["signal"], Quantity)
    assert isinstance(restored.observables["raw_iq"], ComplexQuantity)
    assert isinstance(restored.observables["samples"], MeasurementArray)
    assert isinstance(restored.observables["iq"], MeasurementArray)
    assert isinstance(restored.observables["probability"], MeasurementArray)


def test_measurement_dataset_and_schema_round_trip() -> None:
    record = signal_record()
    schema = signal_point_schema(size=3)
    dataset = MeasurementDataset(
        schema=schema,
        records=[record],
    )
    restored = assert_model_round_trip(dataset)

    assert restored.dataset_schema.format_version == MEASUREMENT_DATASET_FORMAT_VERSION
    assert restored.dataset_schema.record_schema == MEASUREMENT_RECORD_SCHEMA_VERSION
    assert restored.dataset_schema.dataset_id == "raw-measurements"
    assert restored.dataset_schema.primary_coordinates == ["drive_frequency"]
    assert restored.dataset_schema.primary_observables == ["signal"]
    assert restored == dataset
