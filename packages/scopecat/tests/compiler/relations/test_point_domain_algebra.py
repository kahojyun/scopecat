from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDependentProduct,
    PointDomainAnalysis,
    PointDomainExpr,
    PointDomainShape,
    PointDomainShapeError,
    PointProduct,
    PointRows,
    PointZip,
    analyze_point_domain,
    iter_point_axis_linear,
    map_point_axis_centers,
    point_axis_linear,
    point_axis_values,
    point_dependent_product,
    point_literal_rows,
    point_product,
    point_zip,
    walk_point_domain,
)
from scopecat.kernel.value_types import Int, Scalar, TableColumn
from scopecat.records.parameter import Quantity

_INT = Scalar(Int())
_SPAN = Quantity(value=2.0, unit="V")


def _rows(column_id: str, count: int) -> PointRows:
    return point_literal_rows(
        (TableColumn(column_id, _INT),),
        tuple((index,) for index in range(count)),
    )


def _analyze(root: PointDomainExpr[object]) -> PointDomainAnalysis:
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
    assert _analyze(values).root.cardinality == 3
    assert _analyze(linear).root.cardinality == 5
    assert _analyze(linear).root.value_type.columns == (TableColumn("linear", _INT),)
    with pytest.raises(ValueError, match="at least 2"):
        PointAxisLinear(center="center", span=_SPAN, count=1)
    with pytest.raises(ValueError, match="non-empty"):
        point_axis_values("", _INT, (1,))


def test_literal_rows_derive_exact_cardinality_from_positional_rows() -> None:
    columns = (TableColumn("a", _INT), TableColumn("b", _INT))
    rows = point_literal_rows(columns, ((1, 2), (3, 4)))

    assert rows == PointRows(columns, ((1, 2), (3, 4)))
    assert _analyze(rows).root.cardinality == 2
    with pytest.raises(ValueError, match="width 1; expected 2"):
        point_literal_rows(columns, ((1,),))


def test_point_product_is_canonical_ordered_and_unit_normalized() -> None:
    a = _rows("a", 2)
    b = _rows("b", 3)
    c = _rows("c", 4)

    root = point_product(POINT_UNIT, point_product(a, b), c)

    assert isinstance(root, PointProduct)
    assert root.factors == (a, b, c)
    assert point_product() == POINT_UNIT
    assert point_product(POINT_UNIT, a) is a
    assert _analyze(root).root.cardinality == 24


def test_dependent_product_is_directional_and_exact() -> None:
    left = _rows("left", 2)
    right = point_axis_linear("right", _INT, "outer-dependent", _SPAN, 3)

    root = point_dependent_product(left, right)

    assert isinstance(root, PointDependentProduct)
    assert root.left is left
    assert root.right is right
    assert point_dependent_product(POINT_UNIT, right) is right
    assert point_dependent_product(left, POINT_UNIT) is left
    assert _analyze(root).root.cardinality == 6


def test_zip_keeps_unit_semantics_and_requires_equal_exact_counts() -> None:
    left = _rows("left", 2)
    right = _rows("right", 2)

    root = point_zip(left, right)

    assert isinstance(root, PointZip)
    assert _analyze(root).root.cardinality == 2
    with pytest.raises(PointDomainShapeError) as caught:
        _analyze(point_zip(POINT_UNIT, _rows("many", 2)))
    assert caught.value.code == "point_domain_zip_cardinality_mismatch"


def test_structural_paths_and_center_mapping_are_stable() -> None:
    left = point_axis_linear("left", _INT, "left-center", _SPAN, 2)
    middle = point_axis_values("middle", _INT, (1, 2))
    right_a = point_axis_linear("right-a", _INT, "right-center", _SPAN, 2)
    right_b = point_axis_values("right-b", _INT, (3, 4))
    root = point_product(
        left,
        point_dependent_product(middle, point_zip(right_a, right_b)),
    )

    paths = tuple(path for path, _node in walk_point_domain(root))
    linear = tuple(
        (path, source.center) for path, source in iter_point_axis_linear(root)
    )
    mapped = map_point_axis_centers(root, lambda center, path: (center, path))

    assert paths == (
        (),
        ("factors", 0),
        ("factors", 1),
        ("factors", 1, "left"),
        ("factors", 1, "right"),
        ("factors", 1, "right", "sources", 0),
        ("factors", 1, "right", "sources", 1),
    )
    assert linear == (
        (("factors", 0), "left-center"),
        (("factors", 1, "right", "sources", 0), "right-center"),
    )
    assert tuple(
        (path, source.center) for path, source in iter_point_axis_linear(mapped)
    ) == tuple((path, (center, path)) for path, center in linear)


def test_duplicate_output_columns_fail_at_the_composition_node() -> None:
    root = point_product(
        point_axis_values("same", _INT, (1,)),
        point_axis_values("same", _INT, (2,)),
    )

    with pytest.raises(PointDomainShapeError) as caught:
        _analyze(root)

    assert caught.value.code == "point_domain_duplicate_columns"
    assert caught.value.path == ()


def test_statically_empty_factor_annihilates_exact_product() -> None:
    root = point_product(
        point_axis_values("empty", _INT, ()),
        point_axis_values("other", _INT, (1, 2, 3)),
    )

    assert _analyze(root).root.cardinality == 0


def test_shape_projects_only_columns_and_exact_cardinality() -> None:
    left = point_literal_rows((TableColumn("left", _INT),), ((1,), (2,)))
    right = point_literal_rows((TableColumn("right", _INT),), ((3,), (4,)))

    product_type = _analyze(point_product(left, right)).root.value_type
    zip_type = _analyze(point_zip(left, right)).root.value_type

    assert product_type.primary_key == ()
    assert zip_type.primary_key == ()
    assert not product_type.allow_extra_columns
    assert not zip_type.allow_extra_columns
    assert product_type.min_rows == product_type.max_rows == 4
    assert zip_type.min_rows == zip_type.max_rows == 2


def test_point_domain_shape_requires_nonnegative_cardinality() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        PointDomainShape((), -1)


@given(
    counts=st.lists(st.integers(min_value=0, max_value=6), max_size=6),
)
def test_generated_product_cardinality_is_multiplicative(
    counts: list[int],
) -> None:
    factors = tuple(
        point_axis_values(f"c{index}", _INT, tuple(range(count)))
        for index, count in enumerate(counts)
    )
    expected = 1
    for count in counts:
        expected *= count

    assert _analyze(point_product(*factors)).root.cardinality == expected


@given(
    counts=st.tuples(
        st.integers(min_value=0, max_value=6),
        st.integers(min_value=0, max_value=6),
        st.integers(min_value=0, max_value=6),
    )
)
def test_generated_product_association_has_one_canonical_order(
    counts: tuple[int, int, int],
) -> None:
    first, second, third = (
        point_axis_values(column_id, _INT, tuple(range(count)))
        for column_id, count in zip(("first", "second", "third"), counts, strict=True)
    )

    assert point_product(point_product(first, second), third) == point_product(
        first,
        point_product(second, third),
    )


@given(
    counts=st.lists(
        st.integers(min_value=0, max_value=6),
        min_size=2,
        max_size=6,
    )
)
def test_generated_zip_accepts_exactly_equal_lengths(counts: list[int]) -> None:
    factors = tuple(
        point_axis_values(f"c{index}", _INT, tuple(range(count)))
        for index, count in enumerate(counts)
    )

    if len(set(counts)) == 1:
        assert _analyze(point_zip(*factors)).root.cardinality == counts[0]
    else:
        with pytest.raises(PointDomainShapeError) as caught:
            _analyze(point_zip(*factors))
        assert caught.value.code == "point_domain_zip_cardinality_mismatch"


def test_direct_noncanonical_nodes_are_rejected() -> None:
    leaf = point_axis_values("x", _INT, (1,))

    with pytest.raises(ValueError, match="at least two"):
        PointProduct((leaf,))
    with pytest.raises(ValueError, match="point unit"):
        PointDependentProduct(POINT_UNIT, leaf)
    with pytest.raises(ValueError, match="at least two"):
        PointZip((leaf,))
