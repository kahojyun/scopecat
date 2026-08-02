# pyright: reportUnusedFunction=false

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest

import scopecat as sc
from scopecat.authoring import ValueValidationError
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.bind import BoundPlan
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.value_resolution import resolve_bound_value
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpr
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.value_graph import OperationId
from scopecat.program.values import input as program_input
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.expressions import evaluate_scalar


def _bind_program(
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot,
) -> BoundPlan:
    return bind_invocation(
        invocation,
        config_profile=config,
    )


def _payload_type() -> sc.ScalarType:
    return sc.ScalarType(sc.PayloadType("test.module-output"))


type _PayloadInput = Annotated[
    sc.Input[object],
    sc.ScalarType(sc.PayloadType("test.module-output")),
]
type _FloatInput = Annotated[sc.Input[float], sc.FloatType()]
type _PositiveIntInput = Annotated[sc.Input[int], sc.IntType(minimum=1)]
type _GhzQuantityInput = Annotated[sc.Input[sc.Quantity], sc.QuantityType(unit="GHz")]
type _MhzQuantityInput = Annotated[sc.Input[sc.Quantity], sc.QuantityType(unit="MHz")]
_GHZ_FREQUENCY_TABLE = sc.TableType(
    columns=(
        sc.TableColumn(
            "frequency",
            sc.ScalarType(sc.QuantityType(unit="GHz")),
        ),
    )
)
_MHZ_FREQUENCY_TABLE = sc.TableType(
    columns=(
        sc.TableColumn(
            "frequency",
            sc.ScalarType(sc.QuantityType(unit="MHz")),
        ),
    )
)
type _GhzFrequencyTableInput = Annotated[
    sc.Input[list[dict[str, object]]],
    _GHZ_FREQUENCY_TABLE,
]
type _MhzFrequencyTableInput = Annotated[
    sc.Input[list[dict[str, object]]],
    _MHZ_FREQUENCY_TABLE,
]


def _identity_payload(*, payload: object) -> object:
    return payload


def _capture_pair(*, passthrough: object, shifted: object) -> tuple[object, object]:
    return passthrough, shifted


def _identity_consumed(*, consumed: object) -> object:
    return consumed


def _producer_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()

    @sc.module(id="test.outputs.producer")
    def module(context: sc.ModuleContext) -> None:
        produced = context.compute(
            "produce",
            fn=lambda: {"ok": True},
            output_type=payload_type,
        )
        context.export(payload=produced)

    return module


def _consumer_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()

    @sc.module(id="test.outputs.consumer")
    def module(context: sc.ModuleContext, payload: _PayloadInput) -> None:
        context.compute(
            "consume",
            fn=_identity_payload,
            inputs={"payload": sc.input_ref(payload)},
            output_type=payload_type,
        )

    return module


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

    @sc.module(id="test.outputs.siblings")
    def root(context: sc.ModuleContext) -> None:
        context.call(first)
        context.call(second)
        context.call(first_consumer)
        context.call(second_consumer)

    assembly = compose_module(root.definition)
    nodes = {operation.id: operation for operation in assembly.compute_nodes}
    results = {operation.result_id: operation for operation in assembly.compute_nodes}

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
    assert results[first_input].id == OperationId(
        SymbolId(scope=("first-producer",), local_id="produce")
    )
    assert results[second_input].id == OperationId(
        SymbolId(scope=("second-producer",), local_id="produce")
    )

    call = root()

    @sc.template(id="test.outputs.siblings", kind="module_outputs")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    program = _bind_program(
        template_definition(),
        load_config(),
    )
    bound_nodes = {node.id: node for node in program.program.program.compute_nodes}
    first_edge = resolve_bound_value(
        program.program,
        program.bindings,
        dict(
            bound_nodes[
                OperationId(
                    SymbolId(scope=("siblings", "first-consumer"), local_id="consume")
                )
            ].inputs
        )["payload"],
    )
    second_edge = resolve_bound_value(
        program.program,
        program.bindings,
        dict(
            bound_nodes[
                OperationId(
                    SymbolId(scope=("siblings", "second-consumer"), local_id="consume")
                )
            ].inputs
        )["payload"],
    )
    assert isinstance(first_edge, ComputeResultScalarExpr)
    assert isinstance(second_edge, ComputeResultScalarExpr)
    first_producer = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "first-producer"), local_id="produce"))
    ]
    second_producer = bound_nodes[
        OperationId(SymbolId(scope=("siblings", "second-producer"), local_id="produce"))
    ]
    assert first_edge.value_id == first_producer.result_id
    assert second_edge.value_id == second_producer.result_id
    assert first_edge.value_type == _payload_type()
    assert second_edge.value_type == _payload_type()


def test_exported_child_value_is_prefixed_when_parent_is_instantiated() -> None:
    producer = _producer_module()
    child_instance = producer.instantiate("child")

    @sc.module(id="test.outputs.wrapper")
    def wrapper(context: sc.ModuleContext) -> None:
        context.call(child_instance)
        context.export(payload=child_instance.outputs.payload)

    outer = wrapper.instantiate("outer")
    sink = _consumer_module().instantiate("sink", payload=outer.outputs.payload)

    @sc.module(id="test.outputs.nested")
    def root(context: sc.ModuleContext) -> None:
        context.call(outer)
        context.call(sink)

    assembly = compose_module(root.definition)
    sink_node = next(
        operation
        for operation in assembly.compute_nodes
        if operation.id.local_id == "consume"
    )
    sink_input = dict(sink_node.inputs)["payload"]
    results = {operation.result_id: operation for operation in assembly.compute_nodes}
    assert results[sink_input].id == OperationId(
        SymbolId(scope=("outer", "child"), local_id="produce")
    )


def test_nested_compute_exports_preserve_exact_typed_result_values(
    tmp_path: Path,
) -> None:
    producer = _producer_module()
    child = producer.instantiate("child")

    @sc.module(id="test.outputs.typed-result-wrapper")
    def wrapper(context: sc.ModuleContext) -> None:
        context.call(child)
        context.export(payload=child.outputs.payload)

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

    @sc.module(id="test.outputs.typed-result-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(first)
        context.call(second)
        context.call(first_sink)
        context.call(second_sink)

    call = root()

    @sc.template(id="test.outputs.typed-result", kind="module_outputs")
    def template_definition(experiment: sc.ExperimentContext) -> None:
        experiment.run(call)

    program = _bind_program(
        template_definition(),
        load_config(),
    )
    nodes = {node.id: node for node in program.program.program.compute_nodes}
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
        edge = resolve_bound_value(
            program.program,
            program.bindings,
            dict(sink_node.inputs)["payload"],
        )
        assert isinstance(edge, ComputeResultScalarExpr)
        assert producer_node.result_type == expected_type
        assert producer_node.result_id.scope == (
            "typed-result-root",
            wrapper_scope,
            "child",
            "produce",
            "outputs",
        )
        assert producer_node.result_id.local_id == "result"
        assert edge.value_id == producer_node.result_id
        assert edge.value_type == expected_type


def test_passthrough_and_expression_exports_bind_instance_inputs() -> None:
    @sc.module(id="test.outputs.expressions")
    def module(context: sc.ModuleContext, value: _FloatInput) -> None:
        value_ref = sc.input_ref(value)
        context.export(passthrough=value_ref, shifted=value_ref + 0.5)

    invocation = module.instantiate("expression-instance", value=1.25)

    @sc.module(id="test.outputs.expression-consumer")
    def consumer_module(
        context: sc.ModuleContext,
        passthrough: _FloatInput,
        shifted: _FloatInput,
    ) -> None:
        context.compute(
            "capture",
            fn=_capture_pair,
            inputs={"passthrough": passthrough, "shifted": shifted},
            output_type=sc.ScalarType(sc.PayloadType("test.export-capture")),
        )

    consumer = consumer_module.instantiate(
        "consumer",
        passthrough=invocation.outputs.passthrough,
        shifted=invocation.outputs.shifted,
    )

    @sc.module(id="test.outputs.expression-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(invocation)
        context.call(consumer)

    flattened = compose_module(root.definition)
    capture_node = next(
        operation
        for operation in flattened.compute_nodes
        if operation.id.local_id == "capture"
    )
    capture_inputs = dict(capture_node.inputs)
    definitions = {definition.id: definition for definition in flattened.value_defs}
    passthrough = definitions[capture_inputs["passthrough"]]
    assert isinstance(passthrough.source, ScalarExpr)
    assert (
        evaluate_scalar(
            passthrough.source,
            EvalContext(),
        )
        == 1.25
    )
    shifted = definitions[capture_inputs["shifted"]]
    assert isinstance(shifted.source, ScalarExpr)
    assert (
        evaluate_scalar(
            shifted.source,
            EvalContext(),
        )
        == 1.75
    )
    assert set(invocation.outputs) == {"passthrough", "shifted"}


def test_direct_export_preserves_its_declared_assignable_input_type() -> None:
    ghz_type = sc.ScalarType(sc.QuantityType(unit="GHz"))

    @sc.module(id="test.outputs.assignable-direct-export")
    def source(context: sc.ModuleContext, value: _GhzQuantityInput) -> None:
        context.export(value=sc.input_ref(value))

    @sc.module(id="test.outputs.assignable-direct-export-root")
    def root(context: sc.ModuleContext, value: _MhzQuantityInput) -> None:
        instance = context.call(source.instantiate("source", value=sc.input_ref(value)))
        context.compute(
            "capture",
            fn=_identity_consumed,
            inputs={"consumed": instance.outputs.value},
            output_type=ghz_type,
        )

    flattened = compose_module(root.definition)
    capture = next(
        node for node in flattened.compute_nodes if node.id.local_id == "capture"
    )
    captured_id = dict(capture.inputs)["consumed"]
    captured = next(
        definition
        for definition in flattened.value_defs
        if definition.id == captured_id
    )

    assert dict(capture.input_types) == {"consumed": ghz_type}
    assert captured.value_type == ghz_type


def test_direct_table_export_preserves_its_declared_assignable_input_type() -> None:
    @sc.module(id="test.outputs.assignable-direct-table-export")
    def source(context: sc.ModuleContext, rows: _GhzFrequencyTableInput) -> None:
        context.export(rows=sc.input_ref(rows))

    @sc.module(id="test.outputs.assignable-direct-table-export-root")
    def root(context: sc.ModuleContext, rows: _MhzFrequencyTableInput) -> None:
        instance = context.call(source.instantiate("source", rows=sc.input_ref(rows)))
        context.export(rows=instance.outputs.rows)

    flattened = compose_module(root.definition)

    assert [(port.id, port.value_type) for port in flattened.input_ports] == [
        ("rows", _MHZ_FREQUENCY_TABLE)
    ]


def test_invocation_validates_typed_and_literal_inputs_immediately() -> None:
    @sc.module(id="test.outputs.validation")
    def module(
        context: sc.ModuleContext,
        payload: _PayloadInput,
        count: _PositiveIntInput,
    ) -> None:
        del context, payload, count

    incompatible = program_input(
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
    @sc.module(id="test.outputs.product")
    def module(context: sc.ModuleContext) -> None:
        context._product("signal")

    child = module.instantiate("child")

    assert child.products["signal"].id == "child/signal"


def test_module_export_arithmetic_resolves_during_elaboration() -> None:
    value_type = sc.ScalarType(sc.FloatType())

    @sc.module(id="test.outputs.expression-boundary")
    def source(context: sc.ModuleContext, value: _FloatInput) -> None:
        context.export(value=sc.input_ref(value))

    source_instance = source.instantiate("source", value=1.0)
    exported = source_instance.outputs.value
    shifted = exported + 1.0

    @sc.module(id="test.outputs.expression-boundary-consumer")
    def consumer_module(context: sc.ModuleContext, consumed: _FloatInput) -> None:
        context.compute(
            "capture",
            fn=_identity_consumed,
            inputs={"consumed": consumed},
            output_type=value_type,
        )

    consumer = consumer_module.instantiate("consumer", consumed=shifted)

    @sc.module(id="test.outputs.expression-boundary-root")
    def root(context: sc.ModuleContext) -> None:
        context.call(source_instance)
        context.call(consumer)

    flattened = compose_module(root.definition)
    capture_node = next(
        semantic_operation
        for semantic_operation in flattened.compute_nodes
        if semantic_operation.id.local_id == "capture"
    )
    captured = dict(capture_node.inputs)["consumed"]
    definitions = {definition.id: definition for definition in flattened.value_defs}
    shifted_definition = definitions[captured]
    assert isinstance(shifted_definition.source, ScalarExpr)
    assert (
        evaluate_scalar(
            shifted_definition.source,
            EvalContext(),
        )
        == 2.0
    )


def test_duplicate_explicit_instance_ids_are_rejected() -> None:
    producer = _producer_module()

    with pytest.raises(ValueError, match="duplicate module instance ids: 'duplicate'"):

        @sc.module(id="test.outputs.duplicate-instance")
        def duplicate_instance(context: sc.ModuleContext) -> None:
            context.call(producer.instantiate("duplicate"))
            context.call(producer.instantiate("duplicate"))


def test_output_refs_are_nominally_owned_by_the_used_instance() -> None:
    foreign = _producer_module().instantiate("same")
    selected = _producer_module().instantiate("same")
    sink = _consumer_module().instantiate(
        "sink",
        payload=foreign.outputs.payload,
    )
    with pytest.raises(CheckFailed) as error:

        @sc.module(id="test.outputs.nominal")
        def nominal(context: sc.ModuleContext) -> None:
            context.call(selected)
            context.call(sink)

    assert [problem.code for problem in error.value.problems] == [
        "module_export_foreign_instance"
    ]


def test_output_roots_preserve_free_inputs_and_value_provenance() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    parameter = sc.parameter("output_parameter", value_type)
    point = sc.coordinate("output_point", value_type)

    @sc.module(id="test.outputs.roots")
    def source(
        context: sc.ModuleContext,
        value: _FloatInput,
        parameter_value: _FloatInput,
        point_value: _FloatInput,
    ) -> None:
        context.export(
            value=sc.input_ref(value),
            parameter=sc.input_ref(parameter_value),
            point=sc.input_ref(point_value),
        )

    @sc.module(id="test.outputs.roots.wrapper")
    def wrapper(context: sc.ModuleContext, value: _FloatInput) -> None:
        source_instance = context.call(
            source.instantiate(
                "source",
                value=sc.input_ref(value),
                parameter_value=0.0,
                point_value=0.0,
            )
        )
        context.export(value=source_instance.outputs.value)

    @sc.template(id="test.outputs.roots", kind="outputs")
    def template(
        experiment: sc.ExperimentContext,
        value: _FloatInput,
    ) -> None:
        experiment.run(
            source(
                value=value,
                parameter_value=parameter,
                point_value=point,
            )
        )
        experiment.scan(sc.axis(point, (1.0,)))

    assembly = compile_invocation(template(value=1.0)).program.program

    assert [
        (port.id, port.value_type) for port in wrapper.definition.interface.imports
    ] == [("value", value_type)]
    assert assembly.parameter_contracts == (
        ParameterValueContract("output_parameter", value_type),
    )
    assert [dependency.id for dependency in assembly.point_dependencies] == [
        "output_point"
    ]
