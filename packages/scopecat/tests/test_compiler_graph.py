from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat._compiler.graph import ComputeGraphError, order_compute_nodes
from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ComputeEdge, TypedComputeNode
from scopecat.authoring._resolution import resolve_experiment
from scopecat.value_types import Float, Int, Payload, Scalar
from tests.support.authoring import load_config

FLOAT = Scalar(Float())


def _node(local_id: str, *producers: str) -> TypedComputeNode:
    return TypedComputeNode(
        id=NodeId(local_id=local_id),
        inputs={
            f"input_{index}": ComputeEdge(
                producer=NodeId(local_id=producer),
                value_type=FLOAT,
            )
            for index, producer in enumerate(producers)
        },
        output_type=FLOAT,
        fn=lambda: 0.0,
    )


def test_compute_graph_uses_declaration_stable_topological_order() -> None:
    consumer = _node("consumer", "producer")
    independent = _node("independent")
    producer = _node("producer")

    ordered = order_compute_nodes((consumer, independent, producer))

    assert [node.id.local_id for node in ordered] == [
        "independent",
        "producer",
        "consumer",
    ]


def test_node_qualified_name_encodes_structural_segments_injectively() -> None:
    embedded_separator = NodeId(scope=("a/b",), local_id="c")
    separate_segments = NodeId(scope=("a", "b"), local_id="c")

    assert embedded_separator != separate_segments
    assert embedded_separator.qualified_name == "a%2Fb/c"
    assert separate_segments.qualified_name == "a/b/c"


def test_compute_graph_rejects_missing_producer() -> None:
    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((_node("consumer", "missing"),))

    assert error.value.code == "compute_producer_missing"
    assert error.value.path == "compute_nodes.consumer.inputs.input_0"


def test_compute_graph_rejects_duplicate_producers() -> None:
    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((_node("duplicate"), _node("duplicate")))

    assert error.value.code == "compute_producer_duplicate"
    assert error.value.path == "compute_nodes.duplicate"


def test_compute_graph_rejects_edge_type_mismatch() -> None:
    producer = _node("producer")
    consumer = TypedComputeNode(
        id=NodeId(local_id="consumer"),
        inputs={
            "value": ComputeEdge(
                producer=producer.id,
                value_type=Scalar(Int()),
            )
        },
        output_type=FLOAT,
    )

    with pytest.raises(ComputeGraphError) as error:
        order_compute_nodes((producer, consumer))

    assert error.value.code == "compute_edge_type_mismatch"
    assert error.value.path == "compute_nodes.consumer.inputs.value"


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


def test_cross_module_compute_edges_are_scoped_and_topologically_ordered(
    tmp_path: Path,
) -> None:
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
        .use(child(program=produce.output), child(program=produce.output))
        .build()
    )

    resolved = resolve_experiment(
        parent.template("test.compiler.graph", kind="compiler_graph").build().bind(),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    nodes = resolved.experiment.compute_nodes
    assert [node.id.local_id for node in nodes] == ["produce", "consume", "consume"]
    assert nodes[0].id.scope == ()
    assert nodes[1].id.scope == ("test.compiler.graph.child[0]",)
    assert nodes[2].id.scope == ("test.compiler.graph.child[1]",)
    for consumer in nodes[1:]:
        edge = consumer.inputs["program"]
        assert isinstance(edge, ComputeEdge)
        assert edge.producer == nodes[0].id
