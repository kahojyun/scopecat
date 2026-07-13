from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ComputeEdge
from scopecat._relations import EvalContext
from scopecat.authoring import ValueValidationError
from scopecat.authoring._module_composition import assemble_module_internal
from scopecat.authoring._module_handles import module_exposed_input_types_internal
from scopecat.authoring._resolution import resolve_experiment
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
    internal_value_ref_compute_node_id,
)
from scopecat.errors import CheckFailed
from tests.support.authoring import load_config


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

    assembly = assemble_module_internal(root)
    nodes = {node.node_id: node for node in assembly.compute_nodes}

    first_input = dict(
        nodes[NodeId(scope=("first-consumer",), local_id="consume")].inputs
    )["payload"]
    second_input = dict(
        nodes[NodeId(scope=("second-consumer",), local_id="consume")].inputs
    )["payload"]
    assert isinstance(first_input, ValueRef)
    assert isinstance(second_input, ValueRef)
    assert internal_value_ref_compute_node_id(first_input) == NodeId(
        scope=("first-producer",),
        local_id="produce",
    )
    assert internal_value_ref_compute_node_id(second_input) == NodeId(
        scope=("second-producer",),
        local_id="produce",
    )

    resolved = resolve_experiment(
        root.template("test.outputs.siblings", kind="module_outputs").build().bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )
    linked_nodes = {node.id: node for node in resolved.experiment.compute_nodes}
    first_edge = linked_nodes[
        NodeId(scope=("first-consumer",), local_id="consume")
    ].inputs["payload"]
    second_edge = linked_nodes[
        NodeId(scope=("second-consumer",), local_id="consume")
    ].inputs["payload"]
    assert isinstance(first_edge, ComputeEdge)
    assert isinstance(second_edge, ComputeEdge)
    assert first_edge.producer == NodeId(
        scope=("first-producer",),
        local_id="produce",
    )
    assert second_edge.producer == NodeId(
        scope=("second-producer",),
        local_id="produce",
    )


def test_exported_child_value_is_prefixed_when_parent_is_instantiated() -> None:
    producer = _producer_module()
    child = producer.instantiate("child")
    wrapper = (
        sc.module("test.outputs.wrapper")
        .use(child)
        .export(payload=child.outputs.payload)
        .build()
    )
    outer = wrapper.instantiate("outer")
    sink = _consumer_module().instantiate("sink", payload=outer.outputs.payload)
    root = sc.module("test.outputs.nested").use(outer, sink).build()

    assembly = assemble_module_internal(root)
    sink_node = next(node for node in assembly.compute_nodes if node.id == "consume")
    sink_input = dict(sink_node.inputs)["payload"]

    assert isinstance(sink_input, ValueRef)
    assert internal_value_ref_compute_node_id(sink_input) == NodeId(
        scope=("outer", "child"),
        local_id="produce",
    )


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

    passthrough = internal_lower_scalar_value_ref(invocation.outputs.passthrough)
    shifted = internal_lower_scalar_value_ref(invocation.outputs["shifted"])

    assert passthrough.eval(EvalContext()) == 1.25
    assert shifted.eval(EvalContext()) == 1.75
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
        module(payload=incompatible)
    with pytest.raises(ValueValidationError, match="value must be at least 1"):
        module.instantiate("invalid-literal", count=0)
    with pytest.raises(ValueError, match="must connect all inputs"):
        module.instantiate("missing-inputs")


def test_fixed_records_are_reserved_for_the_template_root() -> None:
    module = sc.module("test.outputs.fixed-record").record("signal").build()

    with pytest.raises(ValueError, match="must declare products"):
        module.instantiate("child")


def test_legacy_invocation_requires_explicit_identity_for_outputs() -> None:
    invocation = _producer_module()()

    with pytest.raises(ValueError, match=r"use module\.instantiate"):
        _ = invocation.outputs


def test_duplicate_explicit_instance_ids_are_rejected() -> None:
    producer = _producer_module()

    with pytest.raises(ValueError, match="duplicate instance ids: 'duplicate'"):
        sc.module("test.outputs.duplicate-instance").use(
            producer.instantiate("duplicate"),
            producer.instantiate("duplicate"),
        )


def test_output_refs_are_nominally_owned_by_the_used_instance(
    tmp_path: Path,
) -> None:
    foreign = _producer_module().instantiate("same")
    selected = _producer_module().instantiate("same")
    sink = _consumer_module().instantiate(
        "sink",
        payload=foreign.outputs.payload,
    )
    root = sc.module("test.outputs.nominal").use(selected, sink).build()

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            root.template("test.outputs.nominal", kind="module_outputs").build().bind(),
            workspace=tmp_path,
            config_profile=load_config(),
        )

    assert [problem.code for problem in error.value.problems] == [
        "compute_value_foreign_instance"
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

    assembly = assemble_module_internal(source)

    assert module_exposed_input_types_internal(wrapper) == {"value": value_type}
    assert [contract.parameter_id for contract in assembly.parameter_contracts] == [
        "output_parameter"
    ]
    assert [dependency.id for dependency in assembly.point_dependencies] == [
        "output_point"
    ]
