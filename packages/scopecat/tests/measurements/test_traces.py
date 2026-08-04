from __future__ import annotations

import math

import pytest

from scopecat.measurements.results import (
    TraceComplexMode,
    measurement_traces,
    project_measurement_trace_preview,
    validate_measurement_records_against_schema,
)
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementProductGridPointDomain,
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


@pytest.mark.parametrize("grouped_variable_index", [0, 1])
def test_trace_preview_explicitly_pairs_variables_when_only_one_has_a_group(
    grouped_variable_index: int,
) -> None:
    dataset = _trace_dataset()
    dataset.dataset_schema.variables[
        grouped_variable_index
    ].recording_group_id = "readout"

    with pytest.raises(ValueError, match="no compatible trace variables"):
        project_measurement_trace_preview(dataset, "s_parameter")

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        coordinate="frequency",
        max_series=1,
        max_samples=2,
    )

    assert projection.coordinate_id == "frequency"
    assert projection.observable_id == "s_parameter"
    assert projection.recording_group_id == "readout"


@pytest.mark.parametrize(
    ("complex_mode", "expected"),
    [
        ("magnitude", (1.0, math.hypot(0.9, 0.1))),
        ("phase", (0.0, math.atan2(0.1, 0.9))),
        ("real", (1.0, 0.9)),
        ("imag", (0.0, 0.1)),
    ],
)
def test_trace_preview_projects_complex_modes_with_even_endpoint_sampling(
    complex_mode: TraceComplexMode,
    expected: tuple[float, float],
) -> None:
    projection = project_measurement_trace_preview(
        _trace_dataset(),
        "s_parameter",
        max_series=2,
        max_samples=4,
        complex_mode=complex_mode,
    )

    assert projection.value_mode == complex_mode
    assert projection.value_unit == ("rad" if complex_mode == "phase" else "ratio")
    assert projection.source_sample_count == 6
    assert projection.returned_sample_count == 4
    assert projection.samples_reduced
    assert len(projection.series) == 2
    assert projection.series[0].x == (4.9e9, 5.1e9)
    assert projection.series[0].y == pytest.approx(expected)


def test_trace_preview_reports_value_mode_for_real_observable() -> None:
    dataset = _trace_dataset()
    dataset.dataset_schema.variables[1] = dataset.dataset_schema.variables[
        1
    ].model_copy(update={"dtype": "float64"})
    for record in dataset.records:
        record.observables["s_parameter"] = MeasurementArray.create(
            dtype="float64",
            unit="ratio",
            shape=(3,),
            values=(1.0, 0.2, 0.9),
        )

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        max_series=1,
        max_samples=2,
        complex_mode="phase",
    )

    assert projection.value_mode == "value"
    assert projection.value_unit == "ratio"
    assert projection.series[0].y == (1.0, 0.9)


def test_trace_preview_omits_unavailable_series_without_scanning_past_cap() -> None:
    dataset = _trace_dataset()
    dataset.records[0].observables["s_parameter"] = MeasurementUnavailable.create(
        reason="overload",
        dtype="complex128",
        unit="ratio",
        shape=(3,),
        metadata={},
    )
    dataset.records.append(
        MeasurementRecord(
            run_id="trace-run",
            logical_point_id="must-not-be-read",
            point_index=2,
            coordinates={},
            observables={},
        )
    )

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        max_series=2,
        max_samples=4,
    )

    assert [series.point_index for series in projection.series] == [1]
    assert projection.source_sample_count == 3
    assert projection.returned_sample_count == 3
    assert not projection.samples_reduced


def _trace_dataset() -> MeasurementDataset:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        point_domain=MeasurementProductGridPointDomain(axes=[]),
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
        dataset_schema=schema,
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
