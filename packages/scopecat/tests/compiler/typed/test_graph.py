from __future__ import annotations

import scopecat as sc
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.compiler.semantic.model import (
    OperationId,
    OperationOutputSource,
    ValueId,
    ValueUse,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar


def test_symbol_qualified_name_encodes_structural_segments_injectively() -> None:
    embedded_separator = SymbolId(scope=("a/b",), local_id="c")
    separate_segments = SymbolId(scope=("a", "b"), local_id="c")

    assert embedded_separator != separate_segments
    assert embedded_separator.qualified_name == "a%2Fb/c"
    assert separate_segments.qualified_name == "a/b/c"


def test_compute_value_and_operation_identities_are_nominally_disjoint() -> None:
    symbol = SymbolId(local_id="same")

    assert OperationId(symbol) != ValueId(symbol)


def test_cross_module_compute_edges_are_scoped_and_topologically_ordered() -> None:
    payload_type = Scalar(Payload("compiler.graph.payload"))
    child_input = sc.input("program", payload_type)
    consume = sc.compute(
        "consume",
        fn=_identity_program,
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
    graph = compiled.assembly.graph.semantic_graph.graph
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


def _identity_program(*, program: object) -> object:
    return program
