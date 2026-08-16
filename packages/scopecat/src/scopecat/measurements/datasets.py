"""Measurement dataset content identifiers and bounded point selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementProductGridPointDomain,
)

MEASUREMENT_DATASET_KIND = "measurement_dataset"
MEASUREMENT_DATASET_CODEC = "scopecat.measurement-dataset.v12"
RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
MAX_MEASUREMENT_PAGE_SIZE = 500
MAX_MEASUREMENT_SLICE_SIZE = 4096
MAX_MEASUREMENT_TRACE_SERIES = 32
MAX_MEASUREMENT_TRACE_SAMPLES = 4096


def select_measurement_schema(
    schema: MeasurementDatasetSchema,
    variable_ids: Sequence[str],
) -> MeasurementDatasetSchema:
    """Retain selected durable variables while preserving dataset semantics."""

    selected = set(variable_ids)
    available = {variable.id for variable in schema.variables}
    unknown = selected - available
    if unknown:
        raise ValueError(f"unknown measurement variables: {', '.join(sorted(unknown))}")
    selected_result = schema.result
    if selected_result is not None and any(
        field.variable_id not in selected for field in selected_result.fields
    ):
        selected_result = None
    return MeasurementDatasetSchema.model_validate(
        {
            **schema.model_dump(mode="python"),
            "variables": tuple(
                variable for variable in schema.variables if variable.id in selected
            ),
            "variable_groups": tuple(
                group
                for group in schema.variable_groups
                if any(
                    variable.id in selected and variable.recording_group_id == group.id
                    for variable in schema.variables
                )
            ),
            "primary_coordinates": tuple(
                variable_id
                for variable_id in schema.primary_coordinates
                if variable_id in selected
            ),
            "primary_observables": tuple(
                variable_id
                for variable_id in schema.primary_observables
                if variable_id in selected
            ),
            "result": selected_result,
        }
    )


def product_grid_slice_indices(
    domain: MeasurementProductGridPointDomain,
    fixed_axis_indices: Mapping[str, int],
    *,
    offset: int = 0,
    limit: int = MAX_MEASUREMENT_SLICE_SIZE,
) -> tuple[tuple[int, ...], int]:
    """Return one random-access window of a product-grid projection."""

    if offset < 0:
        raise ValueError("product-grid slice offset must be non-negative")
    if limit <= 0:
        raise ValueError("product-grid slice limit must be positive")

    axes = {axis.id: axis for axis in domain.axes}
    unknown = set(fixed_axis_indices) - set(axes)
    if unknown:
        raise ValueError(f"unknown product-grid axes: {', '.join(sorted(unknown))}")
    for axis_id, index in fixed_axis_indices.items():
        if not 0 <= index < axes[axis_id].size:
            raise ValueError(f"product-grid axis index is out of range: {axis_id}")

    selected_sizes = tuple(
        1 if axis.id in fixed_axis_indices else axis.size for axis in domain.axes
    )
    selected_count = 1
    for size in selected_sizes:
        selected_count *= size
    if offset > selected_count:
        raise ValueError("product-grid slice offset exceeds its selected point count")

    point_strides = [1] * len(domain.axes)
    point_stride = 1
    for axis_index in range(len(domain.axes) - 1, -1, -1):
        point_strides[axis_index] = point_stride
        point_stride *= domain.axes[axis_index].size

    selected_strides = [1] * len(domain.axes)
    selected_stride = 1
    for axis_index in range(len(domain.axes) - 1, -1, -1):
        selected_strides[axis_index] = selected_stride
        if domain.axes[axis_index].id not in fixed_axis_indices:
            selected_stride *= domain.axes[axis_index].size

    point_indices = tuple(
        sum(
            (
                fixed_axis_indices[axis.id]
                if axis.id in fixed_axis_indices
                else (selected_ordinal // selected_strides[axis_index]) % axis.size
            )
            * point_strides[axis_index]
            for axis_index, axis in enumerate(domain.axes)
        )
        for selected_ordinal in range(offset, min(offset + limit, selected_count))
    )
    return point_indices, selected_count
