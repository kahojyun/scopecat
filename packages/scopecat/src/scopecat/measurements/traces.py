"""One-dimensional numeric views over validated measurement datasets."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray

from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementRecord,
    MeasurementUnavailable,
    MeasurementVariable,
)

type TraceCoordinate = int | float
type TraceSample = int | float | complex
type TraceCoordinateArray = NDArray[np.int64] | NDArray[np.float64]
type TraceSampleArray = NDArray[np.int64] | NDArray[np.float64] | NDArray[np.complex128]
type TraceValueMode = Literal["value", "magnitude", "phase", "real", "imag"]
type TraceDownsampling = Literal["even"]


@dataclass(frozen=True, slots=True)
class Trace:
    """One point-local observable indexed by one numeric coordinate."""

    point_index: int
    logical_point_id: str | None
    dimension_id: str
    recording_group_id: str | None
    coordinate_id: str
    observable_id: str
    coordinate_label: str | None
    observable_label: str | None
    coordinate_unit: str | None
    observable_unit: str | None
    x: TraceCoordinateArray
    y: TraceSampleArray


@dataclass(frozen=True, slots=True)
class ProjectedTraceSeries:
    """One response-ready numeric series with its pre-sampling size."""

    point_index: int
    logical_point_id: str | None
    label: str
    x: tuple[TraceCoordinate, ...]
    y: tuple[float, ...]
    source_sample_count: int


@dataclass(frozen=True, slots=True)
class MeasurementTraceProjection:
    """A bounded, display-mode-specific projection of point-local traces."""

    dimension_id: str
    recording_group_id: str | None
    coordinate_id: str
    observable_id: str
    coordinate_label: str | None
    observable_label: str | None
    coordinate_unit: str | None
    observable_unit: str | None
    value_mode: TraceValueMode
    value_unit: str | None
    downsampling: TraceDownsampling
    series: tuple[ProjectedTraceSeries, ...]
    source_sample_count: int
    returned_sample_count: int
    samples_reduced: bool


def measurement_traces(
    dataset: MeasurementDataset,
    observable: str | None = None,
    *,
    coordinate: str | None = None,
    group: str | None = None,
) -> tuple[Trace, ...]:
    """Read one unambiguous point-local trace from every dataset point.

    A recording group is the preferred selector when several acquisitions use
    compatible dimensions; explicit variable ids remain available for custom
    or partially grouped datasets.
    """

    coordinate_variable, observable_variable = _trace_variables(
        dataset.dataset_schema,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    return _measurement_traces(
        dataset.records,
        coordinate_variable,
        observable_variable,
        skip_unavailable=False,
    )


def project_measurement_trace_preview(
    dataset: MeasurementDataset,
    observable: str | None = None,
    *,
    coordinate: str | None = None,
    group: str | None = None,
    max_series: int = 32,
    max_samples: int = 4096,
    value_mode: TraceValueMode | None = None,
    downsampling: TraceDownsampling = "even",
) -> MeasurementTraceProjection:
    """Project a bounded numeric preview without scanning past its series cap.

    ``max_samples`` is one total response budget shared evenly by the returned
    series. Even sampling preserves both endpoints whenever a source trace has
    at least two samples. Unavailable selected points are omitted; callers can
    compare the returned count with their separate domain-selection count.
    """

    if max_series < 1:
        raise ValueError("trace preview max_series must be positive")
    if max_samples < 2:
        raise ValueError("trace preview max_samples must be at least two")
    if downsampling != "even":
        raise ValueError(f"unsupported trace downsampling: {downsampling}")
    coordinate_variable, observable_variable = _trace_variables(
        dataset.dataset_schema,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    series_limit = min(max_series, max_samples // 2)
    traces = tuple(
        trace
        for trace in _measurement_traces(
            dataset.records[:series_limit],
            coordinate_variable,
            observable_variable,
            skip_unavailable=True,
        )
        if trace.y.size > 0
    )
    if observable_variable.dtype == "complex128":
        actual_mode: TraceValueMode = value_mode or "magnitude"
        if actual_mode == "value":
            raise ValueError("complex trace samples require a projected value mode")
    else:
        actual_mode = value_mode or "value"
        if actual_mode != "value":
            raise ValueError("real trace samples require value mode")
    per_series_limit = max_samples if not traces else max(2, max_samples // len(traces))
    projected = tuple(
        _project_trace(
            trace,
            limit=per_series_limit,
            value_mode=actual_mode,
        )
        for trace in traces
    )
    source_sample_count = sum(item.source_sample_count for item in projected)
    returned_sample_count = sum(len(item.y) for item in projected)
    return MeasurementTraceProjection(
        dimension_id=observable_variable.dims[1],
        recording_group_id=(
            coordinate_variable.recording_group_id
            or observable_variable.recording_group_id
        ),
        coordinate_id=coordinate_variable.id,
        observable_id=observable_variable.id,
        coordinate_label=coordinate_variable.label,
        observable_label=observable_variable.label,
        coordinate_unit=coordinate_variable.unit,
        observable_unit=observable_variable.unit,
        value_mode=actual_mode,
        value_unit=("rad" if actual_mode == "phase" else observable_variable.unit),
        downsampling=downsampling,
        series=projected,
        source_sample_count=source_sample_count,
        returned_sample_count=returned_sample_count,
        samples_reduced=returned_sample_count < source_sample_count,
    )


def _trace_variables(
    schema: MeasurementDatasetSchema,
    *,
    coordinate: str | None,
    observable: str | None,
    group: str | None,
) -> tuple[MeasurementVariable, MeasurementVariable]:
    variables = {variable.id: variable for variable in schema.variables}
    coordinate_variable, observable_variable = _select_trace_variables(
        variables,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    coordinate = coordinate_variable.id
    observable = observable_variable.id
    if coordinate_variable.role != "coordinate":
        raise ValueError(f"trace coordinate {coordinate!r} is not a coordinate")
    if observable_variable.role != "observable":
        raise ValueError(f"trace observable {observable!r} is not an observable")
    coordinate_group = coordinate_variable.recording_group_id
    observable_group = observable_variable.recording_group_id
    if (
        coordinate_group is not None
        and observable_group is not None
        and coordinate_group != observable_group
    ):
        raise ValueError(
            "trace coordinate and observable must belong to one recording group"
        )
    if (
        len(coordinate_variable.dims) != 2
        or coordinate_variable.dims != observable_variable.dims
    ):
        raise ValueError(
            "trace coordinate and observable must share one point-local dimension"
        )
    if coordinate_variable.dtype not in {"float64", "int64"}:
        raise ValueError("trace coordinates must be numeric")
    if observable_variable.dtype not in {"float64", "int64", "complex128"}:
        raise ValueError("trace observables must be numeric")
    return coordinate_variable, observable_variable


def _measurement_traces(
    records: Sequence[MeasurementRecord],
    coordinate_variable: MeasurementVariable,
    observable_variable: MeasurementVariable,
    *,
    skip_unavailable: bool,
) -> tuple[Trace, ...]:
    coordinate = coordinate_variable.id
    observable = observable_variable.id
    coordinate_group = coordinate_variable.recording_group_id
    observable_group = observable_variable.recording_group_id
    dimension_id = coordinate_variable.dims[1]
    traces: list[Trace] = []
    for record in records:
        x_value = record.coordinates[coordinate]
        y_value = record.observables[observable]
        if isinstance(x_value, MeasurementUnavailable):
            if skip_unavailable:
                continue
            raise ValueError(
                f"trace coordinate {coordinate!r} is unavailable at point "
                f"{record.point_index}: {x_value.reason}"
            )
        if isinstance(y_value, MeasurementUnavailable):
            if skip_unavailable:
                continue
            raise ValueError(
                f"trace observable {observable!r} is unavailable at point "
                f"{record.point_index}: {y_value.reason}"
            )
        if not isinstance(x_value, MeasurementArray) or not isinstance(
            y_value,
            MeasurementArray,
        ):
            raise ValueError("trace values must be point-local arrays")
        x = _coordinate_values(x_value)
        y = _sample_values(y_value)
        if len(x) != len(y):
            raise ValueError(
                f"trace arrays differ in length at point {record.point_index}"
            )
        traces.append(
            Trace(
                point_index=record.point_index,
                logical_point_id=record.logical_point_id,
                dimension_id=dimension_id,
                recording_group_id=coordinate_group or observable_group,
                coordinate_id=coordinate,
                observable_id=observable,
                coordinate_label=coordinate_variable.label,
                observable_label=observable_variable.label,
                coordinate_unit=coordinate_variable.unit,
                observable_unit=observable_variable.unit,
                x=x,
                y=y,
            )
        )
    return tuple(traces)


def _project_trace(
    trace: Trace,
    *,
    limit: int,
    value_mode: TraceValueMode,
) -> ProjectedTraceSeries:
    indices = _even_sample_indices(len(trace.y), limit)
    return ProjectedTraceSeries(
        point_index=trace.point_index,
        logical_point_id=trace.logical_point_id,
        label=trace.logical_point_id or f"Point {trace.point_index}",
        x=tuple(
            _native_coordinate(cast("np.integer | np.floating", trace.x[index]))
            for index in indices
        ),
        y=tuple(
            _project_sample(
                cast(
                    "np.integer | np.floating | np.complexfloating",
                    trace.y[index],
                ),
                value_mode,
            )
            for index in indices
        ),
        source_sample_count=len(trace.y),
    )


def _even_sample_indices(size: int, limit: int) -> tuple[int, ...]:
    if size <= limit:
        return tuple(range(size))
    return tuple(round(index * (size - 1) / (limit - 1)) for index in range(limit))


def _native_coordinate(value: np.integer | np.floating) -> TraceCoordinate:
    return int(value) if isinstance(value, np.integer) else float(value)


def _project_sample(
    sample: TraceSample | np.integer | np.floating | np.complexfloating,
    mode: TraceValueMode,
) -> float:
    if isinstance(sample, np.integer):
        sample = int(sample)
    elif isinstance(sample, np.floating):
        sample = float(sample)
    elif isinstance(sample, np.complexfloating):
        sample = complex(sample)
    if mode == "value":
        if isinstance(sample, complex):
            raise ValueError("complex trace samples require an explicit display mode")
        return float(sample)
    selected = sample if isinstance(sample, complex) else complex(sample, 0.0)
    if mode == "magnitude":
        return abs(selected)
    if mode == "phase":
        return math.atan2(selected.imag, selected.real)
    if mode == "real":
        return selected.real
    return selected.imag


def _select_trace_variables(
    variables: dict[str, MeasurementVariable],
    *,
    coordinate: str | None,
    observable: str | None,
    group: str | None,
) -> tuple[MeasurementVariable, MeasurementVariable]:
    if group is not None:
        variables = {
            variable_id: variable
            for variable_id, variable in variables.items()
            if variable.recording_group_id == group
        }
        if not variables:
            raise ValueError(f"measurement dataset has no recording group {group!r}")
    if coordinate is not None and observable is not None:
        return (
            _require_variable(variables, coordinate),
            _require_variable(variables, observable),
        )
    selected_coordinate = (
        None if coordinate is None else _require_variable(variables, coordinate)
    )
    selected_observable = (
        None if observable is None else _require_variable(variables, observable)
    )
    coordinates = (
        (selected_coordinate,)
        if selected_coordinate is not None
        else tuple(
            variable
            for variable in variables.values()
            if _is_trace_coordinate(variable)
        )
    )
    observables = (
        (selected_observable,)
        if selected_observable is not None
        else tuple(
            variable
            for variable in variables.values()
            if _is_trace_observable(variable)
        )
    )
    candidates = tuple(
        (coordinate_variable, observable_variable)
        for coordinate_variable in coordinates
        for observable_variable in observables
        if _is_trace_coordinate(coordinate_variable)
        and _is_trace_observable(observable_variable)
        and coordinate_variable.dims == observable_variable.dims
        and (
            coordinate_variable.recording_group_id
            == observable_variable.recording_group_id
        )
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("measurement dataset has no compatible trace variables")
    rendered = ", ".join(
        f"{coordinate_variable.id!r} + {observable_variable.id!r}"
        + (
            ""
            if coordinate_variable.recording_group_id is None
            else f" (group {coordinate_variable.recording_group_id!r})"
        )
        for coordinate_variable, observable_variable in candidates
    )
    raise ValueError(
        "measurement dataset has ambiguous trace variables; select a recording "
        f"group, observable, or coordinate explicitly: {rendered}"
    )


def _is_trace_coordinate(variable: MeasurementVariable) -> bool:
    return (
        variable.role == "coordinate"
        and variable.dtype in {"float64", "int64"}
        and len(variable.dims) == 2
    )


def _is_trace_observable(variable: MeasurementVariable) -> bool:
    return (
        variable.role == "observable"
        and variable.dtype in {"float64", "int64", "complex128"}
        and len(variable.dims) == 2
    )


def _require_variable(
    variables: dict[str, MeasurementVariable],
    variable_id: str,
) -> MeasurementVariable:
    try:
        return variables[variable_id]
    except KeyError as error:
        raise ValueError(
            f"measurement dataset has no variable {variable_id!r}"
        ) from error


def _coordinate_values(value: MeasurementArray) -> TraceCoordinateArray:
    if value.dtype == "int64":
        return cast("NDArray[np.int64]", value.values)
    return cast("NDArray[np.float64]", value.values)


def _sample_values(value: MeasurementArray) -> TraceSampleArray:
    if value.dtype == "complex128":
        return cast("NDArray[np.complex128]", value.values)
    if value.dtype == "int64":
        return cast("NDArray[np.int64]", value.values)
    return cast("NDArray[np.float64]", value.values)


__all__ = ["Trace"]
