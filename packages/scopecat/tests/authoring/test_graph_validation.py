from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._binding_intents import requires, resource_port
from scopecat.authoring._products import ModuleProductDecl, record_product
from scopecat.compiler.frontend.assembly_lowering import validate_assembly_entrypoint
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.semantic.model import (
    AcquireEffect,
    SemanticDomainExecution,
    SemanticGraphIR,
)
from scopecat.compiler.semantic.verification import (
    VerifiedSemanticGraph,
    verify_semantic_graph,
)
from scopecat.compiler.typed.program import CoreProgram
from scopecat.compiler.typed.verification import (
    VerifiedCoreProgram,
    seal_typed_program,
)
from scopecat.config.environment import build_config_environment
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.value_types import Float, Payload, Scalar
from tests.testkit.authoring import link_invocation, load_config, template_fixture


def _resolve(module: sc.ExperimentModule[...]) -> None:
    invocation = template_fixture(module, id="test.graph", kind="graph").bind()
    link_invocation(
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


def test_invocation_rejects_an_unregistered_compute_output() -> None:
    missing = sc.compute(
        "missing-program",
        fn=lambda: {"program": True},
        output_type=sc.ScalarType(sc.PayloadType("pulse-program")),
    )
    with pytest.raises(CheckFailed) as error:
        (
            sc.module_body(id="test.graph.invocation-missing")
            .resource("drive", requires=("test.play_waveforms/v1",))
            .invoke(
                "play",
                resource="drive",
                interface="test.play_waveforms/v1",
                operation="play",
                arguments={"program": missing.output},
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
        .resource("drive", requires=("test.set_gain/v1",))
        .computes(compute_value)
        .bind_property(
            "drive",
            interface="test.set_gain/v1",
            property="value",
            value=compute_value.output,
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module)

    assert error.value.problems[0].code == "compute_payload_unavailable"
    assert error.value.problems[0].location == model_location("bindings", 0, "value")
    assert "numeric-value/outputs/result" in error.value.problems[0].message


def test_module_rejects_a_table_shaped_plan_state_binding() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )

    with pytest.raises(TypeError, match="scalar typed value or scalar literal"):
        (
            sc.module_body(id="test.graph.table-state-binding")
            .inputs(rows)
            .resource("drive", requires=("test.set_gain/v1",))
            .bind_property(
                "drive",
                interface="test.set_gain/v1",
                property="value",
                value=rows,
            )
        )


def test_product_axes_reject_table_values_at_authoring_boundary() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(columns=(sc.TableColumn("value", sc.ScalarType(sc.FloatType())),)),
    )

    with pytest.raises(TypeError, match="axis values must be scalar"):
        sc.product_axis("sample", size=rows)
    with pytest.raises(TypeError, match="axis values must be scalar"):
        sc.entity_axis("entity", rows)


def test_static_record_schema_is_checked_before_parameter_catalog() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    missing_parameter = sc.parameter(
        "missing-record-parameter",
        value_type,
    )
    consume = sc.compute(
        "consume-parameter",
        fn=_identity_value,
        inputs={"value": missing_parameter},
        output_type=value_type,
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
    size = sc.coordinate("axis-size", sc.ScalarType(sc.IntType(minimum=1)))
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
        link_invocation(
            invocation,
            config_profile=load_config(),
        )

    problem = error.value.problems[0]
    assert problem.code == "product_axis_value_depends_on_point"
    assert problem.location == model_location(
        "products", "signal", "axes", "sample", "size"
    )


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
    compiled = compile_invocation(invocation)

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

    compiled = compile_invocation(invocation)

    assert compiled.request.inputs == {"subject": "q0"}
    assert compiled.assembly.source.inputs == {"subject": EntityRef(id="q0")}
    assert (
        compiled.assembly.graph.semantic_graph.graph
        == compiled.assembly.source.semantic_graph
    )


def test_compile_invocation_projects_request_metadata() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    module = sc.module_body(id="test.graph.prepared-request").inputs(subject).build()
    invocation = template_fixture(
        module,
        id="test.graph.prepared-request",
        kind="graph",
    ).bind(subject="q0")

    compiled = compile_invocation(
        invocation,
        metadata={"sample": "q0"},
        operator="alice",
    )

    assert compiled.request.experiment_id == invocation.definition.id
    assert compiled.request.inputs == {"subject": "q0"}
    assert compiled.request.metadata == {"sample": "q0"}
    assert compiled.request.operator == "alice"


def test_compile_verifies_and_seals_the_final_program_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"graph": 0, "seal": 0}

    def counted_graph(
        graph: SemanticGraphIR,
        *,
        effects: tuple[SemanticDomainExecution | AcquireEffect, ...] = (),
    ) -> VerifiedSemanticGraph:
        calls["graph"] += 1
        return verify_semantic_graph(graph, effects=effects)

    def counted_seal(
        program: CoreProgram,
        *,
        phase: ProblemPhase = ProblemPhase.AUTHORING,
    ) -> VerifiedCoreProgram:
        calls["seal"] += 1
        return seal_typed_program(program, phase=phase)

    monkeypatch.setattr(
        "scopecat.compiler.frontend.graph_validation.verify_semantic_graph",
        counted_graph,
    )
    monkeypatch.setattr(
        "scopecat.compiler.linking.linked.seal_typed_program",
        counted_seal,
    )
    module = sc.module_body(id="test.graph.single-proof").build()
    invocation = template_fixture(
        module,
        id="test.graph.single-proof",
        kind="graph",
    ).bind()

    compiled = compile_invocation(invocation)
    resolved = resolve_compiled_invocation(
        compiled,
        environment=build_config_environment(load_config()),
    )

    assert calls == {"graph": 1, "seal": 1}
    assert resolved.program.id == "test.graph.single-proof"


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


def test_resource_selector_requires_a_scalar_entity_value() -> None:
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


def test_compute_output_arithmetic_requires_an_explicit_compute() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = sc.input("value", value_type)
    producer = sc.compute(
        "producer",
        fn=lambda: 1.0,
        output_type=value_type,
    )

    with pytest.raises(TypeError, match=r"express this calculation with sc\.compute"):
        _ = producer.output + child_value


def test_source_coordinate_collision_ignores_non_coordinate_payload() -> None:
    point_source = point_axis_values(
        "payload",
        Scalar(Payload("point-payload")),
        (PayloadValue(schema_id="point-payload", payload={}),),
    )

    verify_assembly_graph(
        SemanticExperimentIR(
            point_domain=(point_source,),
            product_declarations=(ModuleProductDecl(id="payload"),),
            record_selections=(record_product("payload"),),
        )
    )


def test_source_coordinate_collision_uses_typed_coordinate_predicate() -> None:
    point_source = point_axis_values(
        "coordinate",
        Scalar(Float()),
        (1.0,),
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(
            SemanticExperimentIR(
                point_domain=(point_source,),
                product_declarations=(ModuleProductDecl(id="coordinate"),),
                record_selections=(record_product("coordinate"),),
            )
        )

    assert error.value.problems[0].code == ("experiment_record_coordinate_collision")
