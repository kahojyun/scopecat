from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.measurements.projection import select_measurement_projection
from scopecat.planning.measurement_projection import (
    project_measurement_catalog,
    project_run_point_catalog,
    project_static_value_record_candidates,
)
from scopecat.planning.point_materialization import materialize_bound_points
from scopecat.records.run_request import PointRowsRecord
from tests.testkit.authoring import bind_invocation, load_config

_INT = sc.ScalarType(sc.IntType())


def test_point_rows_compile_materialize_and_persist_layout() -> None:
    x = sc.coordinate("x", _INT)
    y = sc.coordinate("y", _INT)

    @sc.template(id="test.point-rows", kind="point_rows")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.points(
            (
                {x: 1, y: 10},
                {x: 1, y: 10},
                {x: 3, y: 30},
            )
        )
        experiment.record(x, record_id="observed_x")

    invocation = template()
    compiled = compile_invocation(invocation)

    assert compiled.program.program.point_domain_layout == "point_cloud"
    [request_points] = compiled.request.scans
    assert isinstance(request_points, PointRowsRecord)
    assert request_points.columns == ["x", "y"]
    assert request_points.rows == [
        {"x": 1, "y": 10},
        {"x": 1, "y": 10},
        {"x": 3, "y": 30},
    ]

    bound = bind_invocation(invocation, config_profile=load_config())
    bound_points = materialize_bound_points(bound)
    domain = bound_points.point_domain
    assert domain.layout == "point_cloud"
    assert domain.axis_sizes == (("x", 3), ("y", 3))
    assert [point.row for point in domain.points] == request_points.rows
    assert [point.logical_ordinal for point in domain.points] == [0, 1, 2]
    assert domain.points[0].logical_id != domain.points[1].logical_id

    catalog = project_measurement_catalog(bound_points)
    projection = select_measurement_projection(
        catalog,
        bound.bindings.record_uses,
        static_value_candidates=project_static_value_record_candidates(bound_points),
    )
    run_points = project_run_point_catalog(bound_points).points
    schema = projection.schema_for(run_points)
    assert schema is not None
    assert schema.metadata["point_domain"] == {
        "layout": "point_cloud",
        "axes": [{"id": "x", "size": 3}, {"id": "y", "size": 3}],
    }


def test_empty_point_rows_are_a_zero_point_domain() -> None:
    x = sc.coordinate("x", _INT)
    y = sc.coordinate("y", _INT)

    @sc.template(id="test.empty-point-rows", kind="point_rows")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.points((), coordinates=(x, y))

    invocation = template()
    compiled = compile_invocation(invocation)
    [request_points] = compiled.request.scans
    assert isinstance(request_points, PointRowsRecord)
    assert request_points.columns == ["x", "y"]
    assert request_points.rows == []

    bound = bind_invocation(invocation, config_profile=load_config())
    domain = materialize_bound_points(bound).point_domain
    assert domain.layout == "point_cloud"
    assert domain.points == ()
    assert bound.point_domain.cardinality == 0


def test_point_rows_require_the_same_typed_coordinate_columns() -> None:
    x = sc.coordinate("x", _INT)
    y = sc.coordinate("y", _INT)

    with pytest.raises(ValueError, match="same typed coordinate columns"):
        sc.points(({x: 1, y: 2}, {x: 3}))


def test_point_rows_cannot_be_combined_with_grid_scans() -> None:
    x = sc.coordinate("x", _INT)

    def definition(experiment: sc.ExperimentContext) -> None:
        experiment.scan(sc.axis(x, (1, 2)))
        experiment.points(({x: 3},))

    with pytest.raises(ValueError, match="cannot be combined with scan axes"):
        sc.template(id="test.mixed-point-domain", kind="point_rows")(definition)
