"""Measurement dataset content identifiers and bounded point selection."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import islice, product

from scopecat.records.measurement import MeasurementProductGridPointDomain

MEASUREMENT_DATASET_KIND = "measurement_dataset"
RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
MAX_MEASUREMENT_PAGE_SIZE = 500
MAX_MEASUREMENT_SLICE_SIZE = 4096
MAX_MEASUREMENT_TRACE_SERIES = 32
MAX_MEASUREMENT_TRACE_SAMPLES = 4096


def product_grid_slice_indices(
    domain: MeasurementProductGridPointDomain,
    fixed_axis_indices: Mapping[str, int],
    *,
    limit: int = MAX_MEASUREMENT_SLICE_SIZE,
) -> tuple[tuple[int, ...], int]:
    """Return bounded logical ordinals for one product-grid projection."""

    axes = {axis.id: axis for axis in domain.axes}
    unknown = set(fixed_axis_indices) - set(axes)
    if unknown:
        raise ValueError(f"unknown product-grid axes: {', '.join(sorted(unknown))}")
    for axis_id, index in fixed_axis_indices.items():
        if not 0 <= index < axes[axis_id].size:
            raise ValueError(f"product-grid axis index is out of range: {axis_id}")

    selected_ranges = tuple(
        (fixed_axis_indices[axis.id],)
        if axis.id in fixed_axis_indices
        else range(axis.size)
        for axis in domain.axes
    )
    selected_count = 1
    for values in selected_ranges:
        selected_count *= len(values)
    strides: list[int] = []
    for axis_index, _axis in enumerate(domain.axes):
        stride = 1
        for following in domain.axes[axis_index + 1 :]:
            stride *= following.size
        strides.append(stride)
    point_indices = tuple(
        islice(
            (
                sum(
                    index * stride
                    for index, stride in zip(indices, strides, strict=True)
                )
                for indices in product(*selected_ranges)
            ),
            limit,
        )
    )
    return point_indices, selected_count
