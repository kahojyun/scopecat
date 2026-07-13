from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

import scopecat as sc
from scopecat._compiler.program import ComputeEdge
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    EvalContext,
)
from scopecat._relations import ScalarExpr
from scopecat._semantic_graph import (
    LiteralValueSource,
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    ScalarBinarySemantics,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.authoring import ValueValidationError
from scopecat.authoring._elaboration import elaborate_module
from scopecat.authoring._resolution import resolve_experiment
from scopecat.authoring._value_refs import (
    internal_value_ref_scalar_operation,
    internal_value_ref_source_kind,
)
from scopecat.errors import CheckFailed
from tests.support.authoring import load_config
from tests.support.relation_plans import evaluate_scalar


def _payload_type() -> sc.ScalarType:
    return sc.ScalarType(sc.PayloadType("test.module-output"))


def _producer_module() -> sc.ExperimentModule:
    payload_type = _payload_type()
    produce = sc.compute(
        "produce",
        fn=lambda: {"ok": True},
        output_type=payload_type,
    )
    return (
        sc.module("test.outputs.producer")
        .computes(produce)
        .export(payload=produce.output)
        .build()
    )


def _consumer_module() -> sc.ExperimentModule:
    payload_type = _payload_type()
    payload = sc.input("payload", payload_type)
    consume = sc.compute(
        "consume",
        fn=lambda *, payload: payload,
        inputs={"payload": payload},
        output_type=payload_type,
    )
    return sc.module("test.outputs.consumer").inputs(payload).computes(consume).build()


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
        sc.module("test.outputs.siblings")
        .use(first, second, first_consumer, second_consumer)
        .build()
    )

    assembly = elaborate_module(root)
    nodes = {
        operation.id: operation for operation in assembly.semantic_graph.operations
    }
    definitions = {
        definition.id: definition for definition in assembly.semantic_graph.value_defs
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
    first_source = definitions[first_input.value_id].source
    second_source = definitions[second_input.value_id].source
    assert isinstance(first_source, OperationOutputSource)
    assert isinstance(second_source, OperationOutputSource)
    assert first_source.operation_id == OperationId(
        SymbolId(scope=("first-producer",), local_id="produce")
    )
    assert second_source.operation_id == OperationId(
        SymbolId(scope=("second-producer",), local_id="produce")
    )

    resolved = resolve_experiment(
        root.template("test.outputs.siblings", kind="module_outputs").build().bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    linked_nodes = {node.id: node for node in resolved.experiment.compute_nodes}
    first_edge = linked_nodes[
        OperationId(SymbolId(scope=("first-consumer",), local_id="consume"))
    ].inputs["payload"]
    second_edge = linked_nodes[
        OperationId(SymbolId(scope=("second-consumer",), local_id="consume"))
    ].inputs["payload"]
    assert isinstance(first_edge, ComputeEdge)
    assert isinstance(second_edge, ComputeEdge)
    first_producer = linked_nodes[
        OperationId(SymbolId(scope=("first-producer",), local_id="produce"))
    ]
    second_producer = linked_nodes[
        OperationId(SymbolId(scope=("second-producer",), local_id="produce"))
    ]
    assert first_edge.value_id == first_producer.result.id
    assert first_edge.expected_type == first_producer.result.value_type
    assert second_edge.value_id == second_producer.result.id
    assert second_edge.expected_type == second_producer.result.value_type


def test_exported_child_value_is_prefixed_when_parent_is_instantiated() -> None:
    producer = _producer_module()
    child_instance = producer.instantiate("child")
    wrapper = (
        sc.module("test.outputs.wrapper")
        .use(child_instance)
        .export(payload=child_instance.outputs.payload)
        .build()
    )
    outer = wrapper.instantiate("outer")
    sink = _consumer_module().instantiate("sink", payload=outer.outputs.payload)
    root = sc.module("test.outputs.nested").use(outer, sink).build()

    assembly = elaborate_module(root)
    sink_node = next(
        operation
        for operation in assembly.semantic_graph.operations
        if operation.id.local_id == "consume"
    )
    sink_input = dict(sink_node.inputs)["payload"]
    definitions = {
        definition.id: definition for definition in assembly.semantic_graph.value_defs
    }
    source = definitions[sink_input.value_id].source

    assert isinstance(source, OperationOutputSource)
    assert source.operation_id == OperationId(
        SymbolId(scope=("outer", "child"), local_id="produce")
    )


def test_nested_compute_exports_preserve_exact_typed_result_values(
    tmp_path: Path,
) -> None:
    producer = _producer_module()
    child = producer.instantiate("child")
    wrapper = (
        sc.module("test.outputs.typed-result-wrapper")
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
        sc.module("test.outputs.typed-result-root")
        .use(first, second, first_sink, second_sink)
        .build()
    )

    resolved = resolve_experiment(
        root.template("test.outputs.typed-result", kind="module_outputs")
        .build()
        .bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    nodes = {node.id: node for node in resolved.experiment.compute_nodes}
    expected_availability = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)
    expected_type = _payload_type()

    for wrapper_scope, sink_scope in (
        ("alpha.outer", "first-sink"),
        ("beta/outer", "second-sink"),
    ):
        producer_node = nodes[
            OperationId(SymbolId(scope=(wrapper_scope, "child"), local_id="produce"))
        ]
        sink_node = nodes[
            OperationId(SymbolId(scope=(sink_scope,), local_id="consume"))
        ]
        edge = sink_node.inputs["payload"]
        assert isinstance(edge, ComputeEdge)
        assert producer_node.result.value_type == expected_type
        assert producer_node.result.availability == expected_availability
        assert producer_node.result.id.scope == (
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
        sc.module("test.outputs.expressions")
        .inputs(value)
        .export(passthrough=value, shifted=value + 0.5)
        .build()
    )
    invocation = module.instantiate("expression-instance", value=1.25)
    passthrough_input = sc.input("passthrough", value_type)
    shifted_input = sc.input("shifted", value_type)
    capture = sc.compute(
        "capture",
        fn=lambda *, passthrough, shifted: (passthrough, shifted),
        inputs={"passthrough": passthrough_input, "shifted": shifted_input},
        output_type=sc.ScalarType(sc.PayloadType("test.export-capture")),
    )
    consumer = (
        sc.module("test.outputs.expression-consumer")
        .inputs(passthrough_input, shifted_input)
        .computes(capture)
        .build()
        .instantiate(
            "consumer",
            passthrough=invocation.outputs.passthrough,
            shifted=invocation.outputs.shifted,
        )
    )
    root = sc.module("test.outputs.expression-root").use(invocation, consumer).build()
    flattened = elaborate_module(root)
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
    shifted = definitions[capture_inputs["shifted"].value_id]
    assert isinstance(passthrough.source, PlanExpressionSource)
    assert isinstance(passthrough.source.expression, ScalarExpr)
    assert (
        evaluate_scalar(
            REFERENCE_RELATION_BACKEND,
            passthrough.source.expression,
            EvalContext(),
            bindings=passthrough.source.verified_plan.bindings,
        )
        == 1.25
    )
    assert isinstance(shifted.source, OperationOutputSource)
    shift_operation = next(
        operation
        for operation in flattened.semantic_graph.operations
        if operation.id == shifted.source.operation_id
    )
    assert isinstance(shift_operation.contract.semantics, ScalarBinarySemantics)
    assert shift_operation.contract.semantics.operator == "+"
    operands = {
        name: definitions[value.value_id].source
        for name, value in shift_operation.inputs
    }
    assert isinstance(operands["left"], PlanExpressionSource)
    assert isinstance(operands["left"].expression, ScalarExpr)
    assert (
        evaluate_scalar(
            REFERENCE_RELATION_BACKEND,
            operands["left"].expression,
            EvalContext(),
            bindings=operands["left"].verified_plan.bindings,
        )
        == 1.25
    )
    assert operands["right"] == LiteralValueSource(0.5)
    assert set(invocation.outputs) == {"passthrough", "shifted"}


def test_invocation_validates_typed_and_literal_inputs_immediately() -> None:
    payload = sc.input("payload", _payload_type())
    count = sc.input("count", sc.ScalarType(sc.IntType(minimum=1)))
    module = sc.module("test.outputs.validation").inputs(payload, count).build()
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


def test_fixed_records_are_reserved_for_the_template_root() -> None:
    module = sc.module("test.outputs.fixed-record").record("signal").build()

    with pytest.raises(ValueError, match="must declare products"):
        module.instantiate("child")


def test_module_is_not_an_anonymous_invocation_factory() -> None:
    assert not callable(_producer_module())


def test_module_export_scalar_operations_resolve_during_elaboration() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    source = (
        sc.module("test.outputs.expression-boundary")
        .inputs(value)
        .export(value=value)
        .build()
    )
    source_instance = source.instantiate("source", value=1.0)
    exported = source_instance.outputs.value
    shifted = exported + 1.0

    operation = internal_value_ref_scalar_operation(shifted)
    assert internal_value_ref_source_kind(shifted) == "scalar_operation"
    assert operation is not None
    assert operation.left is exported

    consumed = sc.input("consumed", value_type)
    capture = sc.compute(
        "capture",
        fn=lambda *, consumed: consumed,
        inputs={"consumed": consumed},
        output_type=value_type,
    )
    consumer = (
        sc.module("test.outputs.expression-boundary-consumer")
        .inputs(consumed)
        .computes(capture)
        .build()
        .instantiate("consumer", consumed=shifted)
    )
    root = (
        sc.module("test.outputs.expression-boundary-root")
        .use(source_instance, consumer)
        .build()
    )

    flattened = elaborate_module(root)
    capture_node = next(
        semantic_operation
        for semantic_operation in flattened.semantic_graph.operations
        if semantic_operation.id.local_id == "capture"
    )
    captured = dict(capture_node.inputs)["consumed"]
    definitions = {
        definition.id: definition for definition in flattened.semantic_graph.value_defs
    }
    captured_definition = definitions[captured.value_id]
    assert isinstance(captured_definition.source, OperationOutputSource)
    semantic_operation = next(
        candidate
        for candidate in flattened.semantic_graph.operations
        if candidate.id == captured_definition.source.operation_id
    )
    assert isinstance(semantic_operation.contract.semantics, ScalarBinarySemantics)
    assert semantic_operation.contract.semantics.operator == "+"
    operands = {
        name: definitions[value.value_id].source
        for name, value in semantic_operation.inputs
    }
    assert isinstance(operands["left"], PlanExpressionSource)
    assert isinstance(operands["left"].expression, ScalarExpr)
    assert (
        evaluate_scalar(
            REFERENCE_RELATION_BACKEND,
            operands["left"].expression,
            EvalContext(),
            bindings=operands["left"].verified_plan.bindings,
        )
        == 1.0
    )
    assert operands["right"] == LiteralValueSource(1.0)


def test_module_build_rejects_undeclared_export_inputs() -> None:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))

    with pytest.raises(CheckFailed) as error:
        sc.module("test.outputs.undeclared-input").export(value=value).build()

    assert [problem.code for problem in error.value.problems] == [
        "module_input_undeclared"
    ]


def test_module_use_requires_explicit_instances() -> None:
    root = sc.module("test.outputs.explicit-use")
    use = root.use

    with pytest.raises(TypeError, match="instantiate"):
        use(cast("sc.ModuleInvocation", _producer_module()))
    with pytest.raises(TypeError, match="instantiate"):
        use(cast("sc.ModuleInvocation", sc.module("test.outputs.unbuilt-child")))


def test_duplicate_explicit_instance_ids_are_rejected() -> None:
    producer = _producer_module()

    with pytest.raises(ValueError, match="duplicate instance ids: 'duplicate'"):
        sc.module("test.outputs.duplicate-instance").use(
            producer.instantiate("duplicate"),
            producer.instantiate("duplicate"),
        )


def test_output_refs_are_nominally_owned_by_the_used_instance() -> None:
    foreign = _producer_module().instantiate("same")
    selected = _producer_module().instantiate("same")
    sink = _consumer_module().instantiate(
        "sink",
        payload=foreign.outputs.payload,
    )
    with pytest.raises(CheckFailed) as error:
        sc.module("test.outputs.nominal").use(selected, sink).build()

    assert [problem.code for problem in error.value.problems] == [
        "module_export_foreign_instance"
    ]


def test_output_roots_preserve_free_inputs_and_value_provenance() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    parameter = sc.parameter("output_parameter", value_type)
    point = sc.point("output_point", value_type)
    source = (
        sc.module("test.outputs.roots")
        .inputs(value)
        .export(value=value, parameter=parameter, point=point)
        .build()
    )
    source_instance = source.instantiate("source", value=value)
    wrapper = (
        sc.module("test.outputs.roots.wrapper")
        .inputs(value)
        .use(source_instance)
        .export(value=source_instance.outputs.value)
        .build()
    )

    assembly = elaborate_module(source)

    assert [(port.id, port.value_type) for port in wrapper.ir.interface.imports] == [
        ("value", value_type)
    ]
    assert [contract.parameter_id for contract in assembly.parameter_contracts] == [
        "output_parameter"
    ]
    assert [dependency.id for dependency in assembly.point_dependencies] == [
        "output_point"
    ]
