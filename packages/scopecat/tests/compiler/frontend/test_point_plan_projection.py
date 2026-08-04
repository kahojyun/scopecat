from __future__ import annotations

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.program.logical import LogicalProgram
from scopecat.program.point_domain import PointAxisValues
from scopecat.records.run_request import GridDomainRecord, PointCloudDomainRecord

_INT = sc.ScalarType(sc.IntType())


def _axis_values(program: LogicalProgram, axis_id: str) -> tuple[object, ...]:
    axis = next(axis for axis in program.point_domain if axis.id == axis_id)
    source = axis.source
    assert isinstance(source, PointAxisValues)
    return source.values


def test_compile_projects_the_base_grid_and_composes_the_expanded_plan() -> None:
    frequency = sc.coordinate("frequency", _INT)

    @sc.experiment(id="test.repeat-grid", kind="point_plan")
    def repeated(experiment: sc.ExperimentContext) -> None:
        experiment.grid(
            sc.axis(frequency, (1, 2)),
            repeat=2,
            repeat_mode="sweep",
            traversal="snake",
        )

    compiled = compile_invocation(repeated())
    request_plan = compiled.request.point_plan
    program = compiled.program.program

    assert isinstance(request_plan.domain, GridDomainRecord)
    assert [axis.axis_id for axis in request_plan.domain.axes] == ["frequency"]
    assert request_plan.repeat == 2
    assert request_plan.repeat_mode == "sweep"
    assert request_plan.traversal == "snake"
    assert [axis.id for axis in program.point_domain] == ["repeat", "frequency"]
    assert _axis_values(program, "repeat") == (0, 1)
    assert _axis_values(program, "frequency") == (1, 2)
    assert program.point_repeat == 2
    assert program.point_repeat_mode == "sweep"
    assert program.point_traversal == "snake"


def test_compile_expands_point_repeat_within_each_point_cloud_row() -> None:
    x = sc.coordinate("x", _INT)

    @sc.experiment(id="test.repeat-points", kind="point_plan")
    def repeated(experiment: sc.ExperimentContext) -> None:
        experiment.points(
            ({x: 1}, {x: 2}),
            repeat=2,
            repeat_mode="point",
        )

    compiled = compile_invocation(repeated())
    request_plan = compiled.request.point_plan
    program = compiled.program.program

    assert isinstance(request_plan.domain, PointCloudDomainRecord)
    assert request_plan.domain.columns == ["x"]
    assert request_plan.domain.rows == [{"x": 1}, {"x": 2}]
    assert program.point_domain_layout == "point_cloud"
    assert [axis.id for axis in program.point_domain] == ["x", "repeat"]
    assert _axis_values(program, "x") == (1, 1, 2, 2)
    assert _axis_values(program, "repeat") == (0, 1, 0, 1)


def test_synthetic_repeat_satisfies_an_authored_point_dependency() -> None:
    repeat = sc.coordinate("repeat", _INT)

    @sc.experiment(id="test.repeat-dependency", kind="point_plan")
    def repeated(experiment: sc.ExperimentContext) -> None:
        experiment.grid(repeat=2)
        experiment.record(repeat, record_id="observed_repeat")

    compiled = compile_invocation(repeated())
    request_domain = compiled.request.point_plan.domain
    program = compiled.program.program

    assert isinstance(request_domain, GridDomainRecord)
    assert request_domain.axes == []
    assert [axis.id for axis in program.point_domain] == ["repeat"]
    assert tuple(dependency.id for dependency in program.point_dependencies) == (
        "repeat",
    )
