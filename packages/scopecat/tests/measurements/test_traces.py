from __future__ import annotations

import pytest

from scopecat.measurements.results import (
    measurement_traces,
    validate_measurement_records_against_schema,
)
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

    traces = measurement_traces(dataset)

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


def test_trace_view_infers_the_coordinate_for_one_selected_observable() -> None:
    [trace, *_] = measurement_traces(_trace_dataset(), "s_parameter")

    assert trace.coordinate_id == "frequency"
    assert trace.observable_id == "s_parameter"


def test_trace_view_selects_one_recording_group_without_cross_pairing() -> None:
    dataset = _trace_dataset()
    frequency, s_parameter = dataset.dataset_schema.variables
    frequency.recording_group_id = "readout/first"
    s_parameter.recording_group_id = "readout/first"
    dataset.dataset_schema.variables.extend(
        (
            MeasurementVariable(
                id="second_frequency",
                role="coordinate",
                dtype="float64",
                unit="Hz",
                dims=["point", "frequency_sample"],
                recording_group_id="readout/second",
            ),
            MeasurementVariable(
                id="second_s_parameter",
                role="observable",
                dtype="complex128",
                unit="ratio",
                dims=["point", "frequency_sample"],
                recording_group_id="readout/second",
            ),
        )
    )
    for record in dataset.records:
        record.coordinates["second_frequency"] = record.coordinates["frequency"]
        record.observables["second_s_parameter"] = record.observables["s_parameter"]

    with pytest.raises(ValueError, match="ambiguous trace variables"):
        measurement_traces(dataset)

    [trace, *_] = measurement_traces(dataset, group="readout/second")

    assert trace.recording_group_id == "readout/second"
    assert trace.coordinate_id == "second_frequency"
    assert trace.observable_id == "second_s_parameter"
    [selected_trace, *_] = measurement_traces(dataset, "second_s_parameter")
    assert selected_trace.coordinate_id == "second_frequency"


def test_trace_view_rejects_unknown_and_mixed_recording_groups() -> None:
    dataset = _trace_dataset()
    frequency, s_parameter = dataset.dataset_schema.variables
    frequency.recording_group_id = "readout/first"
    s_parameter.recording_group_id = "readout/second"

    with pytest.raises(ValueError, match="no recording group 'missing'"):
        measurement_traces(dataset, group="missing")
    with pytest.raises(ValueError, match="must belong to one recording group"):
        measurement_traces(
            dataset,
            coordinate="frequency",
            observable="s_parameter",
        )


def test_trace_view_requires_a_selection_when_multiple_pairs_are_compatible() -> None:
    dataset = _trace_dataset()
    dataset.dataset_schema.variables.append(
        MeasurementVariable(
            id="phase",
            role="observable",
            dtype="float64",
            unit="rad",
            dims=["point", "frequency_sample"],
        )
    )
    dataset.dataset_schema.primary_observables.append("phase")
    for record in dataset.records:
        record.observables["phase"] = MeasurementArray.create(
            dtype="float64",
            unit="rad",
            shape=(3,),
            values=(0.0, 0.1, 0.2),
        )

    with pytest.raises(ValueError, match="ambiguous trace variables"):
        measurement_traces(dataset)

    [trace, *_] = measurement_traces(dataset, "phase")
    assert trace.coordinate_id == "frequency"
    assert trace.observable_id == "phase"


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


def test_trace_view_and_schema_accept_different_lengths_at_each_point() -> None:
    dataset = _trace_dataset()
    dataset.dataset_schema.dimensions[1].size = None
    dataset.records[1].coordinates["frequency"] = MeasurementArray.create(
        dtype="float64",
        unit="Hz",
        shape=(2,),
        values=(4.9e9, 5.0e9),
    )
    dataset.records[1].observables["s_parameter"] = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        shape=(2,),
        values=(
            ComplexComponents(real=1.0, imag=0.0),
            ComplexComponents(real=0.2, imag=-0.1),
        ),
    )

    assert (
        validate_measurement_records_against_schema(
            dataset.records,
            dataset.dataset_schema,
            "raw-measurements",
        )
        == []
    )
    traces = measurement_traces(dataset)
    assert [len(trace.x) for trace in traces] == [3, 2]
    assert [len(trace.y) for trace in traces] == [3, 2]


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
