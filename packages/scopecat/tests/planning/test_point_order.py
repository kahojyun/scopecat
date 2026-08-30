from __future__ import annotations

from itertools import product

import pytest

from scopecat.compiler.point_domain import MaterializedPoint, MaterializedPointDomain
from scopecat.kernel.point_identity import (
    LogicalPointId,
    PointDomainId,
    PointDomainLayout,
)
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Int, Scalar
from scopecat.planning.point_order import (
    PointExecutionGroup,
    PointExecutionPlan,
    point_execution_ordinals,
    resolve_point_schedule,
)
from scopecat.program.point_domain import point_axis_values
from scopecat.program.scans import PointGrouping, PointSchedule


def _domain(
    axis_sizes: tuple[tuple[str, int], ...],
    *,
    point_count: int,
    layout: PointDomainLayout = "product_grid",
) -> MaterializedPointDomain:
    domain_id = PointDomainId("test.point-order", "root")
    coordinate_ids = tuple(axis_id for axis_id, _size in axis_sizes)
    rows = tuple(product(*(range(size) for _axis_id, size in axis_sizes)))
    assert len(rows) == point_count
    return MaterializedPointDomain(
        domain_id,
        tuple(
            MaterializedPoint(
                LogicalPointId(domain_id, ordinal),
                dict(zip(coordinate_ids, row, strict=True)),
            )
            for ordinal, row in enumerate(rows)
        ),
        axes=tuple(
            point_axis_values(axis_id, Scalar(Int()), tuple(range(size)))
            for axis_id, size in axis_sizes
        ),
        layout=layout,
    )


def test_forward_traversal_retains_canonical_order() -> None:
    domain = _domain((("x", 2), ("y", 3)), point_count=6)

    assert tuple(
        point_execution_ordinals(
            domain,
            repeat=1,
            repeat_mode="point",
            traversal="forward",
        )
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


def test_point_groups_distinguish_preferred_order_and_durable_cuts() -> None:
    execution = PointExecutionPlan(
        (
            PointExecutionGroup("first", {}, (0, 1)),
            PointExecutionGroup("reordered", {}, (2, 5)),
            PointExecutionGroup("last", {}, (4, 3)),
        ),
        point_count=6,
    )

    assert tuple(group.ordinals for group in execution.remaining_groups()) == (
        (0, 1),
        (2, 5),
        (4, 3),
    )
    assert execution.is_durable_cut(2)
    assert not execution.is_durable_cut(3)
    assert not execution.is_durable_cut(4)
    assert execution.is_durable_cut(6)
    assert tuple(
        group.ordinals for group in execution.remaining_groups(durable_start=2)
    ) == ((2, 5), (4, 3))


def test_grouped_traversal_preserves_snake_order_between_and_within_groups() -> None:
    domain = _domain((("x", 2), ("y", 3)), point_count=6)

    x_schedule = resolve_point_schedule(
        domain,
        repeat=1,
        repeat_mode="point",
        schedule=PointSchedule(
            traversal="snake",
            grouping=PointGrouping("y-within-x", ("y",)),
        ),
    )
    y_schedule = resolve_point_schedule(
        domain,
        repeat=1,
        repeat_mode="point",
        schedule=PointSchedule(
            traversal="snake",
            grouping=PointGrouping("x-within-y", ("x",)),
        ),
    )

    assert tuple(group.ordinals for group in x_schedule.groups) == (
        (0, 1, 2),
        (5, 4, 3),
    )
    assert tuple(group.ordinals for group in y_schedule.groups) == (
        (0, 3),
        (1, 4),
        (2, 5),
    )


def test_point_groups_allow_variable_and_singleton_sizes() -> None:
    execution = PointExecutionPlan(
        (
            PointExecutionGroup("pair", {}, (0, 1)),
            PointExecutionGroup("singleton", {}, (2,)),
        ),
        point_count=3,
    )

    assert execution.group_count == 2
    assert execution.is_durable_cut(2)
    assert execution.is_durable_cut(3)


def test_coordinate_grouping_stably_co_locates_related_rows() -> None:
    domain_id = PointDomainId("test.point-groups", "root")
    rows: tuple[dict[str, CellValue], ...] = (
        {"delay": 0, "state": 0},
        {"delay": 1, "state": 0},
        {"delay": 0, "state": 1},
        {"delay": 1, "state": 1},
    )
    domain = MaterializedPointDomain(
        domain_id,
        tuple(
            MaterializedPoint(LogicalPointId(domain_id, ordinal), row)
            for ordinal, row in enumerate(rows)
        ),
        axes=(
            point_axis_values("delay", Scalar(Int()), (0, 1, 0, 1)),
            point_axis_values("state", Scalar(Int()), (0, 0, 1, 1)),
        ),
        layout="point_cloud",
    )

    schedule = resolve_point_schedule(
        domain,
        repeat=1,
        repeat_mode="point",
        schedule=PointSchedule(
            grouping=PointGrouping(
                id="state-comparison",
                varying_coordinate_ids=("state",),
            ),
        ),
    )

    assert tuple(group.key for group in schedule.groups) == (
        {"delay": 0},
        {"delay": 1},
    )
    assert tuple(group.ordinals for group in schedule.groups) == ((0, 2), (1, 3))
    execution = schedule
    assert not execution.is_durable_cut(2)
    assert execution.is_durable_cut(4)


def test_point_groups_must_still_partition_the_domain() -> None:
    with pytest.raises(ValueError, match="partition every point"):
        PointExecutionPlan(
            (
                PointExecutionGroup("first", {}, (0, 1)),
                PointExecutionGroup("overlap", {}, (1, 2)),
            ),
            point_count=3,
        )
