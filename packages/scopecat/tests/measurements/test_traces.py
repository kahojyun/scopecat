from __future__ import annotations

import pytest

from scopecat.measurements.results import measurement_traces
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementUnavailable,
    MeasurementVariable,
)


def test_trace_view_selects_one_shared_point_local_dimension() -> None:
    dataset = _trace_dataset()

    traces = measurement_traces(
        dataset,
        coordinate="frequency",
        observable="s_parameter",
    )

    assert [trace.point_index for trace in traces] == [0, 1]
    assert traces[0].dimension_id == "frequency_sample"
    assert traces[0].coordinate_label == "Stimulus frequency"
    assert traces[0].observable_label == "S21"
    assert traces[0].coordinate_unit == "Hz"
    assert traces[0].observable_unit == "ratio"
    assert traces[0].x == (4.9e9, 5.0e9, 5.1e9)
    assert traces[0].y == (
        complex(1.0, 0.0),
        complex(0.2, -0.1),
        complex(0.9, 0.1),
    )


def test_trace_view_reports_unavailable_point_values() -> None:
    dataset = _trace_dataset()
    dataset.records[1].observables["s_parameter"] = MeasurementUnavailable.create(
        reason="overload",
        dtype="complex128",
        unit="ratio",
        shape=(3,),
        metadata={},
    )

    with pytest.raises(
        ValueError,
        match=r"s_parameter.*unavailable at point 1: overload",
    ):
        measurement_traces(
            dataset,
            coordinate="frequency",
            observable="s_parameter",
        )


def _trace_dataset() -> MeasurementDataset:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=2),
            MeasurementDimension(
                id="frequency_sample",
                kind="frequency",
                size=3,
            ),
        ],
        variables=[
            MeasurementVariable(
                id="frequency",
                role="coordinate",
                dtype="float64",
                unit="Hz",
                dims=["point", "frequency_sample"],
                label="Stimulus frequency",
            ),
            MeasurementVariable(
                id="s_parameter",
                role="observable",
                dtype="complex128",
                unit="ratio",
                dims=["point", "frequency_sample"],
                label="S21",
            ),
        ],
        primary_coordinates=["frequency"],
        primary_observables=["s_parameter"],
    )
    return MeasurementDataset(
        schema=schema,
        records=[
            MeasurementRecord(
                run_id="trace-run",
                logical_point_id=f"point-{point_index}",
                point_index=point_index,
                coordinates={
                    "frequency": MeasurementArray.create(
                        dtype="float64",
                        unit="Hz",
                        shape=(3,),
                        values=(4.9e9, 5.0e9, 5.1e9),
                    )
                },
                observables={
                    "s_parameter": MeasurementArray.create(
                        dtype="complex128",
                        unit="ratio",
                        shape=(3,),
                        values=(
                            ComplexComponents(real=1.0, imag=0.0),
                            ComplexComponents(real=0.2, imag=-0.1),
                            ComplexComponents(real=0.9, imag=0.1),
                        ),
                    )
                },
            )
            for point_index in range(2)
        ],
    )
