from __future__ import annotations

import pytest

import scopecat as sc
from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedComputeOutput,
)
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._semantic_graph import (
    OperationId,
    OperationOutputSource,
    ValueId,
    ValueUse,
    operation_result_id,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._resolution import compile_prepared_invocation
from scopecat.problems import model_location
from scopecat.value_types import Float, Int, Payload, Scalar

FLOAT = Scalar(Float())
EXECUTE_POINT = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)


def _operation_id(local_id: str) -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _output(
    operation_id: OperationId,
    *,
    value_type: Scalar = FLOAT,
    value_id: ValueId | None = None,
) -> TypedComputeOutput:
    return TypedComputeOutput(
        id=value_id or operation_result_id(operation_id),
        value_type=value_type,
        availability=EXECUTE_POINT,
    )


def _node(local_id: str, *producers: str) -> TypedComputeNode:
    operation_id = _operation_id(local_id)
    return TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs={
            f"input_{index}": ComputeEdge(
                value_id=operation_result_id(_operation_id(producer)),
                expected_type=FLOAT,
            )
            for index, producer in enumerate(producers)
        },
        result=_output(operation_id),
    )


def test_compute_graph_uses_identity_stable_topological_order() -> None:
    consumer = _node("consumer", "producer")
    independent = _node("independent")
    producer = _node("producer")

    ordered = order_compute_nodes((consumer, independent, producer))

    assert [node.id.local_id for node in ordered] == [
        "independent",
        "producer",
        "consumer",
    ]

    assert order_compute_nodes((_node("z"), _node("a"))) == order_compute_nodes(
        (_node("a"), _node("z"))
    )


def test_symbol_qualified_name_encodes_structural_segments_injectively() -> None:
    embedded_separator = SymbolId(scope=("a/b",), local_id="c")
    separate_segments = SymbolId(scope=("a", "b"), local_id="c")

    assert embedded_separator != separate_segments
    assert embedded_separator.qualified_name == "a%2Fb/c"
    assert separate_segments.qualified_name == "a/b/c"


def test_compute_problem_location_keeps_node_scope_structural() -> None:
    operation_id = OperationId(SymbolId(scope=("a/b",), local_id="c"))
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        result=_output(operation_id),
    )

    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((node, node))

    assert error.value.location == model_location("compute_nodes", "a/b", "c")


def test_compute_graph_rejects_missing_producer() -> None:
    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((_node("consumer", "missing"),))

    assert error.value.code == "compute_output_missing"
    assert error.value.location == model_location(
        "compute_nodes", "consumer", "inputs", "input_0"
    )


def test_compute_graph_rejects_duplicate_operations() -> None:
    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((_node("duplicate"), _node("duplicate")))

    assert error.value.code == "compute_operation_duplicate"
    assert error.value.location == model_location("compute_nodes", "duplicate")


def test_compute_graph_rejects_duplicate_output_definitions() -> None:
    shared_output_id = ValueId(SymbolId(local_id="shared"))
    first_id = _operation_id("first")
    second_id = _operation_id("second")

    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes(
            (
                TypedComputeNode(
                    id=first_id,
                    contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    result=_output(first_id, value_id=shared_output_id),
                ),
                TypedComputeNode(
                    id=second_id,
                    contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    result=_output(second_id, value_id=shared_output_id),
                ),
            )
        )

    assert error.value.code == "compute_output_duplicate"
    assert error.value.location == model_location(
        "compute_nodes", "second", "result", "id"
    )


def test_compute_graph_rejects_edge_type_mismatch() -> None:
    producer = _node("producer")
    consumer_id = _operation_id("consumer")
    consumer = TypedComputeNode(
        id=consumer_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs={
            "value": ComputeEdge(
                value_id=producer.result.id,
                expected_type=Scalar(Int()),
            )
        },
        result=_output(consumer_id),
    )

    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((producer, consumer))

    assert error.value.code == "compute_edge_type_mismatch"
    assert error.value.location == model_location(
        "compute_nodes", "consumer", "inputs", "value"
    )


def test_compute_value_and_operation_identities_are_nominally_disjoint() -> None:
    symbol = SymbolId(local_id="same")

    assert OperationId(symbol) != ValueId(symbol)


@pytest.mark.parametrize(
    "nodes",
    [
        (_node("self", "self"),),
        (_node("left", "right"), _node("right", "left")),
    ],
)
def test_compute_graph_rejects_cycles(
    nodes: tuple[TypedComputeNode, ...],
) -> None:
    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes(nodes)

    assert error.value.code == "compute_graph_cycle"
    assert " -> " in str(error.value)


def test_cross_module_compute_edges_are_scoped_and_topologically_ordered() -> None:
    payload_type = Scalar(Payload("compiler.graph.payload"))
    child_input = sc.input("program", payload_type)
    consume = sc.compute(
        "consume",
        fn=lambda *, program: program,
        inputs={"program": child_input},
        output_type=payload_type,
    )
    child = (
        sc.module("test.compiler.graph.child")
        .inputs(child_input)
        .computes(consume)
        .build()
    )
    produce = sc.compute(
        "produce",
        fn=lambda: {"ok": True},
        output_type=payload_type,
    )
    parent = (
        sc.module("test.compiler.graph.parent")
        .computes(produce)
        .use(
            child.instantiate("first-consumer", program=produce.output),
            child.instantiate("second-consumer", program=produce.output),
        )
        .build()
    )

    invocation = (
        parent.template("test.compiler.graph", kind="compiler_graph").build().bind()
    )
    compiled = compile_prepared_invocation(prepare_invocation(invocation))
    graph = compiled.assembly.semantic_graph
    definitions = {definition.id: definition for definition in graph.value_defs}

    operations = graph.operations
    assert [operation.id.local_id for operation in operations] == [
        "produce",
        "consume",
        "consume",
    ]
    assert operations[0].id.scope == ()
    assert operations[1].id.scope == ("first-consumer",)
    assert operations[2].id.scope == ("second-consumer",)
    for consumer in operations[1:]:
        use = dict(consumer.inputs)["program"]
        assert isinstance(use, ValueUse)
        source = definitions[use.value_id].source
        assert source == OperationOutputSource(operations[0].id)
