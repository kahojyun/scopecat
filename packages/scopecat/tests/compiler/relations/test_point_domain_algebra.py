from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointCardinality,
    PointDependentProduct,
    PointDomainAnalysis,
    PointDomainShape,
    PointDomainShapeError,
    PointProduct,
    PointRelationRows,
    PointZip,
    analyze_point_domain,
    iter_point_relation_rows,
    map_point_relation_rows,
    point_dependent_product,
    point_product,
    point_rows,
    point_zip,
    walk_point_domain,
)
from scopecat.kernel.value_types import Int, Scalar, Table, TableColumn

_INT = Scalar(Int())


def _table(column_id: str, minimum: int, maximum: int | None) -> Table:
    return Table(
        columns=(TableColumn(column_id, _INT),),
        min_rows=minimum,
        max_rows=maximum,
    )


def _analyze(root):
    return analyze_point_domain(root, leaf_value_type=lambda table, _path: table)


def test_point_product_is_canonical_ordered_and_unit_normalized() -> None:
    a = point_rows(_table("a", 2, 2))
    b = point_rows(_table("b", 3, 3))
    c = point_rows(_table("c", 4, 4))

    root = point_product(POINT_UNIT, point_product(a, b), c)

    assert isinstance(root, PointProduct)
    assert root.factors == (a, b, c)
    assert point_product() == POINT_UNIT
    assert point_product(POINT_UNIT, a) is a
    assert _analyze(root).root.cardinality == PointCardinality.exact(24)


def test_dependent_product_is_directional_and_applies_only_unit_laws() -> None:
    left = point_rows(_table("left", 2, 2))
    right = point_rows(_table("right", 1, 3))

    root = point_dependent_product(left, right)

    assert isinstance(root, PointDependentProduct)
    assert root.left is left
    assert root.right is right
    assert point_dependent_product(POINT_UNIT, right) is right
    assert point_dependent_product(left, POINT_UNIT) is left
    assert _analyze(root).root.cardinality == PointCardinality(2, 6)


def test_zip_keeps_unit_semantics_and_intersects_cardinality() -> None:
    left = point_rows(_table("left", 1, 4))
    right = point_rows(_table("right", 2, None))

    root = point_zip(left, right)

    assert isinstance(root, PointZip)
    assert _analyze(root).root.cardinality == PointCardinality(2, 4)
    with pytest.raises(PointDomainShapeError) as caught:
        _analyze(point_zip(POINT_UNIT, point_rows(_table("many", 2, 2))))
    assert caught.value.code == "point_domain_zip_cardinality_mismatch"


def test_structural_paths_and_leaf_mapping_are_stable() -> None:
    root = point_product(
        point_rows("left"),
        point_dependent_product(
            point_rows("middle"),
            point_zip(point_rows("right-a"), point_rows("right-b")),
        ),
    )

    paths = tuple(path for path, _node in walk_point_domain(root))
    leaves = tuple((path, leaf.rows) for path, leaf in iter_point_relation_rows(root))
    mapped = map_point_relation_rows(root, lambda value, path: (value, path))
    original_ids = tuple(
        leaf.relation_use_id for _path, leaf in iter_point_relation_rows(root)
    )

    assert paths == (
        (),
        ("factors", 0),
        ("factors", 1),
        ("factors", 1, "left"),
        ("factors", 1, "right"),
        ("factors", 1, "right", "sources", 0),
        ("factors", 1, "right", "sources", 1),
    )
    assert leaves == (
        (("factors", 0), "left"),
        (("factors", 1, "left"), "middle"),
        (("factors", 1, "right", "sources", 0), "right-a"),
        (("factors", 1, "right", "sources", 1), "right-b"),
    )
    assert tuple(
        leaf.rows for _path, leaf in iter_point_relation_rows(mapped)
    ) == tuple((value, path) for path, value in leaves)
    assert (
        tuple(leaf.relation_use_id for _path, leaf in iter_point_relation_rows(mapped))
        == original_ids
    )


def test_relation_rows_get_fresh_nominal_use_identities() -> None:
    first = point_rows("same")
    second = point_rows("same")

    assert first.relation_use_id != second.relation_use_id


def test_duplicate_output_columns_fail_at_the_composition_node() -> None:
    root = point_product(
        point_rows(_table("same", 1, 1)),
        point_rows(_table("same", 1, 1)),
    )

    with pytest.raises(PointDomainShapeError) as caught:
        _analyze(root)

    assert caught.value.code == "point_domain_duplicate_columns"
    assert caught.value.path == ()


def test_statically_empty_factor_annihilates_unknown_product_maximum() -> None:
    root = point_product(
        point_rows(_table("empty", 0, 0)),
        point_rows(_table("unknown", 0, None)),
    )

    assert _analyze(root).root.cardinality == PointCardinality.exact(0)


def test_shape_metadata_has_explicit_composition_rules() -> None:
    left_type = Table(
        columns=(TableColumn("left", _INT),),
        primary_key=("left",),
        min_rows=1,
        max_rows=2,
    )
    right_type = Table(
        columns=(TableColumn("right", _INT),),
        primary_key=("right",),
        min_rows=1,
        max_rows=2,
        allow_extra_columns=True,
    )

    product_type = _analyze(
        point_product(point_rows(left_type), point_rows(right_type))
    ).root.value_type
    zip_type = _analyze(
        point_zip(point_rows(left_type), point_rows(right_type))
    ).root.value_type

    assert product_type.primary_key == ("left", "right")
    assert zip_type.primary_key == ("left",)
    assert product_type.allow_extra_columns
    assert zip_type.allow_extra_columns


def test_analysis_construction_and_leaf_adapter_are_runtime_sealed() -> None:
    shape = PointDomainShape(Table(columns=(), min_rows=1, max_rows=1))
    facts = {(): shape}
    analysis = PointDomainAnalysis(root=shape, facts=facts)
    facts.clear()

    assert analysis.facts == {(): shape}
    with pytest.raises(ValueError, match="root fact"):
        PointDomainAnalysis(root=shape, facts={})
    with pytest.raises(PointDomainShapeError) as caught:
        analyze_point_domain(
            point_rows("not-table"),
            leaf_value_type=lambda _leaf, _path: "not-table",  # type: ignore[return-value]
        )
    assert caught.value.code == "point_domain_leaf_not_table"


@given(
    counts=st.lists(st.integers(min_value=0, max_value=6), max_size=6),
)
def test_generated_product_cardinality_is_multiplicative(
    counts: list[int],
) -> None:
    factors = tuple(
        point_rows(_table(f"c{index}", count, count))
        for index, count in enumerate(counts)
    )
    expected = 1
    for count in counts:
        expected *= count

    assert _analyze(point_product(*factors)).root.cardinality == (
        PointCardinality.exact(expected)
    )


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
        point_rows(_table(column_id, count, count))
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
        point_rows(_table(f"c{index}", count, count))
        for index, count in enumerate(counts)
    )

    if len(set(counts)) == 1:
        assert _analyze(point_zip(*factors)).root.cardinality == (
            PointCardinality.exact(counts[0])
        )
    else:
        with pytest.raises(PointDomainShapeError) as caught:
            _analyze(point_zip(*factors))
        assert caught.value.code == "point_domain_zip_cardinality_mismatch"


def test_direct_noncanonical_nodes_are_rejected() -> None:
    leaf = PointRelationRows(_table("x", 1, 1))

    with pytest.raises(ValueError, match="at least two"):
        PointProduct((leaf,))
    with pytest.raises(ValueError, match="point unit"):
        PointDependentProduct(POINT_UNIT, leaf)
    with pytest.raises(ValueError, match="at least two"):
        PointZip((leaf,))
