from __future__ import annotations

import pytest

from scopecat.measurements.datasets import product_grid_slice_indices
from scopecat.records.measurement import (
    MeasurementPointDomainAxis,
    MeasurementPointDomainRangeSource,
    MeasurementPointDomainValuesSource,
    MeasurementProductGridPointDomain,
    MeasurementScalar,
)


def test_product_grid_slice_indices_support_deep_random_access_windows() -> None:
    domain = MeasurementProductGridPointDomain(
        axes=[
            _axis("x", 2),
            _axis("y", 3),
            _axis("bias", 2),
        ]
    )

    indices, selected_count = product_grid_slice_indices(
        domain,
        {"bias": 1},
        offset=3,
        limit=2,
    )

    assert indices == (7, 9)
    assert selected_count == 6


def test_product_grid_slice_indices_do_not_scan_a_large_window_prefix() -> None:
    domain = MeasurementProductGridPointDomain(
        axes=[
            _range_axis("x", 1_000_000),
            _range_axis("y", 3),
            _range_axis("bias", 2),
        ]
    )

    indices, selected_count = product_grid_slice_indices(
        domain,
        {"bias": 1},
        offset=2_500_000,
        limit=2,
    )

    assert indices == (5_000_001, 5_000_003)
    assert selected_count == 3_000_000


def test_product_grid_slice_indices_fix_first_middle_and_multiple_axes() -> None:
    domain = MeasurementProductGridPointDomain(
        axes=[
            _axis("x", 2),
            _axis("y", 3),
            _axis("bias", 2),
        ]
    )

    assert product_grid_slice_indices(domain, {"x": 1}) == (
        (6, 7, 8, 9, 10, 11),
        6,
    )
    assert product_grid_slice_indices(domain, {"y": 1, "bias": 0}) == (
        (2, 8),
        2,
    )


def test_product_grid_slice_indices_handle_an_empty_axis() -> None:
    domain = MeasurementProductGridPointDomain(axes=[_axis("x", 2), _axis("empty", 0)])

    assert product_grid_slice_indices(domain, {}) == ((), 0)


def test_product_grid_slice_indices_reject_unknown_and_out_of_range_axes() -> None:
    domain = MeasurementProductGridPointDomain(axes=[_axis("x", 2)])

    with pytest.raises(ValueError, match="unknown product-grid axes"):
        product_grid_slice_indices(domain, {"missing": 0})
    with pytest.raises(ValueError, match="out of range"):
        product_grid_slice_indices(domain, {"x": 2})
    with pytest.raises(ValueError, match="offset exceeds"):
        product_grid_slice_indices(domain, {}, offset=3)


def _axis(axis_id: str, size: int) -> MeasurementPointDomainAxis:
    return MeasurementPointDomainAxis(
        id=axis_id,
        size=size,
        source=MeasurementPointDomainValuesSource(
            values=[
                MeasurementScalar.create(dtype="int64", value=index)
                for index in range(size)
            ]
        ),
    )


def _range_axis(axis_id: str, size: int) -> MeasurementPointDomainAxis:
    return MeasurementPointDomainAxis(
        id=axis_id,
        size=size,
        source=MeasurementPointDomainRangeSource(
            start=MeasurementScalar.create(dtype="int64", value=0),
            stop=MeasurementScalar.create(dtype="int64", value=size - 1),
        ),
    )
