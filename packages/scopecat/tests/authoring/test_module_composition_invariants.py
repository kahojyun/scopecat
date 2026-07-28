from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import scopecat as sc
from scopecat.compiler.frontend.elaboration import (
    SemanticExperimentIR,
    elaborate_module,
)
from scopecat.compiler.frontend.graph_validation import (
    VerifiedAssemblyGraph,
    verify_assembly_graph,
)
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.semantic.model import (
    ValueUse,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.symbols import SymbolId
from tests.testkit.authoring import template_fixture

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


def _combine_payload_and_label(*, payload: object, label: str) -> dict[str, object]:
    return {"payload": payload, "label": label}


def _identity_payload(*, payload: object) -> object:
    return payload


def _composable_module() -> sc.ExperimentModule[...]:
    payload_type = _payload_type()
    produce = sc.compute(
        "produce",
        fn=lambda: {"value": 1},
        output_type=payload_type,
    )
    consume = sc.compute(
        "consume",
        fn=_combine_payload_and_label,
        inputs={
            "payload": produce.output,
            "label": "stable",
        },
        output_type=payload_type,
    )
    return (
        sc.module_body(id="test.composition-invariant.source")
        .resource("source", requires=("test.measure/v1",))
        .bind_property(
            "source",
            interface="test.measure/v1",
            property="mode",
            value="fast",
        )
        .computes(consume, produce)
        .export(payload=consume.output)
        .product("signal", unit="ratio")
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            interface="test.measure/v1",
            acquisition="sample",
        )
        .build()
    )


def _consumer_module() -> sc.ExperimentModule[...]:
    payload = sc.input("payload", _payload_type())
    consume = sc.compute(
        "consume-export",
        fn=_identity_payload,
        inputs={"payload": payload},
        output_type=_payload_type(),
    )
    return (
        sc.module_body(id="test.composition-invariant.consumer")
        .inputs(payload)
        .computes(consume)
        .build()
    )


def _verified_assembly(
    instance_id: str,
) -> tuple[SemanticExperimentIR, VerifiedAssemblyGraph]:
    instance = _composable_module().instantiate(instance_id)
    root = sc.module_body(id="test.composition-invariant.root").use(instance).build()
    assembly = elaborate_module(root.ir)
    return assembly, verify_assembly_graph(assembly)


def _nested_exporting_module(scope: tuple[str, ...]) -> sc.ExperimentModule[...]:
    invocation = _composable_module().instantiate(scope[-1])
    current = (
        sc.module_body(id="test.composition-invariant.generated-wrapper.0")
        .use(invocation)
        .export(payload=invocation.outputs.payload)
        .build()
    )
    for depth, instance_id in enumerate(reversed(scope[:-1]), start=1):
        invocation = current.instantiate(instance_id)
        current = (
            sc.module_body(id=f"test.composition-invariant.generated-wrapper.{depth}")
            .use(invocation)
            .export(payload=invocation.outputs.payload)
            .build()
        )
    return current


def _normalized_signature(
    assembly: SemanticExperimentIR,
    verified: VerifiedAssemblyGraph,
) -> tuple[object, ...]:
    resources = {port.symbol_id: port.id for port in assembly.resource_ports}
    semantic_graph = verified.semantic_graph.graph
    definitions = verified.semantic_graph.value_defs
    results = verified.semantic_graph.operation_results

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
            operation.id.scope for operation in verified.semantic_graph.graph.operations
        } == {(instance_id,)}
        assert {product.scope for product in assembly.product_declarations} == {
            (instance_id,)
        }
        signatures.append(_normalized_signature(assembly, verified))

    assert all(signature == signatures[0] for signature in signatures[1:])


def test_module_metadata_remains_declaration_introspection_only() -> None:
    left = sc.module_body(id="test.metadata.left", metadata={"shared": "left"}).build()
    right = sc.module_body(
        id="test.metadata.right", metadata={"shared": "right"}
    ).build()
    assert left.metadata == {"shared": "left"}
    assert right.metadata == {"shared": "right"}

    for first, second in ((left, right), (right, left)):
        root = (
            sc.module_body(id="test.metadata.root", metadata={"owner": "root"})
            .use(first.instantiate("first"), second.instantiate("second"))
            .build()
        )
        assert root.metadata == {"owner": "root"}
        assert not hasattr(elaborate_module(root.ir), "metadata")


@settings(max_examples=50)
@given(
    instance_ids=st.lists(_GENERATED_INSTANCE_ID, min_size=2, max_size=2, unique=True)
)
def test_generated_alpha_renaming_preserves_normalized_semantics(
    instance_ids: list[str],
) -> None:
    for instance_id in instance_ids:
        instance = _composable_module().instantiate(instance_id)
        root = (
            sc.module_body(id="test.composition-invariant.generated-alpha-root")
            .use(instance)
            .build()
        )
        compile_invocation(
            template_fixture(
                root,
                id="test.composition-invariant.generated-alpha",
                kind="contract",
            ).bind()
        )


def test_structural_scopes_keep_separator_lookalikes_injective() -> None:
    child = _composable_module()
    direct = child.instantiate("a/b")
    nested_child = child.instantiate("b")
    wrapper = (
        sc.module_body(id="test.composition-invariant.wrapper")
        .use(nested_child)
        .build()
    )
    nested = wrapper.instantiate("a")
    root = (
        sc.module_body(id="test.composition-invariant.injective")
        .use(direct, nested)
        .build()
    )

    assembly = elaborate_module(root.ir)
    verified = verify_assembly_graph(assembly)

    node_ids = {operation.id for operation in verified.semantic_graph.graph.operations}
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
    wrapper = (
        sc.module_body(id="test.composition-invariant.generated-injective-wrapper")
        .use(nested_child)
        .build()
    )
    nested = wrapper.instantiate(left)
    root = (
        sc.module_body(id="test.composition-invariant.generated-injective-root")
        .use(direct, nested)
        .build()
    )

    nested_product = next(iter(nested.products.values()))
    template_fixture(
        root,
        id="test.composition-invariant.generated-injective",
        kind="contract",
        records=(
            sc.record_product(direct.products.signal, record_id="direct_signal"),
            sc.record_product(nested_product, record_id="nested_signal"),
        ),
    )


def test_repeated_config_free_verification_is_deterministic() -> None:
    instance = _composable_module().instantiate("stable")
    root = sc.module_body(id="test.composition-invariant.stable").use(instance).build()

    signatures: list[tuple[object, ...]] = []
    for _ in range(5):
        assembly = elaborate_module(root.ir)
        verified = verify_assembly_graph(assembly)
        signatures.append(_normalized_signature(assembly, verified))
        assert [
            operation.id.local_id
            for operation in verified.semantic_graph.graph.operations
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
    root = (
        sc.module_body(id="test.composition-invariant.export-consumer")
        .use(source, sink)
        .build()
    )

    verified = verify_assembly_graph(elaborate_module(root.ir))
    sink_node = next(
        operation
        for operation in verified.semantic_graph.graph.operations
        if operation.id.scope == ("sink",) and operation.id.local_id == "consume-export"
    )
    payload_input = dict(sink_node.inputs)["payload"]
    producer = verified.semantic_graph.operation_results[payload_input.value_id].id

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
    root = (
        sc.module_body(id="test.composition-invariant.generated-export-root")
        .use(source, sink)
        .build()
    )

    compile_invocation(
        template_fixture(
            root,
            id="test.composition-invariant.generated-export",
            kind="contract",
        ).bind()
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
        (
            sc.module_body(id="test.composition-invariant.generated-foreign-root")
            .use(selected, sink)
            .build()
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
        (
            sc.module_body(id="test.composition-invariant.foreign-output")
            .use(selected, sink)
            .build()
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
    root = (
        sc.module_body(id="test.composition-invariant.foreign-product")
        .use(selected)
        .build()
    )

    template = template_fixture(
        root,
        id="test.composition-invariant.foreign-product",
        kind="contract",
        records=(sc.record_product(foreign.products.signal),),
    )

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template())

    assert [problem.code for problem in error.value.problems] == [
        "module_product_foreign_instance"
    ]
