"""One-dimensional numeric views over validated measurement datasets."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementUnavailable,
    MeasurementVariable,
)

type TraceCoordinate = int | float
type TraceSample = int | float | complex


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
    x: tuple[TraceCoordinate, ...]
    y: tuple[TraceSample, ...]


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

    variables = {variable.id: variable for variable in dataset.dataset_schema.variables}
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

    dimension_id = coordinate_variable.dims[1]
    traces: list[Trace] = []
    for record in dataset.records:
        x_value = record.coordinates[coordinate]
        y_value = record.observables[observable]
        if isinstance(x_value, MeasurementUnavailable):
            raise ValueError(
                f"trace coordinate {coordinate!r} is unavailable at point "
                f"{record.point_index}: {x_value.reason}"
            )
        if isinstance(y_value, MeasurementUnavailable):
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


def _coordinate_values(value: MeasurementArray) -> tuple[TraceCoordinate, ...]:
    selected: list[TraceCoordinate] = []
    for item in value.values:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError("trace coordinate array contains a non-numeric value")
        selected.append(item)
    return tuple(selected)


def _sample_values(value: MeasurementArray) -> tuple[TraceSample, ...]:
    selected: list[TraceSample] = []
    for item in value.values:
        if isinstance(item, ComplexComponents):
            selected.append(complex(item.real, item.imag))
        elif not isinstance(item, bool) and isinstance(item, int | float):
            selected.append(item)
        else:
            raise ValueError("trace observable array contains a non-numeric value")
    return tuple(selected)


__all__ = [
    "Trace",
    "TraceCoordinate",
    "TraceSample",
    "measurement_traces",
]
