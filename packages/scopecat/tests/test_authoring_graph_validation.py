from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat._relations import literal_rows
from scopecat.authoring._graph_validation import verify_assembly_graph
from scopecat.authoring._module_composition import ExperimentAssemblyInternal
from scopecat.authoring._record_intents import observable
from scopecat.authoring._resolution import resolve_experiment
from scopecat.authoring._value_refs import internal_value_ref_from_expression
from scopecat.errors import CheckFailed
from scopecat.problems import ModelLocation, model_location
from scopecat.value_types import Float, Payload, Scalar, Table, TableColumn
from tests.support.authoring import load_config


def _resolve(module: sc.ExperimentModule, tmp_path: Path) -> None:
    invocation = module.template("test.graph", kind="graph").build().bind()
    resolve_experiment(
        invocation,
        workspace=tmp_path,
        config_profile=load_config(),
    )


def test_compute_graph_is_verified_before_parameter_contracts(tmp_path: Path) -> None:
    missing = sc.compute(
        "missing-producer",
        fn=lambda: 1.0,
        output_type=sc.ScalarType(sc.FloatType()),
    )
    missing_parameter = sc.parameter(
        "missing-parameter",
        sc.ScalarType(sc.FloatType()),
    )
    consumer = sc.compute(
        "consumer",
        fn=lambda *, upstream, parameter: (upstream, parameter),
        inputs={
            "upstream": missing.output,
            "parameter": missing_parameter,
        },
        output_type=sc.ScalarType(sc.FloatType()),
    )
    module = sc.module("test.graph.order").computes(consumer).build()

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == "compute_producer_missing"
    assert error.value.problems[0].location == model_location(
        "compute_nodes", "consumer", "inputs", "upstream"
    )


def test_compute_route_requires_a_declared_port(tmp_path: Path) -> None:
    consume = sc.compute(
        "consume-route",
        fn=lambda *, route: route,
        inputs={"route": sc.route("drive")},
        output_type=sc.ScalarType(sc.StringType()),
    )
    module = sc.module("test.graph.route-missing").computes(consume).build()

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == "compute_route_port_missing"
    assert error.value.problems[0].location == model_location(
        "compute_nodes", "consume-route", "inputs", "route"
    )


def test_compute_route_requires_port_capabilities(tmp_path: Path) -> None:
    consume = sc.compute(
        "consume-route",
        fn=lambda *, route: route,
        inputs={"route": sc.route("drive", capabilities=("set_gain",))},
        output_type=sc.ScalarType(sc.StringType()),
    )
    module = (
        sc.module("test.graph.route-capability")
        .resource("drive", requires=("set_frequency",))
        .computes(consume)
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == ("compute_route_capability_missing")
    assert "set_gain" in error.value.problems[0].message


def test_state_rejects_an_unregistered_compute_output(tmp_path: Path) -> None:
    missing = sc.compute(
        "missing-program",
        fn=lambda: {"program": True},
        output_type=sc.ScalarType(sc.PayloadType("pulse-program")),
    )
    module = (
        sc.module("test.graph.state-missing")
        .resource("drive", requires=("play_waveforms",))
        .bind_field(
            "drive",
            capability="play_waveforms",
            field="program",
            value=missing.output,
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == "compute_payload_unknown_node"
    assert error.value.problems[0].location == model_location("bindings", 0, "value")


def test_state_rejects_a_non_payload_compute_output(tmp_path: Path) -> None:
    compute_value = sc.compute(
        "numeric-value",
        fn=lambda: 1.0,
        output_type=sc.ScalarType(sc.FloatType()),
    )
    module = (
        sc.module("test.graph.state-type")
        .resource("drive", requires=("set_gain",))
        .computes(compute_value)
        .bind_field(
            "drive",
            capability="set_gain",
            field="value",
            value=compute_value.output,
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == "compute_payload_unavailable"
    assert error.value.problems[0].location == model_location("bindings", 0, "value")


def test_static_record_schema_is_checked_before_parameter_catalog(
    tmp_path: Path,
) -> None:
    missing_parameter = sc.parameter(
        "missing-record-parameter",
        sc.ScalarType(sc.FloatType()),
    )
    consume = sc.compute(
        "consume-parameter",
        fn=lambda *, value: value,
        inputs={"value": missing_parameter},
        output_type=missing_parameter.value_type,
    )
    duplicate_axis = sc.record_axis("sample", size=2)
    module = (
        sc.module("test.graph.record-schema")
        .computes(consume)
        .record("signal", axes=(duplicate_axis, duplicate_axis))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    assert error.value.problems[0].code == ("experiment_record_axis_duplicate")
    assert error.value.problems[0].location == model_location(
        "records", "signal", "axes"
    )


def test_resource_selector_rejects_execute_stage_value(tmp_path: Path) -> None:
    entity_type = sc.ScalarType(sc.EntityType())
    subject = sc.input("subject", entity_type)
    child = (
        sc.module("test.stage.resource-child")
        .inputs(subject)
        .resource("drive", for_entities=(subject,))
        .build()
    )
    produce_subject = sc.compute(
        "produce-subject",
        fn=lambda: "q0",
        output_type=entity_type,
    )
    parent = (
        sc.module("test.stage.resource-parent")
        .computes(produce_subject)
        .use(child(subject=produce_subject.output))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(parent, tmp_path)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location(
        "resources", "drive", "selector", "entity_inputs", 0
    )
    assert "resource selector" in problem.message
    assert "execute-stage" in problem.message


def test_record_axis_rejects_execute_stage_value(tmp_path: Path) -> None:
    size = sc.compute(
        "axis-size",
        fn=lambda: 2,
        output_type=sc.ScalarType(sc.IntType()),
    )
    module = (
        sc.module("test.stage.record-execute")
        .computes(size)
        .record("signal", axes=(sc.record_axis("sample", size=size.output),))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location(
        "records", "signal", "axes", "sample", "size"
    )


def test_record_axis_rejects_point_rate_value(tmp_path: Path) -> None:
    size = sc.point("axis-size", sc.ScalarType(sc.IntType(minimum=1)))
    module = (
        sc.module("test.stage.record-point")
        .record("signal", axes=(sc.record_axis("sample", size=size),))
        .build()
    )
    invocation = (
        module.template("test.stage.record-point", kind="graph")
        .scan(size, (2, 3))
        .build()
        .bind()
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            invocation,
            workspace=tmp_path,
            config_profile=load_config(),
        )

    problem = error.value.problems[0]
    assert problem.code == "value_rate_unavailable"
    assert problem.location == model_location(
        "records", "signal", "axes", "sample", "size"
    )


def test_state_route_selector_rejects_execute_stage_value(tmp_path: Path) -> None:
    rows = sc.parameter(
        "missing-state-rows",
        sc.TableType(columns=()),
    )
    route_entity = sc.compute(
        "route-entity",
        fn=lambda: "q0",
        output_type=sc.ScalarType(sc.EntityType()),
    )
    module = (
        sc.module("test.stage.state-route")
        .resource("drive", requires=("set_gain",))
        .computes(route_entity)
        .state_each(
            rows,
            resource_port="drive",
            capability="set_gain",
            field="value",
            value=1.0,
            route_entities=(route_entity.output,),
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, tmp_path)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location("state", 0, "route_entities", 0)
    assert "state route selector" in problem.message


def test_direct_compute_edge_is_topologically_ordered(tmp_path: Path) -> None:
    value_type = sc.ScalarType(sc.FloatType())
    producer = sc.compute(
        "producer",
        fn=lambda: 1.0,
        output_type=value_type,
    )
    consumer = sc.compute(
        "consumer",
        fn=lambda *, value: value,
        inputs={"value": producer.output},
        output_type=value_type,
    )
    module = sc.module("test.graph.direct-edge").computes(consumer, producer).build()

    invocation = module.template("test.graph.direct-edge", kind="graph").build().bind()
    resolved = resolve_experiment(
        invocation,
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert [node.id.local_id for node in resolved.experiment.compute_nodes] == [
        "producer",
        "consumer",
    ]


def test_compute_rejects_expression_bound_to_execute_value(tmp_path: Path) -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = sc.input("value", value_type)
    consumer = sc.compute(
        "consumer",
        fn=lambda *, value: value,
        inputs={"value": child_value + 1.0},
        output_type=value_type,
    )
    child = (
        sc.module("test.graph.execute-expression-child")
        .inputs(child_value)
        .computes(consumer)
        .build()
    )
    producer = sc.compute(
        "producer",
        fn=lambda: 1.0,
        output_type=value_type,
    )
    parent = (
        sc.module("test.graph.execute-expression-parent")
        .computes(producer)
        .use(child(value=producer.output))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(parent, tmp_path)

    problem = error.value.problems[0]
    assert problem.code == "execute_value_expression_unsupported"
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.path[-3] == "consumer"
    assert problem.location.path[-2:] == ("inputs", "value")
    assert "direct compute outputs" in problem.message


def test_source_coordinate_collision_ignores_non_coordinate_payload() -> None:
    point_source = internal_value_ref_from_expression(
        literal_rows([{}]),
        Table(
            columns=(TableColumn("payload", Scalar(Payload("point-payload"))),),
        ),
    )

    verify_assembly_graph(
        ExperimentAssemblyInternal(
            point_source=point_source,
            records=(observable("payload"),),
        )
    )


def test_source_coordinate_collision_uses_typed_coordinate_predicate() -> None:
    point_source = internal_value_ref_from_expression(
        literal_rows([{}]),
        Table(columns=(TableColumn("coordinate", Scalar(Float())),)),
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(
            ExperimentAssemblyInternal(
                point_source=point_source,
                records=(observable("coordinate"),),
            )
        )

    assert error.value.problems[0].code == ("experiment_record_coordinate_collision")
