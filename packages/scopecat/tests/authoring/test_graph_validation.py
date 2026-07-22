from __future__ import annotations

from dataclasses import replace

import pytest

import scopecat as sc
from scopecat.authoring._binding_intents import requires, resource_port
from scopecat.authoring._products import ModuleProductDecl, record_product
from scopecat.compiler.frontend.assembly_lowering import validate_assembly_entrypoint
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import (
    compile_prepared_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.relations.point_domain import point_literal_rows
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    LiteralValueSource,
    OperationOutputSource,
    SemanticGraphIR,
    SourceMap,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import ScalarBinarySemantics
from scopecat.compiler.semantic.verification import (
    VerifiedSemanticGraph,
    verify_implementation_catalog,
    verify_semantic_graph,
    verify_source_map,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.value_types import Float, Payload, Scalar, TableColumn
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.entity import EntityRef
from tests.testkit.authoring import load_config, template_fixture


def _resolve(module: sc.ExperimentModule) -> None:
    invocation = template_fixture(module, id="test.graph", kind="graph").bind()
    resolve_experiment(
        invocation,
        config_profile=load_config(),
    )


def _pair_values(*, upstream: object, parameter: object) -> tuple[object, object]:
    return upstream, parameter


def _identity_value(*, value: object) -> object:
    return value


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
        fn=_pair_values,
        inputs={
            "upstream": missing.output,
            "parameter": missing_parameter,
        },
        output_type=sc.ScalarType(sc.FloatType()),
    )
    with pytest.raises(CheckFailed) as error:
        sc.module_body(id="test.graph.order").computes(consumer).build()

    assert error.value.problems[0].code == "module_compute_foreign_definition"


def test_state_rejects_an_unregistered_compute_output() -> None:
    missing = sc.compute(
        "missing-program",
        fn=lambda: {"program": True},
        output_type=sc.ScalarType(sc.PayloadType("pulse-program")),
    )
    with pytest.raises(CheckFailed) as error:
        (
            sc.module_body(id="test.graph.state-missing")
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
        sc.module_body(id="test.graph.state-type")
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
        sc.module_body(id="test.graph.table-state-binding")
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
    invocation = template_fixture(
        module,
        id="test.graph.table-state-binding",
        kind="graph",
    ).bind(rows=({"value": 1.0},))

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
        sc.module_body(id="test.graph.table-action-field")
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
    invocation = template_fixture(
        module,
        id="test.graph.table-action-field",
        kind="graph",
    ).bind(rows=({"value": 1.0},))

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
        sc.module_body(id="test.graph.table-row-region-value")
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
    invocation = template_fixture(
        module,
        id="test.graph.table-row-region-value",
        kind="graph",
    ).bind(rows=({"value": 1.0},))

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
        fn=_identity_value,
        inputs={"value": missing_parameter},
        output_type=missing_parameter.value_type,
    )
    duplicate_axis = sc.product_axis("sample", size=2)
    module = (
        sc.module_body(id="test.graph.record-schema")
        .computes(consume)
        .product("signal", axes=(duplicate_axis, duplicate_axis))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module)

    assert error.value.problems[0].code == ("product_axis_duplicate")
    assert error.value.problems[0].location == model_location(
        "products", "signal", "axes"
    )


def test_resource_selector_rejects_external_operation_value() -> None:
    entity_type = sc.ScalarType(sc.EntityType())
    subject = sc.input("subject", entity_type)
    child = (
        sc.module_body(id="test.stage.resource-child")
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
        sc.module_body(id="test.stage.resource-parent")
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
    assert problem.code == "value_requires_execution"
    assert problem.location == model_location(
        "resources",
        "resource-child",
        "drive",
        "selector",
        "entity_inputs",
        0,
    )
    assert "resource selector" in problem.message
    assert "external operation" in problem.message


def test_product_axis_rejects_external_operation_value() -> None:
    size = sc.compute(
        "axis-size",
        fn=lambda: 2,
        output_type=sc.ScalarType(sc.IntType()),
    )
    module = (
        sc.module_body(id="test.stage.record-execute")
        .computes(size)
        .product("signal", axes=(sc.product_axis("sample", size=size.output),))
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module)

    problem = error.value.problems[0]
    assert problem.code == "product_axis_value_requires_execution"
    assert problem.location == model_location(
        "products", "signal", "axes", "sample", "size"
    )


def test_product_axis_rejects_point_dependent_value() -> None:
    size = sc.point("axis-size", sc.ScalarType(sc.IntType(minimum=1)))
    module = (
        sc.module_body(id="test.stage.record-point")
        .product("signal", axes=(sc.product_axis("sample", size=size),))
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.stage.record-point",
        kind="graph",
        scans=(sc.axis(size, (2, 3)),),
    ).bind()

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            invocation,
            config_profile=load_config(),
        )

    problem = error.value.problems[0]
    assert problem.code == "product_axis_value_depends_on_point"
    assert problem.location == model_location(
        "products", "signal", "axes", "sample", "size"
    )


def test_state_target_rejects_external_operation_value() -> None:
    rows = sc.parameter(
        "missing-state-rows",
        sc.TableType(columns=()),
    )
    target_entity = sc.compute(
        "target-entity",
        fn=lambda: "q0",
        output_type=sc.ScalarType(sc.EntityType()),
    )
    module = (
        sc.module_body(id="test.stage.state-target")
        .resource("drive", requires=("set_gain",))
        .computes(target_entity)
        .state_each(
            rows,
            resource_port="drive",
            capability="set_gain",
            field="value",
            value=1.0,
            target_entities=(target_entity.output,),
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module)

    problem = error.value.problems[0]
    assert problem.code == "value_requires_execution"
    assert problem.location == model_location("state", 0, "target_entities", 0)
    assert "state target entity" in problem.message


def test_direct_compute_edge_is_topologically_ordered() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    producer = sc.compute(
        "producer",
        fn=lambda: 1.0,
        output_type=value_type,
    )
    consumer = sc.compute(
        "consumer",
        fn=_identity_value,
        inputs={"value": producer.output},
        output_type=value_type,
    )
    module = (
        sc.module_body(id="test.graph.direct-edge").computes(consumer, producer).build()
    )

    invocation = template_fixture(
        module,
        id="test.graph.direct-edge",
        kind="graph",
    ).bind()
    compiled = compile_prepared_invocation(prepare_invocation(invocation))

    assert [
        operation.id.local_id
        for operation in compiled.assembly.graph.semantic_graph.graph.operations
    ] == [
        "producer",
        "consumer",
    ]


def test_compile_carries_verified_source_and_normalized_compiler_inputs() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    module = sc.module_body(id="test.graph.verified-source").inputs(subject).build()
    invocation = template_fixture(
        module,
        id="test.graph.verified-source",
        kind="graph",
    ).bind(subject="q0")

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
    calls = {"graph": 0, "catalog": 0, "source_map": 0}

    def counted_graph(graph: SemanticGraphIR) -> VerifiedSemanticGraph:
        calls["graph"] += 1
        return verify_semantic_graph(graph)

    def counted_catalog(
        graph: SemanticGraphIR,
        catalog: ImplementationCatalog,
    ) -> ImplementationCatalog:
        calls["catalog"] += 1
        return verify_implementation_catalog(graph, catalog)

    def counted_source_map(graph: SemanticGraphIR, source_map: SourceMap) -> SourceMap:
        calls["source_map"] += 1
        return verify_source_map(graph, source_map)

    monkeypatch.setattr(
        "scopecat.compiler.frontend.graph_validation.verify_semantic_graph",
        counted_graph,
    )
    monkeypatch.setattr(
        "scopecat.compiler.frontend.graph_validation.verify_implementation_catalog",
        counted_catalog,
    )
    monkeypatch.setattr(
        "scopecat.compiler.frontend.graph_validation.verify_source_map",
        counted_source_map,
    )
    module = sc.module_body(id="test.graph.single-proof").build()
    invocation = template_fixture(
        module,
        id="test.graph.single-proof",
        kind="graph",
    ).bind()

    compiled = compile_prepared_invocation(prepare_invocation(invocation))
    resolved = resolve_compiled_invocation(
        compiled,
        environment=validate_config_environment(load_config()),
    )

    assert calls == {"graph": 1, "catalog": 1, "source_map": 1}
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
        fn=_identity_value,
        inputs={"value": child_value + 1.0},
        output_type=value_type,
    )
    child = (
        sc.module_body(id="test.graph.execute-expression-child")
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
        sc.module_body(id="test.graph.execute-expression-parent")
        .computes(producer)
        .use(child.instantiate("expression-child", value=producer.output))
        .build()
    )

    invocation = template_fixture(
        parent,
        id="test.graph.execute-expression",
        kind="graph",
    ).bind()
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
    assert left.source == OperationOutputSource(producer_operation.id)
    assert isinstance(right.source, LiteralValueSource)
    assert right.source.value == 1.0


def test_execute_core_operation_defers_local_implementation_selection() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    produce = sc.compute("produce", fn=lambda: 1.0, output_type=value_type)
    consume = sc.compute(
        "consume",
        fn=_identity_value,
        inputs={"value": produce.output + 1.0},
        output_type=value_type,
    )
    module = (
        sc.module_body(id="test.graph.core-implementation")
        .computes(produce, consume)
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.graph.core-implementation",
        kind="graph",
    ).bind()
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
    point_source = point_literal_rows(
        (TableColumn("payload", Scalar(Payload("point-payload"))),),
        ((PayloadValue(schema_id="point-payload", payload={}),),),
    )

    verify_assembly_graph(
        SemanticExperimentIR(
            point_domain=point_source,
            product_declarations=(ModuleProductDecl(id="payload"),),
            record_selections=(record_product("payload"),),
        )
    )


def test_source_coordinate_collision_uses_typed_coordinate_predicate() -> None:
    point_source = point_literal_rows(
        (TableColumn("coordinate", Scalar(Float())),),
        ((1.0,),),
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(
            SemanticExperimentIR(
                point_domain=point_source,
                product_declarations=(ModuleProductDecl(id="coordinate"),),
                record_selections=(record_product("coordinate"),),
            )
        )

    assert error.value.problems[0].code == ("experiment_record_coordinate_collision")
