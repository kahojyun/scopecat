from __future__ import annotations

from typing import cast

import pytest

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.program.expressions import (
    ParameterLookupScalarExpr,
    ParameterLookupUse,
    ScalarExpr,
    lit,
)
from scopecat.program.logical import LogicalComputeNode
from scopecat.program.logical_graph import verify_logical_graph
from scopecat.program.value_graph import OperationId, operation_result_id

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
            input_types=tuple((name, FLOAT) for name, _value_id in inputs),
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

    value_defs, compute_nodes, measurement_computes = verify_logical_graph(
        (),
        (consumer, independent, producer),
    )

    assert value_defs == ()
    assert [operation.id.local_id for operation in compute_nodes] == [
        "independent",
        "producer",
        "consumer",
    ]
    assert measurement_computes == ()


def test_operation_cycles_are_reported_in_identity_order() -> None:
    left_id = _operation_id("left")
    right_id = _operation_id("right")
    left = LogicalComputeNode(
        id=left_id,
        inputs=(("right", operation_result_id(right_id)),),
        input_types=(("right", FLOAT),),
        result_id=operation_result_id(left_id),
        result_type=FLOAT,
    )
    right = LogicalComputeNode(
        id=right_id,
        inputs=(("left", operation_result_id(left_id)),),
        input_types=(("left", FLOAT),),
        result_id=operation_result_id(right_id),
        result_type=FLOAT,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_logical_graph((), (right, left))

    assert [problem.code for problem in caught.value.problems] == [
        "logical_operation_cycle"
    ]
    assert caught.value.problems[0].message.endswith("left, right")


def test_literal_expression_captures_mutable_values() -> None:
    literal: dict[str, object] = {"nested": [1]}
    expression = lit(literal)

    nested = cast("list[int]", literal["nested"])
    nested.append(2)
    selected = expression.value
    assert isinstance(selected, dict)
    selected["nested"] = [3]

    assert expression.value == {"nested": [1]}


def test_literal_expression_copies_value_models_and_retains_payload_identity() -> None:
    entity = EntityRef(id="q0", kind="qubit")
    quantity = Quantity(value=5.0, unit="GHz")
    payload = PayloadValue(schema_id="test.program", payload=object())

    captured_entity = lit(entity).value
    captured_quantity = lit(quantity).value
    captured_payload = lit(payload).value

    assert captured_entity == entity
    assert captured_entity is not entity
    assert captured_quantity == quantity
    assert captured_quantity is not quantity
    assert captured_payload is payload


def test_parameter_lookup_expression_captures_an_immutable_key() -> None:
    use = ParameterLookupUse(
        table_id="frequencies",
        key_input_types=(("frequency", FLOAT),),
        literal_key_columns=frozenset({"frequency"}),
        column_id="duration",
        result_type=FLOAT,
    )
    original = lit(5.0)
    key = {"frequency": original}
    expression = ParameterLookupScalarExpr(use=use, key=key)

    key["frequency"] = lit(6.0)

    assert expression.key["frequency"] is original
    hash(expression)
    hash(expression + 1.0)
    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        cast("dict[str, ScalarExpr]", expression.key)["frequency"] = lit(7.0)
