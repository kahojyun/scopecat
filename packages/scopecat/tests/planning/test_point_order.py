from __future__ import annotations

from scopecat.compiler.point_domain import MaterializedPoint, MaterializedPointDomain
from scopecat.kernel.point_identity import (
    LogicalPointId,
    PointDomainId,
    PointDomainLayout,
)
from scopecat.planning.point_order import point_execution_ordinals


def _domain(
    axis_sizes: tuple[tuple[str, int], ...],
    *,
    point_count: int,
    layout: PointDomainLayout = "product_grid",
) -> MaterializedPointDomain:
    domain_id = PointDomainId("test.point-order", "root")
    return MaterializedPointDomain(
        domain_id,
        tuple(
            MaterializedPoint(LogicalPointId(domain_id, ordinal), {})
            for ordinal in range(point_count)
        ),
        layout=layout,
        axis_sizes=axis_sizes,
    )


def test_forward_traversal_retains_canonical_order() -> None:
    domain = _domain((("x", 2), ("y", 3)), point_count=6)

    assert point_execution_ordinals(
        domain,
        repeat=1,
        repeat_mode="point",
        traversal="forward",
    ) == (0, 1, 2, 3, 4, 5)


def test_snake_traversal_reverses_alternating_grid_rows() -> None:
    domain = _domain((("x", 2), ("y", 3)), point_count=6)

    assert point_execution_ordinals(
        domain,
        repeat=1,
        repeat_mode="point",
        traversal="snake",
    ) == (0, 1, 2, 5, 4, 3)


def test_multidimensional_snake_path_is_continuous() -> None:
    domain = _domain((("x", 2), ("y", 2), ("z", 3)), point_count=12)

    assert point_execution_ordinals(
        domain,
        repeat=1,
        repeat_mode="point",
        traversal="snake",
    ) == (0, 1, 2, 5, 4, 3, 9, 10, 11, 8, 7, 6)


def test_point_repeat_keeps_repeat_samples_adjacent() -> None:
    domain = _domain((("x", 2), ("y", 2), ("repeat", 2)), point_count=8)

    assert point_execution_ordinals(
        domain,
        repeat=2,
        repeat_mode="point",
        traversal="snake",
    ) == (0, 1, 2, 3, 6, 7, 4, 5)


def test_sweep_repeat_alternates_the_snake_path_between_sweeps() -> None:
    domain = _domain((("repeat", 3), ("x", 2), ("y", 3)), point_count=18)

    assert point_execution_ordinals(
        domain,
        repeat=3,
        repeat_mode="sweep",
        traversal="snake",
    ) == (
        0,
        1,
        2,
        5,
        4,
        3,
        9,
        10,
        11,
        8,
        7,
        6,
        12,
        13,
        14,
        17,
        16,
        15,
    )
