from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._parameter_contracts import ParameterValueContract
from scopecat.authoring._value_refs import (
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)
from scopecat.graph.relations.model import BinaryScalarExpr


def test_value_structure_identifies_external_execution_and_point_dependencies() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    run_input = sc.input("run-input", scalar)
    point = sc.coordinate("point-value", scalar)
    compute = sc.compute("execute-value", fn=lambda: 1.0, output_type=scalar)

    assert not internal_value_ref_requires_execution(run_input)
    assert not internal_value_ref_requires_execution(point)
    assert internal_value_ref_requires_execution(compute.output)
    assert not internal_value_ref_point_dependencies(run_input)
    assert [item.id for item in internal_value_ref_point_dependencies(point)] == [
        "point-value"
    ]


def test_compute_output_cannot_be_bound_inside_relation_arithmetic() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    value = sc.input("value", scalar)
    expression = value + 1.0
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)

    with pytest.raises(TypeError, match=r"express this calculation with sc\.compute"):
        internal_bind_value_ref_inputs(expression, {"value": compute.output})


def test_nested_binding_tracks_point_and_remaining_scalar_inputs() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    inner_input = sc.input("inner", scalar)
    outer_input = sc.input("outer", scalar)
    point = sc.coordinate("inner", scalar)
    nested_input = sc.input("nested", scalar)

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
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)
    with pytest.raises(TypeError, match=r"express this calculation with sc\.compute"):
        _ = compute.output + 1.0


def test_relation_arithmetic_lowers_to_a_binary_expression() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    expression = sc.input("value", scalar) + 1.0

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
