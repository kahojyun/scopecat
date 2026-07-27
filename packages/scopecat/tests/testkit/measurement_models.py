from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementVariable,
)


def signal_record(
    *,
    point_index: int = 0,
    drive_frequency: float = 5.0,
    signal: float = 0.5,
) -> MeasurementRecord:
    return MeasurementRecord(
        run_id="run-000001",
        point_index=point_index,
        coordinates={"drive_frequency": Quantity(value=drive_frequency, unit="GHz")},
        observables={"signal": Quantity(value=signal, unit="ratio")},
    )


def signal_point_schema(
    *,
    dataset_id: str = "raw-measurements",
    size: int = 1,
    drive_frequency_unit: str = "GHz",
) -> MeasurementDatasetSchema:
    return MeasurementDatasetSchema(
        dataset_id=dataset_id,
        dimensions=[MeasurementDimension(id="point", kind="point", size=size)],
        variables=[
            MeasurementVariable(
                id="drive_frequency",
                role="coordinate",
                dtype="float64",
                unit=drive_frequency_unit,
                dims=["point"],
                shape=[size],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["point"],
                shape=[size],
            ),
        ],
        primary_coordinates=["drive_frequency"],
        primary_observables=["signal"],
    )
