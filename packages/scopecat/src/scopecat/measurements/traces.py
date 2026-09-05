"""One-dimensional numeric views over validated measurement datasets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import prod
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray

from scopecat.kernel.entity import EntityRef, entity_identity
from scopecat.records.measurement import (
    EntityAcquisitionEvidence,
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementEntityAcquisition,
    MeasurementPartitionedArray,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementSegmentedArray,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
    measurement_point_axis_values,
)

type TraceCoordinate = int | float
type TraceCoordinateArray = NDArray[np.int64] | NDArray[np.float64]
type TraceSampleArray = NDArray[np.int64] | NDArray[np.float64] | NDArray[np.complex128]
type TraceValueMode = Literal["value", "magnitude", "phase", "real", "imag"]
type TraceDownsampling = Literal["minmax"]
type TraceLayout = Literal["overlay", "small_multiples"]


@dataclass(frozen=True, slots=True)
class Trace:
    """One point-local observable indexed by one numeric coordinate."""

    point_index: int
    logical_point_id: str | None
    label: str
    dimension_id: str
    recording_group_id: str | None
    coordinate_id: str
    observable_id: str
    coordinate_label: str | None
    observable_label: str | None
    coordinate_unit: str | None
    observable_unit: str | None
    entity_index: int | None
    entity: EntityRef | None
    x: TraceCoordinateArray
    y: TraceSampleArray
    source_sample_count: int
    unavailable_reasons: tuple[MeasurementUnavailableReason, ...]
    evidence: InstrumentAcquisitionEvidence | None


@dataclass(frozen=True, slots=True)
class ProjectedTraceSeries:
    """One response-ready numeric series with its pre-sampling size."""

    point_index: int
    logical_point_id: str | None
    label: str
    entity_index: int | None
    entity: EntityRef | None
    x: tuple[TraceCoordinate, ...]
    y: tuple[float, ...]
    source_sample_count: int
    available_sample_count: int
    unavailable_reasons: tuple[MeasurementUnavailableReason, ...]
    evidence: InstrumentAcquisitionEvidence | None


@dataclass(frozen=True, slots=True)
class ProjectedTraceFailure:
    """One selected point/entity series that has no plottable samples."""

    point_index: int
    logical_point_id: str | None
    label: str
    entity_index: int | None
    entity: EntityRef | None
    reasons: tuple[MeasurementUnavailableReason, ...]
    evidence: InstrumentAcquisitionEvidence | None


@dataclass(frozen=True, slots=True)
class MeasurementTraceProjection:
    """A bounded, display-mode-specific projection of point-local traces."""

    dimension_id: str
    recording_group_id: str | None
    coordinate_id: str
    source_coordinate_id: str | None
    observable_id: str
    coordinate_label: str | None
    observable_label: str | None
    coordinate_unit: str | None
    observable_unit: str | None
    entity_dimension_id: str | None
    entity_acquisition: MeasurementEntityAcquisition | None
    selected_entity_count: int
    layout: TraceLayout
    value_mode: TraceValueMode
    value_unit: str | None
    downsampling: TraceDownsampling
    series: tuple[ProjectedTraceSeries, ...]
    failures: tuple[ProjectedTraceFailure, ...]
    source_sample_count: int
    returned_sample_count: int
    samples_reduced: bool


def measurement_traces(
    dataset: MeasurementDataset,
    observable: str | None = None,
    *,
    coordinate: str | None = None,
    group: str | None = None,
    entity_indices: Sequence[int] | None = None,
    entities: Sequence[EntityRef] | None = None,
) -> tuple[Trace, ...]:
    """Read one unambiguous point-local trace from every dataset point.

    ``entities`` selects durable (kind, id) identities in request order; metadata
    is descriptive only. It cannot be combined with ``entity_indices``.

    A recording group is the preferred selector when several acquisitions use
    compatible dimensions; explicit variable ids remain available for custom
    ungrouped datasets.
    """

    (
        coordinate_variable,
        observable_variable,
        entity_dimension,
        sample_dimension,
    ) = _trace_variables(
        dataset.dataset_schema,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    traces, failures = _measurement_traces(
        dataset.dataset_schema,
        dataset.records,
        coordinate_variable,
        observable_variable,
        entity_dimension=entity_dimension,
        sample_dimension=sample_dimension,
        entity_indices=_selected_entity_indices(
            entity_dimension, entity_indices, entities
        ),
        skip_unusable=False,
    )
    if failures:
        failure = failures[0]
        reasons = ", ".join(failure.reasons)
        raise ValueError(f"trace {failure.label} is unavailable: {reasons}")
    return traces


def project_measurement_trace_preview(
    dataset: MeasurementDataset,
    observable: str | None = None,
    *,
    coordinate: str | None = None,
    group: str | None = None,
    max_series: int = 32,
    max_samples: int = 4096,
    value_mode: TraceValueMode | None = None,
    downsampling: TraceDownsampling = "minmax",
    entity_indices: Sequence[int] | None = None,
    entities: Sequence[EntityRef] | None = None,
) -> MeasurementTraceProjection:
    """Project a bounded numeric preview from up to ``max_series`` selections.

    ``entities`` selects (kind, id) identities in request order and returns
    persisted metadata and evidence. It is exclusive with ``entity_indices``.

    ``max_samples`` is one total response budget shared evenly by the returned
    series. Min/max bucket sampling preserves endpoints and narrow extrema.
    Unavailable point/entity selections are retained as bounded failures so the
    caller can explain absent traces and inspect their acquisition evidence.
    """

    if max_series < 1:
        raise ValueError("trace preview max_series must be positive")
    if max_samples < 2:
        raise ValueError("trace preview max_samples must be at least two")
    if downsampling != "minmax":
        raise ValueError(f"unsupported trace downsampling: {downsampling}")
    (
        coordinate_variable,
        observable_variable,
        entity_dimension,
        sample_dimension,
    ) = _trace_variables(
        dataset.dataset_schema,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    series_limit = min(max_series, max_samples // 2)
    selected_entity_indices = _selected_entity_indices(
        entity_dimension, entity_indices, entities
    )
    traces, failures = _measurement_traces(
        dataset.dataset_schema,
        dataset.records,
        coordinate_variable,
        observable_variable,
        entity_dimension=entity_dimension,
        sample_dimension=sample_dimension,
        entity_indices=selected_entity_indices,
        skip_unusable=True,
        limit=series_limit,
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
        dimension_id=sample_dimension.id,
        recording_group_id=observable_variable.recording_group_id,
        coordinate_id=(
            sample_dimension.id
            if coordinate_variable is None
            else coordinate_variable.id
        ),
        source_coordinate_id=(
            None if coordinate_variable is None else coordinate_variable.id
        ),
        observable_id=observable_variable.id,
        coordinate_label=(
            sample_dimension.label
            if coordinate_variable is None
            else coordinate_variable.label
        ),
        observable_label=observable_variable.label,
        coordinate_unit=None
        if coordinate_variable is None
        else coordinate_variable.unit,
        observable_unit=observable_variable.unit,
        entity_dimension_id=None if entity_dimension is None else entity_dimension.id,
        entity_acquisition=observable_variable.entity_acquisition,
        selected_entity_count=len(selected_entity_indices),
        layout=_trace_layout(
            dataset.dataset_schema,
            observable_variable,
            entity_dimension,
        ),
        value_mode=actual_mode,
        value_unit=("rad" if actual_mode == "phase" else observable_variable.unit),
        downsampling=downsampling,
        series=projected,
        failures=failures,
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
) -> tuple[
    MeasurementVariable | None,
    MeasurementVariable,
    MeasurementDimension | None,
    MeasurementDimension,
]:
    variables = {variable.id: variable for variable in schema.variables}
    coordinate_variable, observable_variable = _select_trace_variables(
        variables,
        coordinate=coordinate,
        observable=observable,
        group=group,
    )
    coordinate = None if coordinate_variable is None else coordinate_variable.id
    observable = observable_variable.id
    if coordinate_variable is not None and coordinate_variable.role != "coordinate":
        raise ValueError(f"trace coordinate {coordinate!r} is not a coordinate")
    if observable_variable.role != "observable":
        raise ValueError(f"trace observable {observable!r} is not an observable")
    observable_group = observable_variable.recording_group_id
    if (
        coordinate_variable is not None
        and coordinate_variable.recording_group_id != observable_group
    ):
        raise ValueError(
            "trace coordinate and observable must belong to one recording group"
        )
    if (
        coordinate_variable is not None
        and coordinate_variable.dims != observable_variable.dims
    ):
        raise ValueError(
            "trace coordinate and observable must share point-local dimensions"
        )
    local_dimensions = observable_variable.dims[1:]
    entity_dimensions = tuple(
        dimension
        for dimension in schema.dimensions
        if dimension.kind == "entity" and dimension.id in local_dimensions
    )
    if (
        len(local_dimensions) not in {1, 2}
        or len(entity_dimensions) != len(local_dimensions) - 1
    ):
        raise ValueError(
            "trace variables must have one sample dimension and at most one "
            "entity dimension"
        )
    entity_dimension = entity_dimensions[0] if entity_dimensions else None
    if entity_dimension is not None and entity_dimension.index is None:
        raise ValueError("trace entity dimension requires an indexed entity axis")
    sample_dimension_id = next(
        dimension_id
        for dimension_id in local_dimensions
        if entity_dimension is None or dimension_id != entity_dimension.id
    )
    sample_dimension = next(
        dimension
        for dimension in schema.dimensions
        if dimension.id == sample_dimension_id
    )
    if coordinate_variable is not None and coordinate_variable.dtype not in {
        "float64",
        "int64",
    }:
        raise ValueError("trace coordinates must be numeric")
    if observable_variable.dtype not in {"float64", "int64", "complex128"}:
        raise ValueError("trace observables must be numeric")
    return coordinate_variable, observable_variable, entity_dimension, sample_dimension


def _trace_layout(
    schema: MeasurementDatasetSchema,
    variable: MeasurementVariable,
    entity_dimension: MeasurementDimension | None,
) -> TraceLayout:
    if entity_dimension is None:
        return "overlay"
    sample_dimension_id = next(
        dimension_id
        for dimension_id in variable.dims[1:]
        if dimension_id != entity_dimension.id
    )
    sample_dimension = next(
        dimension
        for dimension in schema.dimensions
        if dimension.id == sample_dimension_id
    )
    return "small_multiples" if sample_dimension.size is None else "overlay"


def _measurement_traces(
    schema: MeasurementDatasetSchema,
    records: Sequence[MeasurementRecord],
    coordinate_variable: MeasurementVariable | None,
    observable_variable: MeasurementVariable,
    *,
    entity_dimension: MeasurementDimension | None,
    sample_dimension: MeasurementDimension,
    entity_indices: Sequence[int | None],
    skip_unusable: bool,
    limit: int | None = None,
) -> tuple[tuple[Trace, ...], tuple[ProjectedTraceFailure, ...]]:
    coordinate = None if coordinate_variable is None else coordinate_variable.id
    observable = observable_variable.id
    coordinate_group = observable_variable.recording_group_id
    dimension_id = sample_dimension.id
    traces: list[Trace] = []
    failures: list[ProjectedTraceFailure] = []
    inspected = 0
    point_labels = tuple(_trace_point_label(schema, record) for record in records)
    point_label_counts = Counter(point_labels)
    for record, base_point_label in zip(records, point_labels, strict=True):
        point_label = (
            base_point_label
            if point_label_counts[base_point_label] == 1
            else f"{base_point_label} · Point {record.point_index}"
        )
        y_value = record.observables[observable]
        for entity_index in entity_indices:
            if limit is not None and inspected == limit:
                return tuple(traces), tuple(failures)
            inspected += 1
            entity = _trace_entity(entity_dimension, entity_index)
            label = _trace_series_label(point_label, entity)
            evidence = _trace_evidence(record, observable, entity_index)
            y_part = _local_trace_array(
                y_value,
                observable_variable,
                entity_dimension,
                entity_index,
            )
            x_part = (
                _synthetic_trace_coordinate(y_part)
                if coordinate_variable is None
                else _local_trace_array(
                    record.coordinates[coordinate_variable.id],
                    coordinate_variable,
                    entity_dimension,
                    entity_index,
                )
            )
            reasons = tuple(dict.fromkeys((*x_part.reasons, *y_part.reasons)))
            if x_part.values is None or y_part.values is None:
                if not skip_unusable:
                    reason = reasons[0] if reasons else "invalid"
                    raise ValueError(
                        f"trace observable {observable!r} is unavailable at point "
                        f"{record.point_index}: {reason}"
                    )
                failures.append(
                    ProjectedTraceFailure(
                        point_index=record.point_index,
                        logical_point_id=record.logical_point_id,
                        label=label,
                        entity_index=entity_index,
                        entity=entity,
                        reasons=reasons or ("invalid",),
                        evidence=evidence,
                    )
                )
                continue
            if len(x_part.values) != len(y_part.values):
                raise ValueError(
                    f"trace arrays differ in length at point {record.point_index}"
                )
            valid = np.logical_and(x_part.valid, y_part.valid)
            if not np.any(valid):
                if not skip_unusable:
                    reason = reasons[0] if reasons else "invalid"
                    raise ValueError(
                        f"trace observable {observable!r} is unavailable at point "
                        f"{record.point_index}: {reason}"
                    )
                failures.append(
                    ProjectedTraceFailure(
                        point_index=record.point_index,
                        logical_point_id=record.logical_point_id,
                        label=label,
                        entity_index=entity_index,
                        entity=entity,
                        reasons=reasons or ("invalid",),
                        evidence=evidence,
                    )
                )
                continue
            x = _readonly_selected(x_part.values, valid)
            y = _readonly_selected(y_part.values, valid)
            traces.append(
                Trace(
                    point_index=record.point_index,
                    logical_point_id=record.logical_point_id,
                    label=label,
                    dimension_id=dimension_id,
                    recording_group_id=coordinate_group,
                    coordinate_id=dimension_id if coordinate is None else coordinate,
                    observable_id=observable,
                    coordinate_label=(
                        sample_dimension.label
                        if coordinate_variable is None
                        else coordinate_variable.label
                    ),
                    observable_label=observable_variable.label,
                    coordinate_unit=(
                        None
                        if coordinate_variable is None
                        else coordinate_variable.unit
                    ),
                    observable_unit=observable_variable.unit,
                    entity_index=entity_index,
                    entity=entity,
                    x=cast("TraceCoordinateArray", x),
                    y=y,
                    source_sample_count=len(y_part.values),
                    unavailable_reasons=reasons,
                    evidence=evidence,
                )
            )
    return tuple(traces), tuple(failures)


@dataclass(frozen=True, slots=True)
class _LocalTraceArray:
    values: TraceSampleArray | None
    valid: NDArray[np.bool_]
    reasons: tuple[MeasurementUnavailableReason, ...]


def _selected_entity_indices(
    dimension: MeasurementDimension | None,
    requested: Sequence[int] | None,
    entities: Sequence[EntityRef] | None = None,
) -> tuple[int | None, ...]:
    if requested is not None and entities is not None:
        raise ValueError("trace selection accepts either entities or entity indices")
    if dimension is None:
        if entities is not None:
            raise ValueError("trace entities require an entity trace axis")
        if requested is not None:
            raise ValueError("trace entity indices require an entity trace axis")
        return (None,)
    assert dimension.index is not None
    if entities is not None:
        identities = tuple(entity_identity(entity) for entity in entities)
        if not identities:
            raise ValueError("trace entities must not be empty")
        if len(identities) != len(set(identities)):
            raise ValueError("trace entity identities must be unique")
        positions = {
            entity_identity(entity): index
            for index, entity in enumerate(dimension.index.values)
        }
        unknown = tuple(
            identity for identity in identities if identity not in positions
        )
        if unknown:
            raise ValueError(f"unknown trace entity identities: {unknown}")
        return tuple(positions[identity] for identity in identities)
    if requested is None:
        return tuple(range(len(dimension.index.values)))
    selected = tuple(requested)
    if len(selected) != len(set(selected)):
        raise ValueError("trace entity indices must be unique")
    if any(index < 0 or index >= len(dimension.index.values) for index in selected):
        raise ValueError("trace entity index is out of range")
    return selected


def _trace_entity(
    dimension: MeasurementDimension | None,
    entity_index: int | None,
) -> EntityRef | None:
    if dimension is None:
        return None
    assert dimension.index is not None and entity_index is not None
    return dimension.index.values[entity_index]


def _local_trace_array(
    value: MeasurementValue,
    variable: MeasurementVariable,
    entity_dimension: MeasurementDimension | None,
    entity_index: int | None,
) -> _LocalTraceArray:
    if isinstance(value, MeasurementUnavailable):
        return _LocalTraceArray(
            values=None,
            valid=np.asarray((), dtype=np.bool_),
            reasons=(value.reason,),
        )
    if isinstance(value, MeasurementSegmentedArray):
        if entity_dimension is None or entity_index is None:
            raise ValueError("segmented trace values require an entity selection")
        entity_axis = variable.dims[1:].index(entity_dimension.id)
        if entity_axis != 0:
            raise ValueError(
                "segmented trace values require the entity-first local layout"
            )
        segment = value.segments[entity_index]
        return _local_segment_array(segment)
    if isinstance(value, MeasurementPartitionedArray):
        value = value.materialize()
    if not isinstance(value, MeasurementArray):
        raise ValueError("trace values must be point-local arrays")
    entity_axis = (
        None
        if entity_dimension is None
        else variable.dims[1:].index(entity_dimension.id)
    )
    raw_values = cast("TraceSampleArray", value.values)
    if entity_axis is None:
        values = raw_values
    else:
        assert entity_index is not None
        values = cast(
            "TraceSampleArray",
            np.take(raw_values, entity_index, axis=entity_axis),
        )
    if value.availability is None:
        valid = np.ones(values.shape, dtype=np.bool_)
    elif entity_axis is None:
        valid = value.availability.valid
    else:
        assert entity_index is not None
        valid = cast(
            "NDArray[np.bool_]",
            np.take(
                value.availability.valid,
                entity_index,
                axis=entity_axis,
            ),
        )
    if values.ndim != 1:
        raise ValueError("one selected trace must be one-dimensional")
    return _LocalTraceArray(
        values=values,
        valid=np.asarray(valid, dtype=np.bool_),
        reasons=_array_unavailable_reasons(value, entity_axis, entity_index),
    )


def _synthetic_trace_coordinate(value: _LocalTraceArray) -> _LocalTraceArray:
    if value.values is None:
        return _LocalTraceArray(
            values=None,
            valid=np.asarray((), dtype=np.bool_),
            reasons=(),
        )
    coordinate = np.arange(len(value.values), dtype=np.int64)
    coordinate.setflags(write=False)
    return _LocalTraceArray(
        values=coordinate,
        valid=np.ones(coordinate.shape, dtype=np.bool_),
        reasons=(),
    )


def _local_segment_array(
    value: MeasurementArray | MeasurementUnavailable,
) -> _LocalTraceArray:
    if isinstance(value, MeasurementUnavailable):
        return _LocalTraceArray(
            values=None,
            valid=np.asarray((), dtype=np.bool_),
            reasons=(value.reason,),
        )
    if value.values.ndim != 1:
        raise ValueError("one selected trace segment must be one-dimensional")
    return _LocalTraceArray(
        values=cast("TraceSampleArray", value.values),
        valid=(
            np.ones(value.shape, dtype=np.bool_)
            if value.availability is None
            else value.availability.valid
        ),
        reasons=_array_unavailable_reasons(value, None, None),
    )


def _array_unavailable_reasons(
    value: MeasurementArray,
    entity_axis: int | None,
    entity_index: int | None,
) -> tuple[MeasurementUnavailableReason, ...]:
    if value.availability is None:
        return ()
    if entity_axis is None:
        return tuple(
            dict.fromkeys(group.reason for group in value.availability.unavailable)
        )
    assert entity_index is not None
    selected: list[MeasurementUnavailableReason] = []
    for group in value.availability.unavailable:
        coordinates = np.unravel_index(
            np.asarray(group.flat_indices, dtype=np.intp),
            value.shape,
        )
        matches = cast(
            "NDArray[np.bool_]",
            coordinates[entity_axis] == entity_index,
        )
        if bool(np.any(matches)):
            selected.append(group.reason)
    return tuple(dict.fromkeys(selected))


def _trace_evidence(
    record: MeasurementRecord,
    observable_id: str,
    entity_index: int | None,
) -> InstrumentAcquisitionEvidence | None:
    evidence = record.acquisition_evidence.for_variable(observable_id)
    if isinstance(evidence, EntityAcquisitionEvidence):
        return None if entity_index is None else evidence.values[entity_index]
    return evidence


def _readonly_selected(
    values: TraceSampleArray,
    valid: NDArray[np.bool_],
) -> TraceSampleArray:
    if np.all(valid):
        return values
    selected = values[valid]
    selected.setflags(write=False)
    return selected


def _trace_point_label(
    schema: MeasurementDatasetSchema,
    record: MeasurementRecord,
) -> str:
    variables = {variable.id: variable for variable in schema.variables}
    domain = schema.point_domain
    coordinates: list[str] = []
    if isinstance(domain, MeasurementProductGridPointDomain):
        for axis_index, axis in enumerate(domain.axes):
            stride = prod(item.size for item in domain.axes[axis_index + 1 :])
            value_index = (record.point_index // stride) % axis.size
            value = measurement_point_axis_values(axis)[value_index]
            if value is not None:
                variable = variables.get(axis.id)
                coordinates.append(
                    _trace_coordinate_label(
                        variable.label if variable is not None else None,
                        axis.id,
                        value,
                    )
                )
    else:
        for column in domain.columns:
            value = record.coordinates.get(column.id)
            if not isinstance(value, MeasurementScalar):
                continue
            variable = variables.get(column.id)
            coordinates.append(
                _trace_coordinate_label(
                    variable.label if variable is not None else None,
                    column.id,
                    value,
                )
            )
    return " · ".join(coordinates) if coordinates else f"Point {record.point_index}"


def _trace_coordinate_label(
    label: str | None,
    coordinate_id: str,
    value: MeasurementScalar,
) -> str:
    name = label or _display_identifier(coordinate_id)
    rendered = _trace_scalar_label(value)
    return f"{name} {rendered}"


def _trace_scalar_label(value: MeasurementScalar) -> str:
    scalar = value.value
    if isinstance(scalar, bool):
        rendered = "True" if scalar else "False"
    elif isinstance(scalar, int):
        rendered = str(scalar)
    elif isinstance(scalar, float):
        rendered = format(scalar, ".6g")
    elif isinstance(scalar, complex):
        sign = "-" if scalar.imag < 0 else "+"
        rendered = (
            f"{format(scalar.real, '.6g')} {sign} {format(abs(scalar.imag), '.6g')}i"
        )
    else:
        rendered = scalar
    return f"{rendered} {value.unit}" if value.unit is not None else rendered


def _display_identifier(identifier: str) -> str:
    words = identifier.replace("-", " ").replace("_", " ").replace("/", " ").split()
    return " ".join(f"{word[:1].upper()}{word[1:]}" for word in words)


def _trace_series_label(point_label: str, entity: EntityRef | None) -> str:
    if entity is None:
        return point_label
    metadata_label = entity.metadata.get("label")
    entity_label = metadata_label if isinstance(metadata_label, str) else entity.id
    return f"{point_label} · {entity_label}"


def _project_trace(
    trace: Trace,
    *,
    limit: int,
    value_mode: TraceValueMode,
) -> ProjectedTraceSeries:
    projected_values = _project_samples(trace.y, value_mode)
    indices = _minmax_sample_indices(projected_values, limit)
    return ProjectedTraceSeries(
        point_index=trace.point_index,
        logical_point_id=trace.logical_point_id,
        label=trace.label,
        entity_index=trace.entity_index,
        entity=trace.entity,
        x=tuple(
            _native_coordinate(cast("np.integer | np.floating", trace.x[index]))
            for index in indices
        ),
        y=tuple(
            cast("np.float64", projected_values[index]).item() for index in indices
        ),
        source_sample_count=trace.source_sample_count,
        available_sample_count=len(trace.y),
        unavailable_reasons=trace.unavailable_reasons,
        evidence=trace.evidence,
    )


def _minmax_sample_indices(
    values: NDArray[np.float64],
    limit: int,
) -> tuple[int, ...]:
    size = values.size
    if size <= limit:
        return tuple(range(size))

    interior_budget = limit - 2
    bucket_count = (interior_budget + 1) // 2
    edges = np.linspace(1, size - 1, bucket_count + 1, dtype=np.int64)
    selected = {0, size - 1}
    remaining_slots = interior_budget
    for start_value, end_value in pairwise(edges):
        start = int(start_value)
        end = int(end_value)
        bucket = values[start:end]
        slots = min(2, remaining_slots)
        if slots == 1:
            positions = np.arange(start, end, dtype=np.float64)
            first = cast("np.float64", values[0]).item()
            last = cast("np.float64", values[-1]).item()
            baseline: NDArray[np.float64] = first + (last - first) * positions / (
                size - 1
            )
            selected.add(start + int(np.argmax(np.abs(bucket - baseline))))
        else:
            selected.add(start + int(np.argmin(bucket)))
            selected.add(start + int(np.argmax(bucket)))
        remaining_slots -= slots

    for index in _uniform_sample_indices(size, limit):
        if len(selected) == limit:
            break
        selected.add(index)
    if len(selected) < limit:
        for index in range(1, size - 1):
            selected.add(index)
            if len(selected) == limit:
                break
    return tuple(sorted(selected))


def _uniform_sample_indices(size: int, limit: int) -> tuple[int, ...]:
    return tuple(round(index * (size - 1) / (limit - 1)) for index in range(limit))


def _native_coordinate(value: np.integer | np.floating) -> TraceCoordinate:
    return int(value) if isinstance(value, np.integer) else float(value)


def _project_samples(
    samples: TraceSampleArray,
    mode: TraceValueMode,
) -> NDArray[np.float64]:
    if mode == "value":
        return np.asarray(samples, dtype=np.float64)
    if mode == "magnitude":
        selected = np.abs(samples)
    elif mode == "phase":
        selected = np.angle(samples)
    elif mode == "real":
        selected = np.real(samples)
    else:
        selected = np.imag(samples)
    return np.asarray(selected, dtype=np.float64)


def _select_trace_variables(
    variables: dict[str, MeasurementVariable],
    *,
    coordinate: str | None,
    observable: str | None,
    group: str | None,
) -> tuple[MeasurementVariable | None, MeasurementVariable]:
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
        synthetic_observables = tuple(
            variable for variable in observables if _is_trace_observable(variable)
        )
        aligned_coordinates = (
            ()
            if len(synthetic_observables) != 1
            else tuple(
                variable
                for variable in coordinates
                if _is_trace_coordinate(variable)
                and variable.dims == synthetic_observables[0].dims
            )
        )
        if (
            coordinate is None
            and len(aligned_coordinates) == 0
            and len(synthetic_observables) == 1
        ):
            return None, synthetic_observables[0]
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
        and len(variable.dims) in {2, 3}
    )


def _is_trace_observable(variable: MeasurementVariable) -> bool:
    return (
        variable.role == "observable"
        and variable.dtype in {"float64", "int64", "complex128"}
        and len(variable.dims) in {2, 3}
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


__all__ = ["Trace"]
