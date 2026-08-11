from __future__ import annotations

import pytest
from testkit.expressions import evaluate_scalar

import scopecat as sc
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.verification import ExpressionTypeBindings
from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    LiteralScalarExpr,
    as_scalar_expr,
    input_ref,
)
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.value_refs import (
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
    internal_value_ref_from_expression,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)
from scopecat.program.value_transforms import internal_bind_value_ref_inputs
from scopecat.program.values import compute as program_compute
from scopecat.program.values import input as program_input


def test_value_structure_identifies_external_execution_and_point_dependencies() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    run_input = program_input("run-input", scalar)
    point = sc.coordinate("point-value", scalar)
    compute = program_compute("execute-value", fn=lambda: 1.0, output_type=scalar)
    compute_output = compute.output

    assert not internal_value_ref_requires_execution(run_input)
    assert not internal_value_ref_requires_execution(point)
    assert internal_value_ref_requires_execution(compute_output)
    assert isinstance(compute_output.source, ComputeResultScalarExpr)
    assert internal_lower_value_ref(compute_output) is compute_output.source
    assert not internal_value_ref_point_dependencies(run_input)
    assert [item.id for item in internal_value_ref_point_dependencies(point)] == [
        "point-value"
    ]


def test_nested_binding_tracks_point_and_remaining_scalar_inputs() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    inner_input = program_input("inner", scalar)
    outer_input = program_input("outer", scalar)
    point = sc.coordinate("inner", scalar)
    nested_input = program_input("nested", scalar)

    inner = internal_bind_value_ref_inputs(
        inner_input + outer_input,
        {"inner": point},
    )
    nested = internal_bind_value_ref_inputs(
        nested_input * 2.0,
        {"nested": inner},
    )

    assert [
        dependency.id for dependency in internal_value_ref_point_dependencies(nested)
    ] == ["inner"]
    assert internal_value_ref_scalar_input_ids(nested) == frozenset({"outer"})


def test_scalar_input_binding_preserves_parent_same_named_input() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = program_input("value", value_type)
    parent_value = program_input("value", value_type)

    bound = internal_bind_value_ref_inputs(
        child_value + 1.0,
        {"value": parent_value + 1.0},
    )

    assert evaluate_scalar(
        internal_lower_scalar_value_ref(bound),
        EvalContext(inputs={"value": 2.0}),
        bindings=ExpressionTypeBindings(inputs={"value": value_type}),
    ) == pytest.approx(4.0)


def test_expression_input_binding_does_not_capture_sibling_inputs() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = internal_value_ref_from_expression(
        input_ref("a", value_type),
        value_type,
    )
    parent_b = program_input("b", value_type)
    child_b = internal_value_ref_from_expression(
        as_scalar_expr(10.0, value_type=value_type),
        value_type,
    )

    bound = internal_bind_value_ref_inputs(
        child_value,
        {"a": parent_b + 1.0, "b": child_b},
    )

    assert evaluate_scalar(
        internal_lower_scalar_value_ref(bound),
        EvalContext(inputs={"b": 2.0}),
        bindings=ExpressionTypeBindings(inputs={"b": value_type}),
    ) == pytest.approx(3.0)


def test_compute_output_arithmetic_requires_explicit_compute() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    compute = program_compute("produce", fn=lambda: 1.0, output_type=scalar)
    with pytest.raises(TypeError, match=r"ModuleContext\.compute"):
        _ = compute.output + 1.0


def test_symbolic_values_reject_python_truth_testing() -> None:
    value = program_input("enabled", sc.ScalarType(sc.BoolType()))

    with pytest.raises(TypeError, match="has no Python truth value"):
        bool(value)


def test_scalar_arithmetic_builds_a_binary_expression() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    expression = program_input("value", scalar) + 1.0

    lowered = internal_lower_scalar_value_ref(expression)
    assert isinstance(lowered, BinaryScalarExpr)
    assert lowered.op == "+"
    assert isinstance(lowered.left, InputScalarExpr)
    assert lowered.left.name == "value"
    assert lowered.left.value_type == scalar
    assert isinstance(lowered.right, LiteralScalarExpr)
    assert lowered.right.value == 1.0
    assert lowered.value_type == expression.value_type


def test_arithmetic_derives_parameter_and_point_dependencies() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    parameter = sc.parameter("frequency", scalar)
    point = sc.coordinate("detuning", scalar)
    expression = parameter + point

    assert internal_value_ref_parameter_contracts(expression) == (
        ParameterValueContract("frequency", scalar),
    )
    assert [
        dependency.id
        for dependency in internal_value_ref_point_dependencies(expression)
    ] == ["detuning"]
    assert not internal_value_ref_requires_execution(expression)
