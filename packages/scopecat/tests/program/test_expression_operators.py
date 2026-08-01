"""Shared authored and runtime expression operator semantics."""

from __future__ import annotations

from typing import cast

import pytest

import scopecat as sc
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.verification import ExpressionTypeBindings
from scopecat.program.expression_operators import runtime_values_equal
from scopecat.program.value_refs import internal_lower_scalar_value_ref
from scopecat.program.values import input as program_input
from tests.testkit.expressions import evaluate_scalar


def _input_bindings(**inputs: sc.ValueType) -> ExpressionTypeBindings:
    return ExpressionTypeBindings(inputs=cast("dict[str, sc.ScalarType]", inputs))


def test_typed_arithmetic_and_runtime_use_the_same_operator_contract() -> None:
    text = program_input("text", sc.ScalarType(sc.StringType()))
    count = program_input("count", sc.ScalarType(sc.IntType()))

    with pytest.raises(TypeError, match=r"operator '\+' is not defined"):
        _ = text + "suffix"

    numeric = count + 0.5
    assert numeric.value_type == sc.ScalarType(sc.FloatType())
    assert (
        evaluate_scalar(
            internal_lower_scalar_value_ref(numeric),
            EvalContext(inputs={"count": 2}),
            bindings=_input_bindings(count=count.value_type),
        )
        == 2.5
    )


def test_arithmetic_supports_literal_operands_on_either_side() -> None:
    count = program_input("count", sc.ScalarType(sc.IntType(minimum=1)))
    expressions = (
        count + 2,
        2 + count,
        count - 2,
        5 - count,
        count * 2,
        2 * count,
        count / 2,
        6 / count,
    )

    assert [
        evaluate_scalar(
            internal_lower_scalar_value_ref(expression),
            EvalContext(inputs={"count": 2}),
            bindings=_input_bindings(count=count.value_type),
        )
        for expression in expressions
    ] == [4, 4, 0, 3, 4, 4, 1.0, 3.0]


def test_integer_arithmetic_preserves_affine_bounds() -> None:
    count = sc.coordinate(
        "count",
        sc.ScalarType(sc.IntType(minimum=0, maximum=4)),
    )
    unbounded_count = sc.coordinate(
        "unbounded_count",
        sc.ScalarType(sc.IntType(minimum=0)),
    )

    assert (2 * count + 1).value_type == sc.ScalarType(sc.IntType(minimum=1, maximum=9))
    assert (3 - count).value_type == sc.ScalarType(sc.IntType(minimum=-1, maximum=3))
    assert (2 * unbounded_count + 1).value_type == sc.ScalarType(sc.IntType(minimum=1))


def test_typed_arithmetic_rejects_non_finite_runtime_results() -> None:
    value = program_input("value", sc.ScalarType(sc.FloatType()))
    overflow = internal_lower_scalar_value_ref(value * 1e308)

    with pytest.raises(ValueError, match="non-finite result"):
        evaluate_scalar(
            overflow,
            EvalContext(inputs={"value": 1e308}),
            bindings=_input_bindings(value=value.value_type),
        )


def test_runtime_key_equality_normalizes_quantity_units_symmetrically() -> None:
    tiny_ghz = sc.Quantity(1e-13, "GHz")
    tiny_hz = sc.Quantity(1e-4, "Hz")

    assert runtime_values_equal(tiny_ghz, tiny_hz)
    assert runtime_values_equal(tiny_hz, tiny_ghz)


def test_runtime_key_equality_uses_stable_entity_identity() -> None:
    left = sc.EntityRef(
        id="q0",
        kind="qubit",
        metadata={"source": "left"},
    )
    right = sc.EntityRef(
        id="q0",
        kind="qubit",
        metadata={"source": "right"},
    )
    assert runtime_values_equal(left, right)
    assert not runtime_values_equal(
        left,
        sc.EntityRef(id="q0", kind="resonator"),
    )
    with pytest.raises(TypeError, match="matching"):
        runtime_values_equal(True, 1)
