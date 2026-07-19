from __future__ import annotations

from scopecat.compiler.relations.model import grid, linspace, literal_rows, point_col
from scopecat.compiler.relations.point_domain import (
    point_dependent_product,
    point_rows,
)
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.iteration import (
    PointIterationDependent,
    PointIterationLeaf,
    analyze_point_iteration_layout,
)
from scopecat.compiler.typed.point_domain import PointDomain, verify_point_domain
from scopecat.kernel.value_types import Float, Int, Scalar, Table, TableColumn


def test_finite_grid_preserves_fast_and_slow_axis_strides() -> None:
    table_type = Table(
        (TableColumn("slow", Scalar(Int())), TableColumn("fast", Scalar(Int()))),
        min_rows=6,
        max_rows=6,
    )
    domain = PointDomain(
        point_rows(
            verify_table_value_expr(
                grid(slow=[10, 20], fast=[1, 2, 3]),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            )
        )
    )

    layout = analyze_point_iteration_layout(
        verify_point_domain(domain, program_id="finite-grid")
    )

    assert isinstance(layout.root, PointIterationLeaf)
    slow = layout.axis("slow")
    fast = layout.axis("fast")
    assert slow is not None and slow.values == (10, 20) and slow.repeat_each == 3
    assert fast is not None and fast.values == (1, 2, 3) and fast.repeat_each == 1


def test_literal_linspace_is_an_exact_finite_axis() -> None:
    table_type = Table(
        (TableColumn("x", Scalar(Float())),),
        min_rows=3,
        max_rows=3,
    )
    domain = PointDomain(
        point_rows(
            verify_table_value_expr(
                grid(x=linspace(0.0, 1.0, 3)),
                bindings=RelationTypeBindings(),
                expected_type=table_type,
            )
        )
    )

    layout = analyze_point_iteration_layout(
        verify_point_domain(domain, program_id="finite-linspace")
    )

    axis = layout.axis("x")
    assert axis is not None
    assert axis.values == (0.0, 0.5, 1.0)


def test_dependent_product_retains_outer_layout_and_inner_boundary() -> None:
    left_type = Table(
        (TableColumn("center", Scalar(Float())),),
        min_rows=2,
        max_rows=2,
    )
    right_type = Table(
        (TableColumn("offset", Scalar(Float())),),
        min_rows=2,
        max_rows=2,
    )
    left = point_rows(
        verify_table_value_expr(
            literal_rows(({"center": 1.0}, {"center": 2.0})),
            bindings=RelationTypeBindings(),
            expected_type=left_type,
        )
    )
    right = point_rows(
        verify_table_value_expr(
            grid(
                offset=linspace(
                    point_col("center"),
                    point_col("center") + 1.0,
                    2,
                )
            ),
            bindings=RelationTypeBindings(point_row=RowType.from_table(left_type)),
            expected_type=right_type,
        )
    )

    layout = analyze_point_iteration_layout(
        verify_point_domain(
            PointDomain(point_dependent_product(left, right)),
            program_id="dependent-layout",
        )
    )

    assert isinstance(layout.root, PointIterationDependent)
    assert isinstance(layout.root.left, PointIterationLeaf)
    assert isinstance(layout.root.right, PointIterationLeaf)
    assert layout.root.right.axis_ids == ()
    assert layout.root.right.extent == 2
    assert layout.root.extent == 4
    center = layout.axis("center")
    assert center is not None and center.repeat_each == 2


def test_mixed_grid_retains_static_axis_around_opaque_values() -> None:
    left_type = Table(
        (TableColumn("center", Scalar(Float())),),
        min_rows=2,
        max_rows=2,
    )
    right_type = Table(
        (
            TableColumn("slow", Scalar(Float())),
            TableColumn("fast", Scalar(Int())),
        ),
        min_rows=6,
        max_rows=6,
    )
    left = point_rows(
        verify_table_value_expr(
            literal_rows(({"center": 1.0}, {"center": 2.0})),
            bindings=RelationTypeBindings(),
            expected_type=left_type,
        )
    )
    right = point_rows(
        verify_table_value_expr(
            grid(
                slow=linspace(
                    point_col("center"),
                    point_col("center") + 1.0,
                    2,
                ),
                fast=[1, 2, 3],
            ),
            bindings=RelationTypeBindings(point_row=RowType.from_table(left_type)),
            expected_type=right_type,
        )
    )

    layout = analyze_point_iteration_layout(
        verify_point_domain(
            PointDomain(point_dependent_product(left, right)),
            program_id="mixed-grid-layout",
        )
    )

    assert isinstance(layout.root, PointIterationDependent)
    assert isinstance(layout.root.right, PointIterationLeaf)
    assert layout.root.right.extent == 6
    assert layout.root.right.axis_ids == ("fast",)
    fast = layout.axis("fast")
    assert fast is not None
    assert fast.values == (1, 2, 3)
    assert fast.repeat_each == 1
