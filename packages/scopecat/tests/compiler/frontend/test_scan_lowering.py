from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._parameter_contracts import ParameterValueContract
from scopecat.authoring._point_domain_intents import (
    point_domain_intent_free_point_dependencies,
    point_domain_intent_free_point_input_ids,
    point_domain_intent_parameter_contracts,
    point_domain_intent_value_type,
)
from scopecat.compiler.frontend.scan_lowering import (
    lower_scan_point_domain,
    lower_scan_points,
)
from scopecat.compiler.relations.point_domain import (
    PointAxisLinear,
    PointAxisValues,
    PointDependentProduct,
    PointProduct,
)
from scopecat.records.parameter import Quantity

_FREQUENCY = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _point(axis_id: str):
    return sc.point(axis_id, _FREQUENCY)


def test_explicit_scan_lowers_to_a_structural_axis_with_normalized_values() -> None:
    axis = lower_scan_points(sc.axis(_point("frequency"), [4.9, 5.1], unit="GHz"))

    assert axis.id == "frequency"
    assert axis.value_type == _FREQUENCY
    assert axis.source == PointAxisValues(
        (
            Quantity(value=4.9, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        )
    )
    assert point_domain_intent_value_type(axis).min_rows == 2
    assert point_domain_intent_parameter_contracts(axis) == ()
    assert point_domain_intent_free_point_dependencies(axis) == ()
    assert point_domain_intent_free_point_input_ids(axis) == frozenset()


def test_around_scan_keeps_only_its_typed_center_as_authoring_data() -> None:
    center = sc.input("center", _FREQUENCY)

    axis = lower_scan_points(
        sc.axis(
            _point("frequency"),
            center=center,
            span="2 GHz",
            points=5,
        )
    )

    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.center.value_type == _FREQUENCY
    assert axis.source.span == Quantity(value=2.0, unit="GHz")
    assert axis.source.count == 5
    assert point_domain_intent_free_point_input_ids(axis) == frozenset({"center"})


def test_dependent_scan_closes_only_the_right_linear_center_requirement() -> None:
    scan = sc.cartesian(
        sc.axis(_point("source"), [4.9, 5.1], unit="GHz"),
        sc.axis(
            _point("target"),
            center=_point("source"),
            span="2 GHz",
            points=3,
        ),
    )

    independent = lower_scan_point_domain(scan)
    dependent = lower_scan_point_domain(
        scan,
        dependency_edges=(("source", "target"),),
    )

    assert isinstance(independent, PointProduct)
    assert [
        dependency.id
        for dependency in point_domain_intent_free_point_dependencies(independent)
    ] == ["source"]
    assert isinstance(dependent, PointDependentProduct)
    assert point_domain_intent_free_point_dependencies(dependent) == ()


def test_linear_center_is_the_only_point_domain_parameter_contract_source() -> None:
    explicit = lower_scan_points(sc.axis(_point("explicit"), [4.9, 5.1], unit="GHz"))
    linear = lower_scan_points(
        sc.axis(
            _point("linear"),
            center=sc.parameter("frequency_center", _FREQUENCY),
            span="2 GHz",
            points=3,
        )
    )

    assert point_domain_intent_parameter_contracts(explicit) == ()
    assert point_domain_intent_parameter_contracts(linear) == (
        ParameterValueContract("frequency_center", _FREQUENCY),
    )


def test_zip_requires_at_least_two_scan_sources() -> None:
    with pytest.raises(ValueError, match="at least two scans"):
        sc.zip(sc.axis(_point("frequency"), [4.9, 5.1], unit="GHz"))
