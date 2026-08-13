from __future__ import annotations

import pytest

from scopecat.adaptive_domains import DomainProposalAttempt
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Int, Scalar
from scopecat.optimization import DomainOptimizerContext, OptimizationComplete
from scopecat.program.definitions import (
    ExperimentDef,
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


class _Optimizer:
    id = "test.optimizer"

    def propose(
        self,
        context: DomainOptimizerContext,
    ) -> DomainProposalAttempt | OptimizationComplete:
        del context
        return OptimizationComplete()


def _axis(id: str, *values: int) -> AxisSpec:
    return AxisSpec(
        id=id,
        value_type=_INT,
        source=ValuesScanSource(values),
    )


def _definition(
    *,
    default_point_plan: PointPlan | None = None,
) -> ExperimentDef:
    return ExperimentDef(
        id="test.point-plan",
        kind="test",
        interface=ModuleInterface(),
        body=ModuleBody(),
        default_point_plan=default_point_plan or PointPlan(),
    )


def test_complete_point_declarations_replace_each_other_and_reset() -> None:
    x = coordinate("x", _INT)
    y = coordinate("y", _INT)
    default_axis = _axis("x", 1, 2)
    definition = _definition(
        default_point_plan=PointPlan(GridSpec((default_axis,))),
    )
    invocation = ExperimentInvocation(definition, output=None)

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
        _definition(default_point_plan=PointPlan(GridSpec((first_x, y)))),
        output=None,
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
    invocation = ExperimentInvocation(_definition(), output=None).points([{x: 1}])

    with pytest.raises(TypeError, match="point clouds"):
        invocation.with_axis(_axis("y", 2))
    with pytest.raises(TypeError, match="point clouds"):
        invocation.without_axis(x)


def test_adaptive_policy_is_orthogonal_to_initial_point_edits() -> None:
    optimizer = _Optimizer()
    invocation = ExperimentInvocation(_definition(), output=None).adaptive(
        optimizer,
        max_points=7,
    )

    edited = invocation.grid(_axis("x", 1, 2)).with_repeat(2)

    assert edited.point_plan == PointPlan(
        GridSpec((_axis("x", 1, 2),)),
        repeat=2,
    )
    assert edited.adaptive_domain_plan is not None
    assert edited.adaptive_domain_plan.optimizer is optimizer
    assert edited.adaptive_domain_plan.total_point_limit == 7
    assert edited.without_adaptation().adaptive_domain_plan is None


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
