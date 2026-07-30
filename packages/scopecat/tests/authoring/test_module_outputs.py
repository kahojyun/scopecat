from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring import ValueValidationError
from scopecat.authoring._parameter_contracts import ParameterValueContract
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.assembly_linking import bind_verified_assembly
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.semantic.model import PlanExpressionSource
from scopecat.compiler.typed.program import ComputeEdge, CoreProgram
from scopecat.config.environment import build_config_environment
from scopecat.graph.relations.model import ScalarExpr
from scopecat.graph.values import (
    OperationId,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import evaluate_scalar


def _bind_program(
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot,
) -> CoreProgram:
    environment = build_config_environment(config)
    compiled = compile_invocation(invocation)
    return bind_verified_assembly(compiled.assembly, environment)


def _payload_type() -> sc.ScalarType:
    return sc.ScalarType(sc.PayloadType("test.module-output"))


def _identity_payload(*, payload: object) -> object:
    return payload


def _capture_pair(*, passthrough: object, shifted: object) -> tuple[object, object]:
    return passthrough, shifted


def _identity_consumed(*, consumed: object) -> object:
    return consumed


def _producer_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()
    produce = sc.compute(
        "produce",
        fn=lambda: {"ok": True},
        output_type=payload_type,
    )
    return (
        sc.procedure(id="test.outputs.producer")
        .computes(produce)
        .export(payload=produce.output)
        .build()
    )


def _consumer_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()
    payload = sc.input("payload", payload_type)
    consume = sc.compute(
        "consume",
        fn=_identity_payload,
        inputs={"payload": payload},
        output_type=payload_type,
    )
    return (
        sc.procedure(id="test.outputs.consumer")
        .inputs(payload)
        .computes(consume)
        .build()
    )


def test_explicit_instances_export_hygienic_compute_values_to_siblings(
    tmp_path: Path,
) -> None:
    producer = _producer_module()
    consumer = _consumer_module()
    first = producer.instantiate("first-producer")
    second = producer.instantiate("second-producer")
    first_consumer = consumer.instantiate(
        "first-consumer",
        payload=first.outputs.payload,
    )
    second_consumer = consumer.instantiate(
        "second-consumer",
        payload=second.outputs["payload"],
    )
    root = (
        sc.procedure(id="test.outputs.siblings")
        .use(first, second, first_consumer, second_consumer)
        .build()
    )

    assembly = elaborate_module(root.ir)
    nodes = {
        operation.id: operation for operation in assembly.semantic_graph.operations
    }
    results = {
        operation.result_id: operation
        for operation in assembly.semantic_graph.operations
    }

    first_input = dict(
        nodes[
            OperationId(SymbolId(scope=("first-consumer",), local_id="consume"))
        ].inputs
    )["payload"]
    second_input = dict(
        nodes[
            OperationId(SymbolId(scope=("second-consumer",), local_id="consume"))
        ].inputs
    )["payload"]
    assert results[first_input.value_id].id == OperationId(
        SymbolId(scope=("first-producer",), local_id="produce")
    )
    assert results[second_input.value_id].id == OperationId(
        SymbolId(scope=("second-producer",), local_id="produce")
    )

    call = root()

    @sc.template(id="test.outputs.siblings", kind="module_outputs")
    def template_definition() -> sc.ExperimentBody:
        return sc.experiment(call)

    program = _bind_program(
        template_definition(),
        load_config(),
    )
    bound_nodes = {node.id: node for node in program.compute_nodes}
    first_edge = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "first-consumer"), local_id="consume"))
    ].inputs["payload"]
    second_edge = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "second-consumer"), local_id="consume"))
    ].inputs["payload"]
    assert isinstance(first_edge, ComputeEdge)
    assert isinstance(second_edge, ComputeEdge)
    first_producer = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "first-producer"), local_id="produce"))
    ]
    second_producer = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "second-producer"), local_id="produce"))
    ]
    assert first_edge.value_id == first_producer.result.id
    assert first_edge.expected_type == first_producer.result.value_type
    assert second_edge.value_id == second_producer.result.id
    assert second_edge.expected_type == second_producer.result.value_type


def test_exported_child_value_is_prefixed_when_parent_is_instantiated() -> None:
    producer = _producer_module()
    child_instance = producer.instantiate("child")
    wrapper = (
        sc.procedure(id="test.outputs.wrapper")
        .use(child_instance)
        .export(payload=child_instance.outputs.payload)
        .build()
    )
    outer = wrapper.instantiate("outer")
    sink = _consumer_module().instantiate("sink", payload=outer.outputs.payload)
    root = sc.procedure(id="test.outputs.nested").use(outer, sink).build()

    assembly = elaborate_module(root.ir)
    sink_node = next(
        operation
        for operation in assembly.semantic_graph.operations
        if operation.id.local_id == "consume"
    )
    sink_input = dict(sink_node.inputs)["payload"]
    results = {
        operation.result_id: operation
        for operation in assembly.semantic_graph.operations
    }
    assert results[sink_input.value_id].id == OperationId(
        SymbolId(scope=("outer", "child"), local_id="produce")
    )


def test_nested_compute_exports_preserve_exact_typed_result_values(
    tmp_path: Path,
) -> None:
    producer = _producer_module()
    child = producer.instantiate("child")
    wrapper = (
        sc.procedure(id="test.outputs.typed-result-wrapper")
        .use(child)
        .export(payload=child.outputs.payload)
        .build()
    )
    first = wrapper.instantiate("alpha.outer")
    second = wrapper.instantiate("beta/outer")
    first_sink = _consumer_module().instantiate(
        "first-sink",
        payload=first.outputs.payload,
    )
    second_sink = _consumer_module().instantiate(
        "second-sink",
        payload=second.outputs.payload,
    )
    root = (
        sc.procedure(id="test.outputs.typed-result-root")
        .use(first, second, first_sink, second_sink)
        .build()
    )

    call = root()

    @sc.template(id="test.outputs.typed-result", kind="module_outputs")
    def template_definition() -> sc.ExperimentBody:
        return sc.experiment(call)

    program = _bind_program(
        template_definition(),
        load_config(),
    )
    nodes = {node.id: node for node in program.compute_nodes}
    expected_type = _payload_type()

    for wrapper_scope, sink_scope in (
        ("alpha.outer", "first-sink"),
        ("beta/outer", "second-sink"),
    ):
        producer_node = nodes[
            OperationId(
                SymbolId(
                    scope=("typed-result-root", wrapper_scope, "child"),
                    local_id="produce",
                )
            )
        ]
        sink_node = nodes[
            OperationId(
                SymbolId(
                    scope=("typed-result-root", sink_scope),
                    local_id="consume",
                )
            )
        ]
        edge = sink_node.inputs["payload"]
        assert isinstance(edge, ComputeEdge)
        assert producer_node.result.value_type == expected_type
        assert producer_node.result.id.scope == (
            "typed-result-root",
            wrapper_scope,
            "child",
            "produce",
            "outputs",
        )
        assert producer_node.result.id.local_id == "result"
        assert edge.value_id == producer_node.result.id
        assert edge.expected_type == producer_node.result.value_type


def test_passthrough_and_expression_exports_bind_instance_inputs() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    module = (
        sc.procedure(id="test.outputs.expressions")
        .inputs(value)
        .export(passthrough=value, shifted=value + 0.5)
        .build()
    )
    invocation = module.instantiate("expression-instance", value=1.25)
    passthrough_input = sc.input("passthrough", value_type)
    shifted_input = sc.input("shifted", value_type)
    capture = sc.compute(
        "capture",
        fn=_capture_pair,
        inputs={"passthrough": passthrough_input, "shifted": shifted_input},
        output_type=sc.ScalarType(sc.PayloadType("test.export-capture")),
    )
    consumer = (
        sc.procedure(id="test.outputs.expression-consumer")
        .inputs(passthrough_input, shifted_input)
        .computes(capture)
        .build()
        .instantiate(
            "consumer",
            passthrough=invocation.outputs.passthrough,
            shifted=invocation.outputs.shifted,
        )
    )
    root = (
        sc.procedure(id="test.outputs.expression-root")
        .use(invocation, consumer)
        .build()
    )
    flattened = elaborate_module(root.ir)
    capture_node = next(
        operation
        for operation in flattened.semantic_graph.operations
        if operation.id.local_id == "capture"
    )
    capture_inputs = dict(capture_node.inputs)
    definitions = {
        definition.id: definition for definition in flattened.semantic_graph.value_defs
    }
    passthrough = definitions[capture_inputs["passthrough"].value_id]
    assert isinstance(passthrough.source, PlanExpressionSource)
    assert isinstance(passthrough.source.expression, ScalarExpr)
    assert (
        evaluate_scalar(
            passthrough.source.expression,
            EvalContext(),
            bindings=passthrough.source.verified_plan.bindings,
        )
        == 1.25
    )
    shifted = definitions[capture_inputs["shifted"].value_id]
    assert isinstance(shifted.source, PlanExpressionSource)
    assert isinstance(shifted.source.expression, ScalarExpr)
    assert (
        evaluate_scalar(
            shifted.source.expression,
            EvalContext(),
            bindings=shifted.source.verified_plan.bindings,
        )
        == 1.75
    )
    assert set(invocation.outputs) == {"passthrough", "shifted"}


def test_invocation_validates_typed_and_literal_inputs_immediately() -> None:
    payload = sc.input("payload", _payload_type())
    count = sc.input("count", sc.ScalarType(sc.IntType(minimum=1)))
    module = sc.procedure(id="test.outputs.validation").inputs(payload, count).build()
    incompatible = sc.input(
        "waveform",
        sc.ScalarType(sc.PayloadType("test.waveform")),
    )

    with pytest.raises(ValueValidationError, match=r"Payload\[test.module-output\]"):
        module.instantiate(
            "incompatible-input",
            payload=incompatible,
            count=1,
        )
    with pytest.raises(ValueValidationError, match="value must be at least 1"):
        module.instantiate("invalid-literal", count=0)
    with pytest.raises(ValueError, match="must connect all inputs"):
        module.instantiate("missing-inputs")


def test_module_products_remain_reusable_across_instances() -> None:
    module = sc.procedure(id="test.outputs.product").product("signal").build()

    child = module.instantiate("child")

    assert child.products["signal"].id == "child/signal"


def test_module_export_arithmetic_resolves_during_elaboration() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    source = (
        sc.procedure(id="test.outputs.expression-boundary")
        .inputs(value)
        .export(value=value)
        .build()
    )
    source_instance = source.instantiate("source", value=1.0)
    exported = source_instance.outputs.value
    shifted = exported + 1.0

    consumed = sc.input("consumed", value_type)
    capture = sc.compute(
        "capture",
        fn=_identity_consumed,
        inputs={"consumed": consumed},
        output_type=value_type,
    )
    consumer = (
        sc.procedure(id="test.outputs.expression-boundary-consumer")
        .inputs(consumed)
        .computes(capture)
        .build()
        .instantiate("consumer", consumed=shifted)
    )
    root = (
        sc.procedure(id="test.outputs.expression-boundary-root")
        .use(source_instance, consumer)
        .build()
    )

    flattened = elaborate_module(root.ir)
    capture_node = next(
        semantic_operation
        for semantic_operation in flattened.semantic_graph.operations
        if semantic_operation.id.local_id == "capture"
    )
    captured = dict(capture_node.inputs)["consumed"]
    definitions = {
        definition.id: definition for definition in flattened.semantic_graph.value_defs
    }
    shifted_definition = definitions[captured.value_id]
    assert isinstance(shifted_definition.source, PlanExpressionSource)
    assert isinstance(shifted_definition.source.expression, ScalarExpr)
    assert (
        evaluate_scalar(
            shifted_definition.source.expression,
            EvalContext(),
            bindings=shifted_definition.source.verified_plan.bindings,
        )
        == 2.0
    )


def test_module_build_rejects_undeclared_export_inputs() -> None:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))

    with pytest.raises(CheckFailed) as error:
        sc.procedure(id="test.outputs.undeclared-input").export(value=value).build()

    assert [problem.code for problem in error.value.problems] == [
        "module_input_undeclared"
    ]


def test_duplicate_explicit_instance_ids_are_rejected() -> None:
    producer = _producer_module()

    with pytest.raises(ValueError, match="duplicate module instance ids: 'duplicate'"):
        (
            sc.procedure(id="test.outputs.duplicate-instance")
            .use(
                producer.instantiate("duplicate"),
                producer.instantiate("duplicate"),
            )
            .build()
        )


def test_output_refs_are_nominally_owned_by_the_used_instance() -> None:
    foreign = _producer_module().instantiate("same")
    selected = _producer_module().instantiate("same")
    sink = _consumer_module().instantiate(
        "sink",
        payload=foreign.outputs.payload,
    )
    with pytest.raises(CheckFailed) as error:
        sc.procedure(id="test.outputs.nominal").use(selected, sink).build()

    assert [problem.code for problem in error.value.problems] == [
        "module_export_foreign_instance"
    ]


def test_output_roots_preserve_free_inputs_and_value_provenance() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    parameter = sc.parameter("output_parameter", value_type)
    point = sc.coordinate("output_point", value_type)
    source = (
        sc.procedure(id="test.outputs.roots")
        .inputs(value)
        .export(value=value, parameter=parameter, point=point)
        .build()
    )
    source_instance = source.instantiate("source", value=value)
    wrapper = (
        sc.procedure(id="test.outputs.roots.wrapper")
        .inputs(value)
        .use(source_instance)
        .export(value=source_instance.outputs.value)
        .build()
    )

    assembly = elaborate_module(source.ir)

    assert [(port.id, port.value_type) for port in wrapper.ir.interface.imports] == [
        ("value", value_type)
    ]
    assert assembly.parameter_contracts == (
        ParameterValueContract("output_parameter", value_type),
    )
    assert [dependency.id for dependency in assembly.point_dependencies] == [
        "output_point"
    ]
