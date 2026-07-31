from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import scopecat as sc
from scopecat.authoring import MetadataValue
from scopecat.compiler.frontend.elaboration import (
    LogicalProgram,
    compose_module,
)
from scopecat.compiler.frontend.logical_verification import (
    VerifiedLogicalProgram,
    verify_logical_program,
)
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.semantic.model import (
    ValueUse,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.symbols import SymbolId
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
_GENERATED_INSTANCE_ID = st.text(
    alphabet=tuple("abcXYZ019._/%-[] é量"),
    min_size=1,
    max_size=12,
)
_GENERATED_SCOPE = st.lists(
    _GENERATED_INSTANCE_ID,
    min_size=1,
    max_size=4,
).map(tuple)

# Generated cases target observable authoring behavior through public checks.
# Fixed examples below retain the few deliberate contracts on the current IR.


def _payload_type() -> sc.ScalarType:
    return sc.ScalarType(sc.PayloadType("test.composition-invariant"))


type _PayloadInput = Annotated[
    sc.Input[object],
    sc.ScalarType(sc.PayloadType("test.composition-invariant")),
]


def _combine_payload_and_label(*, payload: object, label: str) -> dict[str, object]:
    return {"payload": payload, "label": label}


def _identity_payload(*, payload: object) -> object:
    return payload


def _composable_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()

    @sc.module(id="test.composition-invariant.source")
    def module(context: sc.ModuleContext) -> None:
        source = context.resource("source", requires=(_MEASURE,))
        context.bind_property(
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
        context.export(payload=consumed)
        signal = context.product("signal", unit="ratio")
        context.acquire(
            "read-signal",
            resource=source,
            results={_MEASURE_SAMPLE_SIGNAL: signal},
        )

    return module


def _consumer_module() -> sc.ExperimentModule[...]:
    @sc.module(id="test.composition-invariant.consumer")
    def module(context: sc.ModuleContext, payload: _PayloadInput) -> None:
        context.compute(
            "consume-export",
            fn=_identity_payload,
            inputs={"payload": sc.input_ref(payload)},
            output_type=_payload_type(),
        )

    return module


def _compose_module(
    id: str,
    *parts: sc.ModuleInvocation,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> sc.ExperimentModule[...]:
    @sc.module(id=id, metadata=metadata)
    def module(context: sc.ModuleContext) -> None:
        for part in parts:
            context.call(part)

    return module


def _compile_invocations(
    *invocations: sc.ModuleInvocation,
    id: str,
) -> None:
    @sc.template(id=id, kind="contract")
    def experiment(context: sc.ExperimentContext) -> None:
        for invocation in invocations:
            context.run(invocation)

    compile_invocation(experiment())


def _exporting_wrapper(
    id: str,
    invocation: sc.ModuleInvocation,
) -> sc.ExperimentModule[...]:
    @sc.module(id=id)
    def module(context: sc.ModuleContext) -> None:
        context.call(invocation)
        context.export(payload=invocation.outputs.payload)

    return module


def _verified_assembly(
    instance_id: str,
) -> tuple[LogicalProgram, VerifiedLogicalProgram]:
    instance = _composable_module().instantiate(instance_id)
    root = _compose_module("test.composition-invariant.root", instance)
    assembly = compose_module(root.ir)
    return assembly, verify_logical_program(assembly)


def _nested_exporting_module(scope: tuple[str, ...]) -> sc.ExperimentModule[...]:
    invocation = _composable_module().instantiate(scope[-1])
    current = _exporting_wrapper(
        "test.composition-invariant.generated-wrapper.0",
        invocation,
    )
    for depth, instance_id in enumerate(reversed(scope[:-1]), start=1):
        invocation = current.instantiate(instance_id)
        current = _exporting_wrapper(
            f"test.composition-invariant.generated-wrapper.{depth}",
            invocation,
        )
    return current


def _normalized_signature(
    assembly: LogicalProgram,
    verified: VerifiedLogicalProgram,
) -> tuple[object, ...]:
    resources = {port.symbol_id: port.id for port in assembly.resource_ports}
    semantic_graph = verified.program.semantic_graph
    definitions = verified.value_defs
    results = verified.operation_results

    def input_signature(value: ValueUse) -> object:
        operation = results.get(value.value_id)
        if operation is not None:
            return ("compute", operation.id.local_id, operation.result_type)
        definition = definitions[value.value_id]
        return (type(definition.source).__name__, definition.value_type)

    return (
        tuple((port.id, port.selector.interfaces) for port in assembly.resource_ports),
        tuple(
            (
                operation.id.local_id,
                tuple(
                    (input_id, input_signature(value))
                    for input_id, value in operation.inputs
                ),
                operation.result_type,
            )
            for operation in semantic_graph.operations
        ),
        tuple(
            (
                resources[binding.port_id],
                binding.interface_id,
                binding.property_id,
                binding.value,
            )
            for binding in assembly.bindings
        ),
        tuple(
            (
                product.id,
                product.unit,
                product.dtype,
            )
            for product in assembly.product_declarations
        ),
    )


def test_alpha_renaming_changes_only_structural_instance_scope() -> None:
    signatures: list[tuple[object, ...]] = []

    for instance_id in _INSTANCE_IDS:
        assembly, verified = _verified_assembly(instance_id)

        assert {port.scope for port in assembly.resource_ports} == {(instance_id,)}
        assert {
            operation.id.scope
            for operation in verified.program.semantic_graph.operations
        } == {(instance_id,)}
        assert {product.scope for product in assembly.product_declarations} == {
            (instance_id,)
        }
        signatures.append(_normalized_signature(assembly, verified))

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
    assert compose_module(left.ir) == compose_module(right.ir)


@settings(max_examples=50)
@given(
    instance_ids=st.lists(_GENERATED_INSTANCE_ID, min_size=2, max_size=2, unique=True)
)
def test_generated_alpha_renaming_preserves_normalized_semantics(
    instance_ids: list[str],
) -> None:
    for instance_id in instance_ids:
        instance = _composable_module().instantiate(instance_id)
        _compile_invocations(
            instance,
            id="test.composition-invariant.generated-alpha",
        )


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

    assembly = compose_module(root.ir)
    verified = verify_logical_program(assembly)

    node_ids = {
        operation.id for operation in verified.program.semantic_graph.operations
    }
    resource_ids = {port.qualified_id for port in assembly.resource_ports}
    product_ids = {product.product_id for product in assembly.product_declarations}

    assert {node_id.scope for node_id in node_ids} == {("a/b",), ("a", "b")}
    assert len({node_id.qualified_name for node_id in node_ids}) == 4
    assert resource_ids == {"a%2Fb/source", "a/b/source"}
    assert product_ids == {
        ProductId(SymbolId(scope=("a/b",), local_id="signal")),
        ProductId(SymbolId(scope=("a", "b"), local_id="signal")),
    }


@settings(max_examples=50)
@given(left=_GENERATED_INSTANCE_ID, right=_GENERATED_INSTANCE_ID)
def test_generated_structural_scopes_are_injective(
    left: str,
    right: str,
) -> None:
    child = _composable_module()
    direct_scope = f"{left}/{right}"
    direct = child.instantiate(direct_scope)
    nested_child = child.instantiate(right)
    wrapper = _compose_module(
        "test.composition-invariant.generated-injective-wrapper",
        nested_child,
    )
    nested = wrapper.instantiate(left)

    nested_product = next(iter(nested.products.values()))

    @sc.template(
        id="test.composition-invariant.generated-injective",
        kind="contract",
    )
    def experiment(context: sc.ExperimentContext) -> None:
        context.run(direct)
        context.run(nested)
        context.record(direct.products.signal, record_id="direct_signal")
        context.record(nested_product, record_id="nested_signal")

    compile_invocation(experiment())


def test_repeated_config_free_verification_is_deterministic() -> None:
    instance = _composable_module().instantiate("stable")
    root = _compose_module("test.composition-invariant.stable", instance)

    signatures: list[tuple[object, ...]] = []
    for _ in range(5):
        assembly = compose_module(root.ir)
        verified = verify_logical_program(assembly)
        signatures.append(_normalized_signature(assembly, verified))
        assert [
            operation.id.local_id
            for operation in verified.program.semantic_graph.operations
        ] == [
            "produce",
            "consume",
        ]

    assert all(signature == signatures[0] for signature in signatures[1:])


def test_scoped_export_can_feed_another_instance_without_capture() -> None:
    source = _composable_module().instantiate("source")
    sink = _consumer_module().instantiate(
        "sink",
        payload=source.outputs.payload,
    )
    root = _compose_module(
        "test.composition-invariant.export-consumer",
        source,
        sink,
    )

    verified = verify_logical_program(compose_module(root.ir))
    sink_node = next(
        operation
        for operation in verified.program.semantic_graph.operations
        if operation.id.scope == ("sink",) and operation.id.local_id == "consume-export"
    )
    payload_input = dict(sink_node.inputs)["payload"]
    producer = verified.operation_results[payload_input.value_id].id

    assert producer.scope == ("source",)
    assert producer.local_id == "consume"


@settings(max_examples=35)
@given(scope=_GENERATED_SCOPE)
def test_generated_nested_exports_preserve_producer_provenance(
    scope: tuple[str, ...],
) -> None:
    source = _nested_exporting_module(scope).instantiate("source")
    sink = _consumer_module().instantiate(
        "sink",
        payload=source.outputs.payload,
    )
    _compile_invocations(
        source,
        sink,
        id="test.composition-invariant.generated-export",
    )


@settings(max_examples=40)
@given(instance_id=_GENERATED_INSTANCE_ID)
def test_generated_nominal_ownership_rejects_same_named_foreign_outputs(
    instance_id: str,
) -> None:
    foreign = _composable_module().instantiate(instance_id)
    selected = _composable_module().instantiate(instance_id)
    sink = _consumer_module().instantiate(
        "sink",
        payload=foreign.outputs.payload,
    )
    with pytest.raises(CheckFailed) as error:
        _compose_module(
            "test.composition-invariant.generated-foreign-root",
            selected,
            sink,
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_export_foreign_instance"
    ]


@pytest.mark.parametrize("instance_id", _INSTANCE_IDS)
def test_same_named_foreign_output_fails_config_free_verification(
    instance_id: str,
) -> None:
    foreign = _composable_module().instantiate(instance_id)
    selected = _composable_module().instantiate(instance_id)
    sink = _consumer_module().instantiate(
        f"sink-{instance_id}",
        payload=foreign.outputs.payload,
    )
    with pytest.raises(CheckFailed) as error:
        _compose_module(
            "test.composition-invariant.foreign-output",
            selected,
            sink,
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_export_foreign_instance"
    ]


@pytest.mark.parametrize("instance_id", _INSTANCE_IDS)
def test_same_named_foreign_product_fails_at_compile(
    instance_id: str,
) -> None:
    foreign = _composable_module().instantiate(instance_id)
    selected = _composable_module().instantiate(instance_id)

    @sc.template(
        id="test.composition-invariant.foreign-product",
        kind="contract",
    )
    def template(context: sc.ExperimentContext) -> None:
        context.run(selected)
        context.record(foreign.products.signal)

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template())

    assert [problem.code for problem in error.value.problems] == [
        "module_product_foreign_instance"
    ]
