from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.semantic.model import (
    ValueUse,
)
from scopecat.graph.values import (
    OperationId,
    ValueId,
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

    @sc.module(id="test.compiler.graph.child")
    def child(
        module: sc.ModuleContext,
        program: Annotated[
            sc.Input[dict[str, object]],
            sc.PayloadType("compiler.graph.payload"),
        ],
    ) -> None:
        module.compute(
            "consume",
            fn=_identity_program,
            inputs={"program": sc.input_ref(program)},
            output_type=payload_type,
        )

    @sc.module(id="test.compiler.graph.parent")
    def parent(module: sc.ModuleContext) -> None:
        produce = module.compute(
            "produce",
            fn=lambda: {"ok": True},
            output_type=payload_type,
        )
        module.call(
            child.instantiate("first-consumer", program=produce),
        )
        module.call(
            child.instantiate("second-consumer", program=produce),
        )

    @sc.template(id="test.compiler.graph", kind="compiler_graph")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(parent())

    invocation = template.bind()
    compiled = compile_invocation(invocation)
    graph = compiled.assembly.graph.semantic_graph.graph
    operations = graph.operations
    assert [operation.id.local_id for operation in operations] == [
        "produce",
        "consume",
        "consume",
    ]
    assert operations[0].id.scope == ("parent",)
    assert operations[1].id.scope == ("parent", "first-consumer")
    assert operations[2].id.scope == ("parent", "second-consumer")
    for consumer in operations[1:]:
        use = dict(consumer.inputs)["program"]
        assert isinstance(use, ValueUse)
        assert use.value_id == operations[0].result_id


def _identity_program(*, program: object) -> object:
    return program
