from __future__ import annotations

from typing import cast

import pytest

from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    verify_relation_plan,
)
from scopecat.compiler.semantic.model import (
    LiteralValueSource,
    PlanExpressionSource,
    SemanticGraphIR,
    SemanticOperation,
    ValueDef,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.semantic.verification import verify_semantic_graph
from scopecat.graph.relations.model import LiteralScalarExpr, as_scalar_expr, input_ref
from scopecat.graph.values import OperationId, ValueId, operation_result_id
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar

FLOAT = Scalar(Float())


def _operation_id(local_id: str) -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _value_id(local_id: str) -> ValueId:
    return ValueId(SymbolId(local_id=local_id))


def _opaque_operation(
    local_id: str,
    *,
    inputs: tuple[tuple[str, ValueUse], ...] = (),
) -> tuple[SemanticOperation, ValueId]:
    operation_id = _operation_id(local_id)
    result_id = operation_result_id(operation_id)
    return (
        SemanticOperation(
            id=operation_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
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
        inputs=(("value", ValueUse(producer_result_id)),),
    )

    verified = verify_semantic_graph(
        SemanticGraphIR(operations=(consumer, independent, producer))
    )

    assert [operation.id.local_id for operation in verified.graph.operations] == [
        "independent",
        "producer",
        "consumer",
    ]


def test_operation_cycles_are_reported_in_identity_order() -> None:
    left_id = _operation_id("left")
    right_id = _operation_id("right")
    left = SemanticOperation(
        id=left_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(("right", ValueUse(operation_result_id(right_id))),),
        result_id=operation_result_id(left_id),
        result_type=FLOAT,
    )
    right = SemanticOperation(
        id=right_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(("left", ValueUse(operation_result_id(left_id))),),
        result_id=operation_result_id(right_id),
        result_type=FLOAT,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(operations=(right, left)))

    assert [problem.code for problem in caught.value.problems] == [
        "semantic_operation_cycle"
    ]
    assert caught.value.problems[0].message.endswith("left, right")


def test_verified_value_maps_are_immutable_derived_views() -> None:
    definition = ValueDef(
        id=_value_id("literal"),
        value_type=FLOAT,
        source=LiteralValueSource(1.0),
    )
    verified = verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))

    assert verified.value_defs[definition.id] == definition
    mutable_view = cast("dict[ValueId, ValueDef]", verified.value_defs)
    with pytest.raises(TypeError):
        mutable_view[_value_id("new")] = definition


def test_plan_expression_source_retains_verified_plan_directly() -> None:
    expression = as_scalar_expr(1.0)
    verified = verify_relation_plan(expression, expected_type=FLOAT)
    source = PlanExpressionSource(verified)

    assert isinstance(source.expression, LiteralScalarExpr)
    assert source.expression is expression
    assert source.verified_plan is verified


def test_plan_expression_source_derives_input_dependencies() -> None:
    source = PlanExpressionSource(
        verify_relation_plan(
            input_ref("gain"),
            expected_type=FLOAT,
            bindings=RelationTypeBindings(inputs={"gain": FLOAT}),
        )
    )

    assert source.source_inputs == ("gain",)
    assert source.imports == source.verified_plan.imports


def test_plan_expression_source_equality_uses_verified_semantics() -> None:
    expression = input_ref("gain")
    first = PlanExpressionSource(
        verify_relation_plan(
            expression,
            expected_type=FLOAT,
            bindings=RelationTypeBindings(inputs={"gain": FLOAT}),
        )
    )
    same = PlanExpressionSource(
        verify_relation_plan(
            expression,
            expected_type=FLOAT,
            bindings=RelationTypeBindings(inputs={"gain": FLOAT, "unused": FLOAT}),
        )
    )
    different = PlanExpressionSource(
        verify_relation_plan(
            input_ref("offset"),
            expected_type=FLOAT,
            bindings=RelationTypeBindings(inputs={"offset": FLOAT}),
        )
    )

    assert first == same
    assert hash(first) == hash(same)
    assert first != different


def test_literal_source_captures_mutable_values() -> None:
    literal = {"nested": [1]}
    source = LiteralValueSource(literal)

    literal["nested"].append(2)

    assert source.value == {"nested": [1]}
