from __future__ import annotations

from dataclasses import replace

import pytest

import scopecat as sc
import scopecat.compiler.frontend.assembly_verification as assembly_verification
from scopecat.authoring._binding_intents import requires, resource_port
from scopecat.authoring._record_intents import observable
from scopecat.authoring._value_refs import internal_value_ref_from_expression
from scopecat.compiler.frontend.assembly_lowering import validate_assembly_entrypoint
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import (
    compile_prepared_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.semantic.availability import (
    ValueRate,
    ValueStage,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    LiteralValueSource,
    OperationOutputSource,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import ScalarBinarySemantics
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.value_types import Float, Payload, Scalar, Table, TableColumn
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.entity import EntityRef
from tests.testkit.authoring import load_config


def _resolve(module: sc.ExperimentModule) -> None:
    invocation = module.template("test.graph", kind="graph").build().bind()
    resolve_experiment(
        invocation,
        config_profile=load_config(),
    )


def test_compute_graph_is_verified_before_parameter_contracts() -> None:
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
    with pytest.raises(CheckFailed) as error:
        sc.module("test.graph.order").computes(consumer).build()

    assert error.value.problems[0].code == "module_compute_foreign_definition"


def test_compute_route_requires_a_declared_port() -> None:
    consume = sc.compute(
        "consume-route",
        fn=lambda *, route: route,
        inputs={"route": sc.route("drive")},
        output_type=sc.ScalarType(sc.StringType()),
    )
    with pytest.raises(CheckFailed) as error:
        sc.module("test.graph.route-missing").computes(consume).build()

    assert error.value.problems[0].code == "module_resource_undeclared"


def test_compute_route_requires_port_capabilities() -> None:
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
        _resolve(module)

    assert error.value.problems[0].code == ("compute_route_capability_missing")
    assert "set_gain" in error.value.problems[0].message


def test_state_rejects_an_unregistered_compute_output() -> None:
    missing = sc.compute(
        "missing-program",
        fn=lambda: {"program": True},
        output_type=sc.ScalarType(sc.PayloadType("pulse-program")),
    )
    with pytest.raises(CheckFailed) as error:
        (
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

    assert error.value.problems[0].code == "module_compute_foreign_definition"


def test_state_rejects_a_non_payload_compute_output() -> None:
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
        _resolve(module)

    assert error.value.problems[0].code == "compute_payload_unavailable"
    assert error.value.problems[0].location == model_location("bindings", 0, "value")
    assert "numeric-value/outputs/result" in error.value.problems[0].message


def test_compile_rejects_a_table_shaped_plan_state_binding() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )
    module = (
        sc.module("test.graph.table-state-binding")
        .inputs(rows)
        .resource("drive", requires=("set_gain",))
        .bind_field(
            "drive",
            capability="set_gain",
            field="value",
            value=rows,
        )
        .build()
    )
    invocation = (
        module.template("test.graph.table-state-binding", kind="graph")
        .build()
        .bind(rows=({"value": 1.0},))
    )

    with pytest.raises(CheckFailed) as error:
        compile_prepared_invocation(prepare_invocation(invocation))

    problem = error.value.problems[0]
    assert problem.code == "state_binding_value_shape_invalid"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location("bindings", 0, "value")
    assert problem.message == "state binding value must be scalar-shaped"


def test_compile_rejects_a_table_shaped_plan_action_field() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )
    module = (
        sc.module("test.graph.table-action-field")
        .inputs(rows)
        .resource("drive", requires=("set_gain",))
        .action(
            "set-gain",
            resource="drive",
            capability="set_gain",
            fields={"value": rows},
        )
        .build()
    )
    invocation = (
        module.template("test.graph.table-action-field", kind="graph")
        .build()
        .bind(rows=({"value": 1.0},))
    )

    with pytest.raises(CheckFailed) as error:
        compile_prepared_invocation(prepare_invocation(invocation))

    problem = error.value.problems[0]
    assert problem.code == "action_field_value_shape_invalid"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location("actions", 0, "fields", "value")
    assert problem.message == "action field value must be scalar-shaped"


def test_compile_rejects_a_table_shaped_plan_row_region_value() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )
    module = (
        sc.module("test.graph.table-row-region-value")
        .inputs(rows)
        .resource("drive", requires=("set_gain",))
        .state_each(
            rows,
            resource_port="drive",
            capability="set_gain",
            field="value",
            value=rows,
        )
        .build()
    )
    invocation = (
        module.template("test.graph.table-row-region-value", kind="graph")
        .build()
        .bind(rows=({"value": 1.0},))
    )

    with pytest.raises(CheckFailed) as error:
        compile_prepared_invocation(prepare_invocation(invocation))

    problem = error.value.problems[0]
    assert problem.code == "semantic_row_region_value_shape_invalid"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.message == "row region state value must be scalar-shaped"


def test_static_record_schema_is_checked_before_parameter_catalog() -> None:
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
        _resolve(module)

    assert error.value.problems[0].code == ("product_axis_duplicate")
    assert error.value.problems[0].location == model_location(
        "records", "signal", "axes"
    )


def test_resource_selector_rejects_execute_stage_value() -> None:
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
        .use(
            child.instantiate(
                "resource-child",
                subject=produce_subject.output,
            )
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(parent)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location(
        "resources",
        "resource-child",
        "drive",
        "selector",
        "entity_inputs",
        0,
    )
    assert "resource selector" in problem.message
    assert "execute-stage" in problem.message


def test_record_axis_rejects_execute_stage_value() -> None:
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
        _resolve(module)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location(
        "records", "signal", "axes", "sample", "size"
    )


def test_record_axis_rejects_point_rate_value() -> None:
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
            config_profile=load_config(),
        )

    problem = error.value.problems[0]
    assert problem.code == "value_rate_unavailable"
    assert problem.location == model_location(
        "records", "signal", "axes", "sample", "size"
    )


def test_state_route_selector_rejects_execute_stage_value() -> None:
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
        _resolve(module)

    problem = error.value.problems[0]
    assert problem.code == "value_stage_unavailable"
    assert problem.location == model_location("state", 0, "route_entities", 0)
    assert "state route selector" in problem.message


def test_direct_compute_edge_is_topologically_ordered() -> None:
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
    compiled = compile_prepared_invocation(prepare_invocation(invocation))

    assert [
        operation.id.local_id
        for operation in compiled.assembly.source.semantic_graph.operations
    ] == [
        "producer",
        "consumer",
    ]


def test_compile_carries_verified_source_and_normalized_compiler_inputs() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    module = sc.module("test.graph.verified-source").inputs(subject).build()
    invocation = (
        module.template("test.graph.verified-source", kind="graph")
        .build()
        .bind(subject="q0")
    )

    compiled = compile_prepared_invocation(prepare_invocation(invocation))

    assert compiled.request.template_inputs == {"subject": "q0"}
    assert compiled.assembly.source.inputs == {"subject": EntityRef(id="q0")}
    assert (
        compiled.assembly.graph.semantic_graph.graph
        == compiled.assembly.source.semantic_graph
    )


def test_compile_verifies_the_final_assembly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[SemanticExperimentIR] = []
    original_verify = verify_assembly_graph

    def counted_verify(assembly: SemanticExperimentIR):
        calls.append(assembly)
        return original_verify(assembly)

    monkeypatch.setattr(
        assembly_verification,
        "verify_assembly_graph",
        counted_verify,
    )
    module = sc.module("test.graph.single-proof").build()
    invocation = module.template("test.graph.single-proof", kind="graph").build().bind()

    compiled = compile_prepared_invocation(prepare_invocation(invocation))
    resolved = resolve_compiled_invocation(
        compiled,
        environment=validate_config_environment(load_config()),
    )

    assert calls == [compiled.assembly.source]
    assert resolved.experiment.id == "test.graph.single-proof"


@pytest.mark.parametrize(
    ("assembly", "code", "root"),
    (
        (
            SemanticExperimentIR(kind="graph"),
            "experiment_assembly_entrypoint_missing_id",
            "experiment_id",
        ),
        (
            SemanticExperimentIR(experiment_id="test.graph"),
            "experiment_assembly_entrypoint_missing_kind",
            "kind",
        ),
    ),
)
def test_entrypoint_closure_is_an_authoring_problem(
    assembly: SemanticExperimentIR,
    code: str,
    root: str,
) -> None:
    with pytest.raises(CheckFailed) as error:
        validate_assembly_entrypoint(assembly)

    problem = error.value.problems[0]
    assert problem.code == code
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location(root)


def test_resource_selector_requires_scalar_or_series_entity_values() -> None:
    invalid_entity = sc.input("subject", sc.ScalarType(sc.StringType()))
    port = resource_port(
        "drive",
        requires(for_entities=(invalid_entity,)),
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(SemanticExperimentIR(resource_ports=(port,)))

    problem = error.value.problems[0]
    assert problem.code == "module_resource_entity_input_invalid"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location(
        "resources", "drive", "selector", "entity_inputs", 0
    )


def test_execute_scalar_expression_becomes_semantic_operation_graph() -> None:
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
        .use(child.instantiate("expression-child", value=producer.output))
        .build()
    )

    invocation = (
        parent.template("test.graph.execute-expression", kind="graph").build().bind()
    )
    compiled = compile_prepared_invocation(prepare_invocation(invocation))
    graph = compiled.assembly.source.semantic_graph
    definitions = {definition.id: definition for definition in graph.value_defs}
    producer_operation = next(
        operation
        for operation in graph.operations
        if operation.id.local_id == "producer"
    )
    consumer_operation = next(
        operation
        for operation in graph.operations
        if operation.id.local_id == "consumer"
    )
    scalar_operation = next(
        operation
        for operation in graph.operations
        if isinstance(operation.contract.semantics, ScalarBinarySemantics)
    )

    assert scalar_operation.contract.semantics == ScalarBinarySemantics("+")
    scalar_inputs = dict(scalar_operation.inputs)
    scalar_output = dict(scalar_operation.outputs)["result"]
    consumer_input = dict(consumer_operation.inputs)["value"]
    assert isinstance(consumer_input, ValueUse)
    assert consumer_input.value_id == scalar_output

    left = definitions[scalar_inputs["left"].value_id]
    right = definitions[scalar_inputs["right"].value_id]
    result = definitions[scalar_output]
    assert left.source == OperationOutputSource(producer_operation.id)
    assert isinstance(right.source, LiteralValueSource)
    assert right.source.value == 1.0
    assert result.availability.stage is ValueStage.EXECUTE
    assert result.availability.rate is ValueRate.POINT


def test_execute_core_operation_defers_local_implementation_selection() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    produce = sc.compute("produce", fn=lambda: 1.0, output_type=value_type)
    consume = sc.compute(
        "consume",
        fn=lambda *, value: value,
        inputs={"value": produce.output + 1.0},
        output_type=value_type,
    )
    module = (
        sc.module("test.graph.core-implementation").computes(produce, consume).build()
    )
    invocation = (
        module.template("test.graph.core-implementation", kind="graph").build().bind()
    )
    compiled = compile_prepared_invocation(prepare_invocation(invocation))
    scalar_operation = next(
        operation
        for operation in compiled.assembly.source.semantic_graph.operations
        if isinstance(operation.contract.semantics, ScalarBinarySemantics)
    )
    catalog = ImplementationCatalog(
        local_python=tuple(
            implementation
            for implementation in (
                compiled.assembly.source.implementation_catalog.local_python
            )
            if implementation.operation_id != scalar_operation.id
        )
    )

    verified = verify_assembly_graph(
        replace(compiled.assembly.source, implementation_catalog=catalog)
    )

    selected = next(
        operation
        for operation in verified.semantic_graph.graph.operations
        if operation.id == scalar_operation.id
    )
    assert selected.contract == scalar_operation.contract


def test_source_coordinate_collision_ignores_non_coordinate_payload() -> None:
    point_source = internal_value_ref_from_expression(
        literal_rows([{}]),
        Table(
            columns=(TableColumn("payload", Scalar(Payload("point-payload"))),),
        ),
    )

    verify_assembly_graph(
        SemanticExperimentIR(
            point_domain=point_rows(point_source),
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
            SemanticExperimentIR(
                point_domain=point_rows(point_source),
                records=(observable("coordinate"),),
            )
        )

    assert error.value.problems[0].code == ("experiment_record_coordinate_collision")
