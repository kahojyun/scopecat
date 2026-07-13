from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._value_refs import (
    ValueDeclarationKey,
    ValueRef,
    internal_bind_value_ref_inputs,
    internal_lower_scalar_value_ref,
    internal_scope_value_ref,
    internal_value_ref_availability,
    internal_value_ref_declaration_key,
    internal_value_ref_declaration_scope,
    internal_value_ref_operation_id,
    internal_value_ref_parameter_contracts,
    internal_value_ref_point_dependencies,
    internal_value_ref_scalar_operation,
    internal_value_ref_source_kind,
)
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueAvailabilityError,
    ValueRate,
    ValueStage,
    require_value_availability,
)
from scopecat.kernel.problems import model_location


def test_value_availability_separates_stage_from_rate() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    run_input = sc.input("run-input", scalar)
    point = sc.point("point-value", scalar)
    compute = sc.compute("execute-value", fn=lambda: 1.0, output_type=scalar)

    assert internal_value_ref_availability(run_input) == ValueAvailability(
        ValueStage.PLAN,
        ValueRate.RUN,
    )
    assert internal_value_ref_availability(point) == ValueAvailability(
        ValueStage.PLAN,
        ValueRate.POINT,
    )
    assert internal_value_ref_availability(compute.output) == ValueAvailability(
        ValueStage.EXECUTE,
        ValueRate.POINT,
    )


def test_bound_expression_inherits_execute_stage_from_its_input() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    value = sc.input("value", scalar)
    expression = value + 1.0
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)

    bound = internal_bind_value_ref_inputs(
        expression,
        {"value": compute.output},
    )

    assert internal_value_ref_availability(bound) == ValueAvailability(
        ValueStage.EXECUTE,
        ValueRate.POINT,
    )


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
    assert internal_value_ref_availability(expression) == ValueAvailability(
        ValueStage.EXECUTE,
        ValueRate.POINT,
    )

    with pytest.raises(TypeError, match="require semantic graph lowering"):
        internal_lower_scalar_value_ref(expression)


def test_scalar_operation_has_nominal_identity_and_structural_scope() -> None:
    scalar = sc.ScalarType(sc.FloatType())
    compute = sc.compute("produce", fn=lambda: 1.0, output_type=scalar)
    expression = compute.output + 1.0
    sibling = compute.output + 1.0

    key = internal_value_ref_declaration_key(expression)
    assert isinstance(key, ValueDeclarationKey)
    assert key != internal_value_ref_declaration_key(sibling)
    assert internal_value_ref_declaration_scope(expression) == ()

    scoped = internal_scope_value_ref(expression, "outer")
    scoped_operation = internal_value_ref_scalar_operation(scoped)
    assert internal_value_ref_declaration_key(scoped) == key
    assert internal_value_ref_declaration_scope(scoped) == ("outer",)
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

    assert [
        contract.parameter_id
        for contract in internal_value_ref_parameter_contracts(expression)
    ] == ["frequency"]
    assert [
        dependency.id
        for dependency in internal_value_ref_point_dependencies(expression)
    ] == ["detuning"]
    assert internal_value_ref_availability(expression) == ValueAvailability(
        ValueStage.PLAN,
        ValueRate.POINT,
    )


def test_availability_checker_reports_stage_and_rate_independently() -> None:
    with pytest.raises(ValueAvailabilityError) as stage_error:
        require_value_availability(
            ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT),
            stages=(ValueStage.PLAN,),
            context="resource selector",
            location=model_location("resources", "drive", "selector"),
        )
    assert stage_error.value.code == "value_stage_unavailable"
    assert stage_error.value.location == model_location(
        "resources", "drive", "selector"
    )

    with pytest.raises(ValueAvailabilityError) as rate_error:
        require_value_availability(
            ValueAvailability(ValueStage.PLAN, ValueRate.POINT),
            stages=(ValueStage.PLAN,),
            rates=(ValueRate.RUN,),
            context="record axis",
            location=model_location("records", "signal", "axes", "sample", "size"),
        )
    assert rate_error.value.code == "value_rate_unavailable"
    assert rate_error.value.location == model_location(
        "records", "signal", "axes", "sample", "size"
    )
