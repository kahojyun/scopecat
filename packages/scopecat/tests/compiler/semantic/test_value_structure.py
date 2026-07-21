from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._parameter_contracts import ParameterValueContract
from scopecat.authoring._value_refs import (
    ValueDeclarationKey,
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_scope_value_ref,
    internal_value_ref_operation_id,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
    internal_value_ref_scalar_operation,
    internal_value_ref_source_kind,
)


def test_value_structure_identifies_external_execution_and_point_dependencies() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    run_input = sc.input("run-input", scalar)
    point = sc.point("point-value", scalar)
    compute = sc.compute("execute-value", fn=lambda: 1.0, output_type=scalar)

    assert not internal_value_ref_requires_execution(run_input)
    assert not internal_value_ref_requires_execution(point)
    assert internal_value_ref_requires_execution(compute.output)
    assert not internal_value_ref_point_dependencies(run_input)
    assert [item.id for item in internal_value_ref_point_dependencies(point)] == [
        "point-value"
    ]


def test_bound_expression_inherits_external_execution_dependency() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    value = sc.input("value", scalar)
    expression = value + 1.0
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)

    bound = internal_bind_value_ref_inputs(expression, {"value": compute.output})

    assert internal_value_ref_requires_execution(bound)


def test_nested_binding_tracks_point_and_remaining_scalar_inputs() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    inner_input = sc.input("inner", scalar)
    outer_input = sc.input("outer", scalar)
    point = sc.point("inner", scalar)
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


def test_direct_execute_scalar_operation_remains_symbolic_until_graph_lowering() -> (
    None
):
    scalar = sc.ScalarType(sc.FloatType())
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)
    produced = compute.output
    expression = produced + 1.0

    operation = internal_value_ref_scalar_operation(expression)
    assert internal_value_ref_source_kind(expression) == "scalar_operation"
    assert operation is not None
    assert operation.operator == "+"
    assert operation.left is produced
    assert operation.right == 1.0
    assert internal_value_ref_requires_execution(expression)

    with pytest.raises(TypeError, match="require semantic graph lowering"):
        internal_lower_scalar_value_ref(expression)


def test_scalar_operation_has_nominal_identity_and_structural_scope() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)
    expression = compute.output + 1.0
    sibling = compute.output + 1.0

    key = expression.declaration_key
    assert isinstance(key, ValueDeclarationKey)
    assert key != sibling.declaration_key
    assert expression.declaration_scope == ()

    scoped = internal_scope_value_ref(expression, "outer")
    scoped_operation = internal_value_ref_scalar_operation(scoped)
    assert scoped.declaration_key == key
    assert scoped.declaration_scope == ("outer",)
    assert scoped_operation is not None
    assert isinstance(scoped_operation.left, ValueRef)
    operation_id = internal_value_ref_operation_id(scoped_operation.left)
    assert operation_id is not None
    assert operation_id.scope == ("outer",)


def test_scalar_operation_derives_parameter_and_point_provenance_from_operands() -> (
    None
):
    scalar = sc.ScalarType(sc.FloatType())
    parameter = sc.parameter("frequency", scalar)
    point = sc.point("detuning", scalar)
    expression = parameter + point

    assert internal_value_ref_parameter_contracts(expression) == (
        ParameterValueContract("frequency", scalar),
    )
    assert [
        dependency.id
        for dependency in internal_value_ref_point_dependencies(expression)
    ] == ["detuning"]
    assert not internal_value_ref_requires_execution(expression)
