from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.program.expressions import BinaryScalarExpr
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.value_refs import (
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)
from scopecat.program.values import compute as program_compute
from scopecat.program.values import input as program_input


def test_value_structure_identifies_external_execution_and_point_dependencies() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    run_input = program_input("run-input", scalar)
    point = sc.coordinate("point-value", scalar)
    compute = program_compute("execute-value", fn=lambda: 1.0, output_type=scalar)

    assert not internal_value_ref_requires_execution(run_input)
    assert not internal_value_ref_requires_execution(point)
    assert internal_value_ref_requires_execution(compute.output)
    assert not internal_value_ref_point_dependencies(run_input)
    assert [item.id for item in internal_value_ref_point_dependencies(point)] == [
        "point-value"
    ]


def test_compute_output_cannot_be_bound_inside_relation_arithmetic() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    value = program_input("value", scalar)
    expression = value + 1.0
    compute = program_compute("produce", fn=lambda: 1.0, output_type=scalar)

    with pytest.raises(TypeError, match=r"ModuleContext\.compute"):
        internal_bind_value_ref_inputs(expression, {"value": compute.output})


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


def test_compute_output_arithmetic_requires_explicit_compute() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    compute = program_compute("produce", fn=lambda: 1.0, output_type=scalar)
    with pytest.raises(TypeError, match=r"ModuleContext\.compute"):
        _ = compute.output + 1.0


def test_relation_arithmetic_lowers_to_a_binary_expression() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    expression = program_input("value", scalar) + 1.0

    lowered = internal_lower_scalar_value_ref(expression)
    assert isinstance(lowered, BinaryScalarExpr)
    assert lowered.op == "+"


def test_arithmetic_stores_parameter_and_point_dependencies() -> None:
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
