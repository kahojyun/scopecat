"""Hierarchy composition and structural identity invariants."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import scopecat as sc
from scopecat.authoring import MetadataValue
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.logical_verification import (
    VerifiedLogicalProgram,
    verify_logical_program,
)
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.symbols import SymbolId
from scopecat.program.logical import LogicalProgram
from scopecat.sdk.instruments import InterfaceRef

_MEASURE = InterfaceRef("test.measure/v1")
_MEASURE_MODE = _MEASURE.property("mode")
_MEASURE_SAMPLE_SIGNAL = _MEASURE.acquisition("sample").result("signal")

_INSTANCE_IDS = (
    "alpha",
    "left.arm",
    "left/arm",
    "left%2Farm",
    "instance-01",
)


def _payload_type() -> sc.ScalarType:
    return sc.ScalarType(sc.PayloadType("test.composition-invariant"))


def _combine_payload_and_label(*, payload: object, label: str) -> dict[str, object]:
    return {"payload": payload, "label": label}


def _composable_module() -> sc.ExperimentModule[sc.ValueRef, ...]:
    payload_type = _payload_type()

    @sc.module(id="test.composition-invariant.source")
    def module(context: sc.ModuleContext) -> sc.ValueRef:
        source = context._resource("source", requires=(_MEASURE,))
        context._bind_property(
            source,
            _MEASURE_MODE,
            value="fast",
        )
        produced = context.compute(
            "produce",
            fn=lambda: {"value": 1},
            output_type=payload_type,
        )
        consumed = context.compute(
            "consume",
            fn=_combine_payload_and_label,
            inputs={
                "payload": produced,
                "label": "stable",
            },
            output_type=payload_type,
        )
        signal = context._product("signal", unit="ratio")
        context._acquire(
            "read-signal",
            resource=source,
            results={_MEASURE_SAMPLE_SIGNAL: signal},
        )
        return consumed

    return module


def _compose_module(
    id: str,
    *parts: sc.ModuleInvocation[Any],
    metadata: Mapping[str, MetadataValue] | None = None,
) -> sc.ExperimentModule[None, ...]:
    @sc.module(id=id, metadata=metadata)
    def module(context: sc.ModuleContext) -> None:
        for part in parts:
            context.use(part)

    return module


def _verified_program(
    instance_id: str,
) -> tuple[LogicalProgram, VerifiedLogicalProgram]:
    instance = _composable_module().instantiate(instance_id)
    root = _compose_module("test.composition-invariant.root", instance)
    program = compose_module(root.definition)
    return program, verify_logical_program(program)


def _normalized_signature(
    program: LogicalProgram,
    verified: VerifiedLogicalProgram,
) -> tuple[object, ...]:
    resources = {port.symbol_id: port.id for port in program.resource_ports}
    logical_program = verified.program
    definitions = verified.value_defs
    results = verified.operation_results

    def input_signature(value: ValueId) -> object:
        operation = results.get(value)
        if operation is not None:
            return ("compute", operation.id.local_id, operation.result_type)
        definition = definitions[value]
        return (type(definition.source).__name__, definition.value_type)

    return (
        tuple((port.id, port.selector.interfaces) for port in program.resource_ports),
        tuple(
            (
                operation.id.local_id,
                tuple(
                    (input_id, input_signature(value))
                    for input_id, value in operation.inputs
                ),
                operation.result_type,
            )
            for operation in logical_program.compute_nodes
        ),
        tuple(
            (
                resources[binding.port_id],
                binding.interface_id,
                binding.property_id,
                input_signature(binding.value_id),
            )
            for binding in program.bindings
        ),
        tuple(
            (
                product.id,
                product.unit,
                product.dtype,
            )
            for product in program.product_declarations
        ),
    )


def test_alpha_renaming_changes_only_structural_instance_scope() -> None:
    signatures: list[tuple[object, ...]] = []

    for instance_id in _INSTANCE_IDS:
        program, verified = _verified_program(instance_id)

        assert {port.scope for port in program.resource_ports} == {(instance_id,)}
        assert {operation.id.scope for operation in verified.program.compute_nodes} == {
            (instance_id,)
        }
        assert {product.scope for product in program.product_declarations} == {
            (instance_id,)
        }
        signatures.append(_normalized_signature(program, verified))

    assert all(signature == signatures[0] for signature in signatures[1:])


def test_module_metadata_remains_declaration_introspection_only() -> None:
    left = _compose_module(
        "test.metadata.module",
        metadata={"shared": "left"},
    )
    right = _compose_module(
        "test.metadata.module",
        metadata={"shared": "right"},
    )
    assert left.metadata == {"shared": "left"}
    assert right.metadata == {"shared": "right"}
    assert compose_module(left.definition) == compose_module(right.definition)


def test_structural_scopes_keep_separator_lookalikes_injective() -> None:
    child = _composable_module()
    direct = child.instantiate("a/b")
    nested_child = child.instantiate("b")
    wrapper = _compose_module(
        "test.composition-invariant.wrapper",
        nested_child,
    )
    nested = wrapper.instantiate("a")
    root = _compose_module(
        "test.composition-invariant.injective",
        direct,
        nested,
    )

    program = compose_module(root.definition)
    verified = verify_logical_program(program)

    node_ids = {operation.id for operation in verified.program.compute_nodes}
    resource_ids = {port.qualified_id for port in program.resource_ports}
    product_ids = {product.product_id for product in program.product_declarations}

    assert {node_id.scope for node_id in node_ids} == {("a/b",), ("a", "b")}
    assert len({node_id.qualified_name for node_id in node_ids}) == 4
    assert resource_ids == {"a%2Fb/source", "a/b/source"}
    assert product_ids == {
        ProductId(SymbolId(scope=("a/b",), local_id="signal")),
        ProductId(SymbolId(scope=("a", "b"), local_id="signal")),
    }
