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
    *,
    coordinate: str,
    observable: str,
) -> tuple[Trace, ...]:
    """Select a compatible coordinate and observable from every dataset point."""

    variables = {variable.id: variable for variable in dataset.dataset_schema.variables}
    coordinate_variable = _require_variable(variables, coordinate)
    observable_variable = _require_variable(variables, observable)
    if coordinate_variable.role != "coordinate":
        raise ValueError(f"trace coordinate {coordinate!r} is not a coordinate")
    if observable_variable.role != "observable":
        raise ValueError(f"trace observable {observable!r} is not an observable")
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
