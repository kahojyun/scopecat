from __future__ import annotations

import pytest

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Int, Scalar
from scopecat.program.definitions import (
    ExperimentDef,
    ExperimentInputDef,
    ExperimentInvocation,
    create_experiment_def,
)
from scopecat.program.module import ModuleBody, ModuleInterface
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    GridSpec,
    PointPlan,
    PointsSpec,
    ValuesScanSource,
)
from scopecat.program.values import coordinate, input

_INT = Scalar(Int())


def _axis(id: str, *values: int) -> AxisSpec:
    return AxisSpec(
        id=id,
        value_type=_INT,
        source=ValuesScanSource(values),
    )


def _definition(
    *,
    default_point_plan: PointPlan | None = None,
    inputs: tuple[ExperimentInputDef, ...] = (),
) -> ExperimentDef:
    return ExperimentDef(
        id="test.point-plan",
        kind="test",
        interface=ModuleInterface(),
        body=ModuleBody(),
        inputs=inputs,
        default_point_plan=default_point_plan or PointPlan(),
    )


def test_bind_is_last_write_and_unbind_reinherits_definition_input() -> None:
    definition = _definition(
        inputs=(ExperimentInputDef("shots", _INT, default=2),),
    )

    selected = ExperimentInvocation(definition).bind(shots=3).bind(shots=5)
    inherited = selected.unbind("shots")

    assert selected.input_overrides == {"shots": 5}
    assert inherited.input_overrides == {}
    assert definition.inputs[0].default == 2


def test_complete_point_declarations_replace_each_other_and_reset() -> None:
    x = coordinate("x", _INT)
    y = coordinate("y", _INT)
    default_axis = _axis("x", 1, 2)
    definition = _definition(
        default_point_plan=PointPlan(GridSpec((default_axis,))),
    )
    invocation = ExperimentInvocation(definition)

    grid = invocation.grid(_axis("y", 3, 4))
    assert isinstance(grid.point_plan.domain, GridSpec)
    assert tuple(axis.id for axis in grid.point_plan.domain.axes) == ("y",)

    points = grid.points([{x: 1, y: 2}, {x: 3, y: 4}])
    assert isinstance(points.point_plan.domain, PointsSpec)
    assert tuple(axis.id for axis in points.point_plan.domain.axes) == ("x", "y")

    empty_grid = points.grid()
    assert empty_grid.point_plan == PointPlan(GridSpec())
    assert empty_grid.reset_points().point_plan == definition.default_point_plan


def test_incremental_grid_edits_replace_in_place_append_and_remove() -> None:
    x = coordinate("x", _INT)
    first_x = _axis("x", 1, 2)
    y = _axis("y", 3, 4)
    replacement_x = _axis("x", 5, 6)
    invocation = ExperimentInvocation(
        _definition(default_point_plan=PointPlan(GridSpec((first_x, y))))
    )

    replaced = invocation.with_axis(replacement_x)
    assert isinstance(replaced.point_plan.domain, GridSpec)
    assert replaced.point_plan.domain.axes == (replacement_x, y)

    z = _axis("z", 7, 8)
    appended = replaced.with_axis(z)
    assert isinstance(appended.point_plan.domain, GridSpec)
    assert appended.point_plan.domain.axes == (replacement_x, y, z)

    without_x = appended.without_axis(x)
    assert isinstance(without_x.point_plan.domain, GridSpec)
    assert without_x.point_plan.domain.axes == (y, z)
    assert without_x.without_axis("z").point_plan == PointPlan(GridSpec((y,)))

    with pytest.raises(ValueError, match="no axis"):
        without_x.without_axis("missing")


def test_point_cloud_rejects_incremental_grid_edits() -> None:
    x = coordinate("x", _INT)
    invocation = ExperimentInvocation(_definition()).points([{x: 1}])

    with pytest.raises(TypeError, match="point clouds"):
        invocation.with_axis(_axis("y", 2))
    with pytest.raises(TypeError, match="point clouds"):
        invocation.without_axis(x)


def test_definition_verification_discovers_inputs_from_point_plan_axes() -> None:
    center = input("center", _INT)
    axis = AxisSpec(
        id="x",
        value_type=_INT,
        source=AroundScanSource(
            center=center,
            span=Quantity(2, "Hz"),
            points=3,
        ),
    )

    definition = create_experiment_def(
        id="test.verified-point-plan",
        kind="test",
        interface=ModuleInterface(),
        body=ModuleBody(),
        default_point_plan=PointPlan(GridSpec((axis,))),
    )

    assert tuple((item.id, item.value_type) for item in definition.inputs) == (
        ("center", _INT),
    )
