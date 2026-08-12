from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import product

import pytest

import scopecat.measurements.datasets as datasets
from scopecat.measurements.datasets import product_grid_slice_indices
from scopecat.records.measurement import (
    MeasurementPointDomainAxis,
    MeasurementPointDomainValuesSource,
    MeasurementProductGridPointDomain,
    MeasurementScalar,
)


def test_product_grid_slice_indices_preserve_authored_product_order_without_full_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = MeasurementProductGridPointDomain(
        axes=[
            _axis("x", 2),
            _axis("y", 3),
            _axis("bias", 2),
        ]
    )

    def fail_after_limit(
        *ranges: Iterable[int],
    ) -> Iterator[tuple[int, ...]]:
        for offset, indices in enumerate(product(*ranges)):
            if offset == 4:
                raise AssertionError("slice selection enumerated beyond its limit")
            yield indices

    with monkeypatch.context() as patch:
        patch.setattr(datasets, "product", fail_after_limit)
        indices, selected_count = product_grid_slice_indices(
            domain,
            {"bias": 1},
            limit=4,
        )

    assert indices == (1, 3, 5, 7)
    assert selected_count == 6


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
