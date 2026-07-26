from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.graph.relations.point_domain import (
    POINT_UNIT,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainExpr,
    PointDomainShape,
    PointDomainShapeError,
    PointProduct,
    analyze_point_domain,
    iter_point_axis_linear,
    map_point_axis_centers,
    point_axis_linear,
    point_axis_values,
    point_product,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Int, Scalar, TableColumn

_INT = Scalar(Int())
_SPAN = Quantity(value=2.0, unit="V")


def _axis(column_id: str, count: int) -> PointAxis[object]:
    return point_axis_values(column_id, _INT, tuple(range(count)))


def _shape(root: PointDomainExpr[object]) -> PointDomainShape:
    return analyze_point_domain(root)


def test_axis_sources_and_helpers_have_exact_shapes() -> None:
    values = point_axis_values("values", _INT, (1, 2, 3))
    linear = point_axis_linear("linear", _INT, "center", _SPAN, 5)

    assert values == PointAxis("values", _INT, PointAxisValues((1, 2, 3)))
    assert linear == PointAxis(
        "linear",
        _INT,
        PointAxisLinear(center="center", span=_SPAN, count=5),
    )
    assert _shape(values).cardinality == 3
    assert _shape(linear).cardinality == 5
    assert _shape(linear).value_type.columns == (TableColumn("linear", _INT),)
    with pytest.raises(ValueError, match="at least 2"):
        PointAxisLinear(center="center", span=_SPAN, count=1)
    with pytest.raises(ValueError, match="non-empty"):
        point_axis_values("", _INT, (1,))


def test_point_product_is_flat_ordered_and_unit_normalized() -> None:
    a = _axis("a", 2)
    b = _axis("b", 3)
    c = _axis("c", 4)

    root = point_product(POINT_UNIT, point_product(a, b), c)

    assert isinstance(root, PointProduct)
    assert root.factors == (a, b, c)
    assert point_product() == POINT_UNIT
    assert point_product(POINT_UNIT, a) is a
    assert _shape(root).cardinality == 24


def test_linear_center_paths_and_mapping_are_stable() -> None:
    left = point_axis_linear("left", _INT, "left-center", _SPAN, 2)
    middle = point_axis_values("middle", _INT, (1, 2))
    right = point_axis_linear("right", _INT, "right-center", _SPAN, 2)
    root = point_product(left, middle, right)

    linear = tuple(
        (path, source.center) for path, source in iter_point_axis_linear(root)
    )
    mapped = map_point_axis_centers(root, lambda center, path: (center, path))

    assert linear == (
        (("factors", 0), "left-center"),
        (("factors", 2), "right-center"),
    )
    assert tuple(
        (path, source.center) for path, source in iter_point_axis_linear(mapped)
    ) == tuple((path, (center, path)) for path, center in linear)


def test_duplicate_output_columns_fail_at_the_domain_root() -> None:
    root = point_product(
        point_axis_values("same", _INT, (1,)),
        point_axis_values("same", _INT, (2,)),
    )

    with pytest.raises(PointDomainShapeError) as caught:
        _shape(root)

    assert caught.value.code == "point_domain_duplicate_columns"
    assert caught.value.path == ()


def test_statically_empty_factor_annihilates_exact_product() -> None:
    root = point_product(
        point_axis_values("empty", _INT, ()),
        point_axis_values("other", _INT, (1, 2, 3)),
    )

    assert _shape(root).cardinality == 0


def test_shape_projects_only_columns_and_exact_cardinality() -> None:
    value_type = _shape(point_product(_axis("left", 2), _axis("right", 2))).value_type

    assert value_type.primary_key == ()
    assert not value_type.allow_extra_columns
    assert value_type.min_rows == value_type.max_rows == 4


def test_point_domain_shape_requires_nonnegative_cardinality() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        PointDomainShape((), -1)


@given(
    counts=st.lists(st.integers(min_value=0, max_value=6), max_size=6),
)
def test_generated_product_cardinality_is_multiplicative(
    counts: list[int],
) -> None:
    factors = tuple(_axis(f"c{index}", count) for index, count in enumerate(counts))
    expected = 1
    for count in counts:
        expected *= count

    assert _shape(point_product(*factors)).cardinality == expected


@given(
    counts=st.tuples(
        st.integers(min_value=0, max_value=6),
        st.integers(min_value=0, max_value=6),
        st.integers(min_value=0, max_value=6),
    )
)
def test_generated_product_association_has_one_flat_order(
    counts: tuple[int, int, int],
) -> None:
    first, second, third = (
        _axis(column_id, count)
        for column_id, count in zip(("first", "second", "third"), counts, strict=True)
    )

    assert point_product(point_product(first, second), third) == point_product(
        first,
        point_product(second, third),
    )


def test_direct_noncanonical_product_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least two"):
        PointProduct((_axis("x", 1),))
