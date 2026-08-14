from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

import numpy as np
import pytest

from scopecat.measurements.results import validate_measurement_records_against_schema
from scopecat.measurements.traces import (
    TraceValueMode,
    measurement_traces,
    project_measurement_trace_preview,
)
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementPointCloudPointDomain,
    MeasurementRecord,
    MeasurementUnavailable,
    MeasurementValue,
    MeasurementVariable,
    MeasurementVariableGroup,
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
    np.testing.assert_array_equal(
        traces[0].x,
        np.array([4.9e9, 5.0e9, 5.1e9], dtype=np.float64),
    )
    np.testing.assert_array_equal(
        traces[0].y,
        np.array(
            [
                complex(1.0, 0.0),
                complex(0.2, -0.1),
                complex(0.9, 0.1),
            ],
            dtype=np.complex128,
        ),
    )
    assert not traces[0].x.flags.writeable
    assert not traces[0].y.flags.writeable


def test_trace_view_infers_the_coordinate_for_one_selected_observable() -> None:
    [trace, *_] = measurement_traces(_trace_dataset(), "s_parameter")

    assert trace.coordinate_id == "frequency"
    assert trace.observable_id == "s_parameter"


def test_trace_view_selects_one_recording_group_without_cross_pairing() -> None:
    dataset = _trace_dataset()
    frequency, s_parameter = dataset.dataset_schema.variables
    first_variables = (
        frequency.model_copy(update={"recording_group_id": "readout/first"}),
        s_parameter.model_copy(update={"recording_group_id": "readout/first"}),
    )
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            variables=(
                *first_variables,
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
            ),
        ),
        records=tuple(
            _replace_record_values(
                record,
                coordinates={"second_frequency": record.coordinates["frequency"]},
                observables={"second_s_parameter": record.observables["s_parameter"]},
            )
            for record in dataset.records
        ),
    )

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
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            variables=(
                frequency.model_copy(update={"recording_group_id": "readout/first"}),
                s_parameter.model_copy(update={"recording_group_id": "readout/second"}),
            ),
        ),
    )

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
    phase = MeasurementVariable(
        id="phase",
        role="observable",
        dtype="float64",
        unit="rad",
        dims=["point", "frequency_sample"],
    )
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            variables=(*dataset.dataset_schema.variables, phase),
            primary_observables=(
                *dataset.dataset_schema.primary_observables,
                "phase",
            ),
        ),
        records=tuple(
            _replace_record_values(
                record,
                observables={
                    "phase": MeasurementArray.create(
                        dtype="float64",
                        unit="rad",
                        values=(0.0, 0.1, 0.2),
                    )
                },
            )
            for record in dataset.records
        ),
    )

    with pytest.raises(ValueError, match="ambiguous trace variables"):
        measurement_traces(dataset)

    [trace, *_] = measurement_traces(dataset, "phase")
    assert trace.coordinate_id == "frequency"
    assert trace.observable_id == "phase"


def test_trace_view_reports_unavailable_point_values() -> None:
    dataset = _trace_dataset()
    unavailable = MeasurementUnavailable.create(
        reason="overload",
        dtype="complex128",
        unit="ratio",
        shape=(3,),
        metadata={},
    )
    dataset = _replace_dataset(
        dataset,
        records=(
            dataset.records[0],
            _replace_record_values(
                dataset.records[1],
                observables={"s_parameter": unavailable},
            ),
        ),
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
    short_frequency = MeasurementArray.create(
        dtype="float64",
        unit="Hz",
        values=(4.9e9, 5.0e9),
    )
    short_parameter = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        values=(
            complex(1.0, 0.0),
            complex(0.2, -0.1),
        ),
    )
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            dimensions=(
                dataset.dataset_schema.dimensions[0],
                dataset.dataset_schema.dimensions[1].model_copy(update={"size": None}),
            ),
        ),
        records=(
            dataset.records[0],
            _replace_record_values(
                dataset.records[1],
                coordinates={"frequency": short_frequency},
                observables={"s_parameter": short_parameter},
            ),
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
def test_trace_preview_rejects_pair_when_only_one_variable_has_a_group(
    grouped_variable_index: int,
) -> None:
    dataset = _trace_dataset()
    variables = list(dataset.dataset_schema.variables)
    variables[grouped_variable_index] = variables[grouped_variable_index].model_copy(
        update={"recording_group_id": "readout"}
    )
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            variables=tuple(variables),
        ),
    )

    with pytest.raises(ValueError, match="no compatible trace variables"):
        project_measurement_trace_preview(dataset, "s_parameter")

    with pytest.raises(ValueError, match="must belong to one recording group"):
        project_measurement_trace_preview(
            dataset,
            "s_parameter",
            coordinate="frequency",
            max_series=1,
            max_samples=2,
        )


@pytest.mark.parametrize(
    ("value_mode", "expected"),
    [
        ("magnitude", (1.0, math.hypot(0.9, 0.1))),
        ("phase", (0.0, math.atan2(0.1, 0.9))),
        ("real", (1.0, 0.9)),
        ("imag", (0.0, 0.1)),
    ],
)
def test_trace_preview_projects_value_modes_with_minmax_endpoint_sampling(
    value_mode: TraceValueMode,
    expected: tuple[float, float],
) -> None:
    projection = project_measurement_trace_preview(
        _trace_dataset(),
        "s_parameter",
        max_series=2,
        max_samples=4,
        value_mode=value_mode,
    )

    assert projection.value_mode == value_mode
    assert projection.value_unit == ("rad" if value_mode == "phase" else "ratio")
    assert projection.source_sample_count == 6
    assert projection.returned_sample_count == 4
    assert projection.samples_reduced
    assert len(projection.series) == 2
    assert projection.series[0].x == (4.9e9, 5.1e9)
    assert projection.series[0].y == pytest.approx(expected)


def test_trace_preview_minmax_sampling_preserves_narrow_extrema() -> None:
    dataset = _trace_dataset()
    frequency_variable, parameter_variable = dataset.dataset_schema.variables
    x = np.arange(101, dtype=np.float64)
    y = np.zeros(101, dtype=np.float64)
    y[37] = 12.0
    y[38] = -10.0
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            dimensions=(
                dataset.dataset_schema.dimensions[0],
                dataset.dataset_schema.dimensions[1].model_copy(update={"size": 101}),
            ),
            variables=(
                frequency_variable,
                parameter_variable.model_copy(update={"dtype": "float64"}),
            ),
        ),
        records=tuple(
            _replace_record_values(
                record,
                coordinates={
                    "frequency": MeasurementArray.create(
                        values=x,
                        dtype="float64",
                        unit="Hz",
                    )
                },
                observables={
                    "s_parameter": MeasurementArray.create(
                        values=y,
                        dtype="float64",
                        unit="ratio",
                    )
                },
            )
            for record in dataset.records
        ),
    )

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        max_series=1,
        max_samples=9,
        value_mode="value",
    )

    [series] = projection.series
    assert projection.downsampling == "minmax"
    assert len(series.y) == 9
    assert series.x[0] == 0.0
    assert series.x[-1] == 100.0
    assert 37.0 in series.x
    assert 38.0 in series.x
    assert 12.0 in series.y
    assert -10.0 in series.y


def test_trace_preview_requires_a_projection_mode_for_complex_values() -> None:
    with pytest.raises(ValueError, match="require a projected value mode"):
        project_measurement_trace_preview(
            _trace_dataset(),
            "s_parameter",
            value_mode="value",
        )


def test_trace_preview_reports_value_mode_for_real_observable() -> None:
    dataset = _trace_dataset()
    frequency_variable, parameter_variable = dataset.dataset_schema.variables
    dataset = _replace_dataset(
        dataset,
        dataset_schema=_replace_schema(
            dataset.dataset_schema,
            variables=(
                frequency_variable,
                parameter_variable.model_copy(update={"dtype": "float64"}),
            ),
        ),
        records=tuple(
            _replace_record_values(
                record,
                observables={
                    "s_parameter": MeasurementArray.create(
                        dtype="float64",
                        unit="ratio",
                        values=(1.0, 0.2, 0.9),
                    )
                },
            )
            for record in dataset.records
        ),
    )

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        max_series=1,
        max_samples=2,
        value_mode="value",
    )

    assert projection.value_mode == "value"
    assert projection.value_unit == "ratio"
    assert projection.series[0].y == (1.0, 0.9)

    with pytest.raises(ValueError, match="real trace samples require value mode"):
        project_measurement_trace_preview(
            dataset,
            "s_parameter",
            value_mode="phase",
        )


def test_trace_preview_scans_past_unavailable_series_until_cap() -> None:
    dataset = _trace_dataset()
    unavailable = MeasurementUnavailable.create(
        reason="overload",
        dtype="complex128",
        unit="ratio",
        shape=(3,),
        metadata={},
    )
    dataset = _replace_dataset(
        dataset,
        records=(
            _replace_record_values(
                dataset.records[0],
                observables={"s_parameter": unavailable},
            ),
            dataset.records[1],
            dataset.records[1].model_copy(
                update={"logical_point_id": "point-2", "point_index": 2},
            ),
        ),
    )

    projection = project_measurement_trace_preview(
        dataset,
        "s_parameter",
        max_series=2,
        max_samples=4,
    )

    assert [series.point_index for series in projection.series] == [1, 2]
    assert projection.source_sample_count == 6
    assert projection.returned_sample_count == 4
    assert projection.samples_reduced


def _replace_schema(
    schema: MeasurementDatasetSchema,
    **updates: object,
) -> MeasurementDatasetSchema:
    variables = updates.get("variables")
    if variables is not None and "variable_groups" not in updates:
        group_ids: dict[str, None] = {}
        for variable in cast("tuple[MeasurementVariable, ...]", variables):
            if variable.recording_group_id is not None:
                group_ids.setdefault(variable.recording_group_id, None)
        updates["variable_groups"] = tuple(
            MeasurementVariableGroup(id=group_id) for group_id in group_ids
        )
    return MeasurementDatasetSchema.model_validate(
        {**schema.model_dump(mode="python"), **updates}
    )


def _replace_dataset(
    dataset: MeasurementDataset,
    *,
    dataset_schema: MeasurementDatasetSchema | None = None,
    records: tuple[MeasurementRecord, ...] | None = None,
) -> MeasurementDataset:
    return MeasurementDataset(
        dataset_schema=dataset.dataset_schema
        if dataset_schema is None
        else dataset_schema,
        records=dataset.records if records is None else records,
        metadata=dataset.metadata,
    )


def _replace_record_values(
    record: MeasurementRecord,
    *,
    coordinates: Mapping[str, MeasurementValue] | None = None,
    observables: Mapping[str, MeasurementValue] | None = None,
) -> MeasurementRecord:
    return MeasurementRecord(
        run_id=record.run_id,
        logical_point_id=record.logical_point_id,
        point_index=record.point_index,
        coordinates={**record.coordinates, **(coordinates or {})},
        observables={**record.observables, **(observables or {})},
        acquisition_evidence=record.acquisition_evidence,
        metadata=record.metadata,
    )


def _trace_dataset() -> MeasurementDataset:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        point_domain=MeasurementPointCloudPointDomain(columns=[]),
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
                        values=(4.9e9, 5.0e9, 5.1e9),
                    )
                },
                observables={
                    "s_parameter": MeasurementArray.create(
                        dtype="complex128",
                        unit="ratio",
                        values=(
                            complex(1.0, 0.0),
                            complex(0.2, -0.1),
                            complex(0.9, 0.1),
                        ),
                    )
                },
            )
            for point_index in range(2)
        ],
    )
