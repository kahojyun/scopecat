from __future__ import annotations

import pytest

from scopecat.graph.relations.model import as_scalar_expr, input_ref
from scopecat.graph.values import OperationId, ValueId, operation_result_id
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.program.logical import (
    LiteralValueSource,
    LogicalComputeNode,
    PlanExpressionSource,
)
from scopecat.program.logical_graph import verify_logical_graph

FLOAT = Scalar(Float())


def _operation_id(local_id: str) -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _opaque_operation(
    local_id: str,
    *,
    inputs: tuple[tuple[str, ValueId], ...] = (),
) -> tuple[LogicalComputeNode, ValueId]:
    operation_id = _operation_id(local_id)
    result_id = operation_result_id(operation_id)
    return (
        LogicalComputeNode(
            id=operation_id,
            inputs=inputs,
            result_id=result_id,
            result_type=FLOAT,
        ),
        result_id,
    )


def test_operation_and_value_ids_are_nominal_structural_identities() -> None:
    symbol = SymbolId(scope=("a/b",), local_id="result")
    operation_id = OperationId(symbol)
    value_id = ValueId(symbol)
    nested = OperationId(SymbolId(scope=("a", "b"), local_id="result"))

    assert type(operation_id) is not type(value_id)
    assert len({operation_id, value_id}) == 2
    assert operation_id != nested
    assert operation_id.qualified_name == "a%2Fb/result"
    assert nested.qualified_name == "a/b/result"


def test_topological_order_is_declaration_independent() -> None:
    producer, producer_result_id = _opaque_operation("producer")
    independent, _ = _opaque_operation("independent")
    consumer, _ = _opaque_operation(
        "consumer",
        inputs=(("value", producer_result_id),),
    )

    value_defs, compute_nodes, measurement_postprocessors = verify_logical_graph(
        (),
        (consumer, independent, producer),
    )

    assert value_defs == ()
    assert [operation.id.local_id for operation in compute_nodes] == [
        "independent",
        "producer",
        "consumer",
    ]
    assert measurement_postprocessors == ()


def test_operation_cycles_are_reported_in_identity_order() -> None:
    left_id = _operation_id("left")
    right_id = _operation_id("right")
    left = LogicalComputeNode(
        id=left_id,
        inputs=(("right", operation_result_id(right_id)),),
        result_id=operation_result_id(left_id),
        result_type=FLOAT,
    )
    right = LogicalComputeNode(
        id=right_id,
        inputs=(("left", operation_result_id(left_id)),),
        result_id=operation_result_id(right_id),
        result_type=FLOAT,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_logical_graph((), (right, left))

    assert [problem.code for problem in caught.value.problems] == [
        "logical_operation_cycle"
    ]
    assert caught.value.problems[0].message.endswith("left, right")


def test_plan_expression_source_derives_input_dependencies() -> None:
    source = PlanExpressionSource(input_ref("gain"))

    assert source.source_inputs == ("gain",)


def test_plan_expression_source_hashes_unhashable_literals() -> None:
    source = PlanExpressionSource(as_scalar_expr({"nested": [1]}))

    hash(source)


def test_literal_source_captures_mutable_values() -> None:
    literal = {"nested": [1]}
    source = LiteralValueSource(literal)

    literal["nested"].append(2)

    assert source.value == {"nested": [1]}
