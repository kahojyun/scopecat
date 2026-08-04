from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.kernel.value_types import Int, Scalar
from scopecat.program.definitions import (
    ExperimentDef,
    ExperimentInvocation,
)
from scopecat.program.module import ModuleBody, ModuleInterface
from scopecat.program.scans import (
    AxisSpec,
    GridSpec,
    PointPlan,
    PointsSpec,
    RepeatMode,
    ScanValue,
    ValuesScanSource,
    expand_point_plan,
)

_INT = Scalar(Int())


def _axis(axis_id: str, *values: int) -> AxisSpec:
    return AxisSpec(
        id=axis_id,
        value_type=_INT,
        source=ValuesScanSource(values),
    )


def _values(axis: AxisSpec) -> tuple[ScanValue, ...]:
    assert isinstance(axis.source, ValuesScanSource)
    return axis.source.values


def _definition(default_points: PointPlan) -> ExperimentDef:
    return ExperimentDef(
        id="test.point-policy",
        kind="test",
        interface=ModuleInterface(),
        body=ModuleBody(),
        default_points=default_points,
    )


@pytest.mark.parametrize("repeat", [True, 0, -1])
def test_point_repeat_requires_a_positive_non_boolean_integer(
    repeat: int,
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        PointPlan(repeat=repeat)


def test_point_cloud_rejects_snake_traversal() -> None:
    points = PointsSpec((_axis("x", 1, 2),))

    with pytest.raises(ValueError, match="only support forward"):
        PointPlan(points, traversal="snake")


@pytest.mark.parametrize(
    "domain",
    [
        GridSpec((_axis("repeat", 0, 1),)),
        PointsSpec((_axis("repeat", 0, 1),)),
    ],
)
def test_repeated_plan_reserves_the_repeat_coordinate(
    domain: GridSpec | PointsSpec,
) -> None:
    with pytest.raises(ValueError, match=r"reserve.*repeat"):
        PointPlan(domain, repeat=2)


def test_grid_repeat_expands_as_the_fast_or_slow_factor() -> None:
    domain = GridSpec((_axis("x", 1, 2), _axis("y", 10, 20)))

    point_repeat = expand_point_plan(PointPlan(domain, repeat=3))
    sweep_repeat = expand_point_plan(PointPlan(domain, repeat=3, repeat_mode="sweep"))

    assert isinstance(point_repeat, GridSpec)
    assert isinstance(sweep_repeat, GridSpec)
    assert tuple(axis.id for axis in point_repeat.axes) == ("x", "y", "repeat")
    assert tuple(axis.id for axis in sweep_repeat.axes) == ("repeat", "x", "y")
    assert _values(point_repeat.axes[-1]) == (0, 1, 2)
    assert _values(sweep_repeat.axes[0]) == (0, 1, 2)
    repeat_type = point_repeat.axes[-1].value_type.atom
    assert isinstance(repeat_type, Int)
    assert (repeat_type.minimum, repeat_type.maximum) == (0, 2)


@pytest.mark.parametrize(
    ("mode", "expected_ids", "expected_x", "expected_repeat"),
    [
        (
            "point",
            ("x", "y", "repeat"),
            (1, 1, 1, 2, 2, 2),
            (0, 1, 2, 0, 1, 2),
        ),
        (
            "sweep",
            ("repeat", "x", "y"),
            (1, 2, 1, 2, 1, 2),
            (0, 0, 1, 1, 2, 2),
        ),
    ],
)
def test_point_cloud_repeat_expands_rows_in_canonical_mode_order(
    mode: RepeatMode,
    expected_ids: tuple[str, ...],
    expected_x: tuple[int, ...],
    expected_repeat: tuple[int, ...],
) -> None:
    domain = PointsSpec((_axis("x", 1, 2), _axis("y", 10, 20)))

    expanded = expand_point_plan(
        PointPlan(
            domain,
            repeat=3,
            repeat_mode=mode,
        )
    )

    assert isinstance(expanded, PointsSpec)
    by_id = {axis.id: axis for axis in expanded.axes}
    assert tuple(axis.id for axis in expanded.axes) == expected_ids
    assert _values(by_id["x"]) == expected_x
    assert _values(by_id["y"]) == (
        (10, 10, 10, 20, 20, 20) if mode == "point" else (10, 20, 10, 20, 10, 20)
    )
    assert _values(by_id["repeat"]) == expected_repeat


@pytest.mark.parametrize("mode", ["point", "sweep"])
def test_empty_point_cloud_remains_empty_when_repeated(mode: RepeatMode) -> None:
    expanded = expand_point_plan(
        PointPlan(
            PointsSpec(),
            repeat=3,
            repeat_mode=mode,
        )
    )

    assert isinstance(expanded, PointsSpec)
    assert len(expanded.axes) == 1
    assert expanded.axes[0].id == "repeat"
    assert _values(expanded.axes[0]) == ()


def test_invocation_point_policy_edits_are_immutable_and_resettable() -> None:
    original_axis = _axis("x", 1, 2)
    default = PointPlan(
        GridSpec((original_axis,)),
        repeat=2,
        repeat_mode="sweep",
        traversal="snake",
    )
    invocation = ExperimentInvocation(_definition(default))

    repeated = invocation.with_repeat(4)
    traversed = repeated.with_traversal("forward")
    replaced = traversed.grid(_axis("y", 3, 4))

    assert invocation.point_plan == default
    assert repeated.point_plan == PointPlan(
        GridSpec((original_axis,)),
        repeat=4,
        repeat_mode="point",
        traversal="snake",
    )
    assert traversed.point_plan.traversal == "forward"
    assert replaced.point_plan.repeat == 4
    assert replaced.point_plan.repeat_mode == "point"
    assert replaced.point_plan.traversal == "forward"
    assert replaced.reset_points().point_plan == default


def test_replacing_a_snake_grid_with_points_uses_explicit_row_order() -> None:
    x = sc.coordinate("x", sc.ScalarType(sc.IntType()))
    invocation = ExperimentInvocation(
        _definition(
            PointPlan(
                GridSpec((_axis("grid-x", 1, 2),)),
                repeat=2,
                traversal="snake",
            )
        )
    )

    replaced = invocation.points(({x: 2}, {x: 1}))

    assert isinstance(replaced.point_plan.domain, PointsSpec)
    assert replaced.point_plan.repeat == 2
    assert replaced.point_plan.traversal == "forward"


def test_authoring_context_declares_the_complete_point_policy() -> None:
    x = sc.coordinate("x", sc.ScalarType(sc.IntType()))

    @sc.experiment(id="test.authored-point-policy", kind="test")
    def authored(experiment: sc.ExperimentContext) -> None:
        experiment.grid(
            sc.axis(x, [1, 2]),
            repeat=3,
            repeat_mode="sweep",
            traversal="snake",
        )

    invocation = authored()

    assert invocation.point_plan.repeat == 3
    assert invocation.point_plan.repeat_mode == "sweep"
    assert invocation.point_plan.traversal == "snake"
