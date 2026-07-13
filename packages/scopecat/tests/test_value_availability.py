from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._value_availability import (
    ValueAvailability,
    ValueAvailabilityError,
    ValueRate,
    ValueStage,
    require_value_availability,
)
from scopecat.authoring._value_refs import (
    internal_bind_value_ref_inputs,
    internal_value_ref_availability,
)
from scopecat.problems import model_location


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
