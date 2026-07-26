from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

import scopecat as sc
from scopecat.authoring._parameter_contracts import ParameterValueContract
from scopecat.authoring._point_domain_intents import (
    point_domain_intent_parameter_contracts,
    point_domain_intent_value_type,
)
from scopecat.authoring._scan_intents import ScanLeafIntent, iter_scan_leaves
from scopecat.compiler.frontend.scan_lowering import (
    lower_scan_points,
    lower_scans_point_domain,
)
from scopecat.compiler.relations.model import ParameterLookupUse
from scopecat.compiler.relations.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointProduct,
)
from scopecat.records.parameter import Quantity

_FREQUENCY = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _point(axis_id: str):
    return sc.coordinate(axis_id, _FREQUENCY)


def _parameter_lookup(
    column: str = "frequency",
    value_type: sc.ScalarType = _FREQUENCY,
) -> sc.ValueRef:
    return sc.parameter_lookup(
        "device_parameters",
        key={"device": "q0"},
        column=column,
        value_type=value_type,
    )


def _leaf(scan: sc.Scan) -> ScanLeafIntent:
    return cast("ScanLeafIntent", scan)


def test_explicit_scan_lowers_to_a_structural_axis_with_normalized_values() -> None:
    axis = lower_scan_points(
        _leaf(sc.axis(_point("frequency"), [4.9, 5.1], unit="GHz"))
    )

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


def test_around_scan_keeps_only_its_typed_center_as_authoring_data() -> None:
    center = sc.input("center", _FREQUENCY)

    axis = lower_scan_points(
        _leaf(
            sc.axis(
                _point("frequency"),
                center=center,
                span="2 GHz",
                points=5,
            )
        )
    )

    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.center.value_type == _FREQUENCY
    assert axis.source.span == Quantity(value=2.0, unit="GHz")
    assert axis.source.count == 5


def test_parameter_around_scan_uses_the_selected_cell_as_its_center() -> None:
    axis = lower_scan_points(
        _leaf(
            sc.param_axis(
                _point("frequency"),
                _parameter_lookup(),
                span="200 MHz",
                points=5,
            )
        )
    )

    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.center.value_type == _FREQUENCY
    assert axis.source.span == Quantity(value=200.0, unit="MHz")
    assert axis.source.count == 5
    [lookup] = tuple(
        contract
        for contract in point_domain_intent_parameter_contracts(axis)
        if isinstance(contract, ParameterLookupUse)
    )
    assert lookup.table_id == "device_parameters"
    assert lookup.column_id == "frequency"
    assert lookup.result_type == _FREQUENCY


def test_parameter_scan_forms_are_mutually_exclusive_and_complete() -> None:
    target = _point("frequency")
    lookup = _parameter_lookup()
    unchecked_param_axis = cast("Callable[..., sc.Scan]", sc.param_axis)

    with pytest.raises(ValueError, match="either values or span/points"):
        unchecked_param_axis(
            target,
            lookup,
            [4.9, 5.1],
            unit="GHz",
            span="200 MHz",
            points=3,
        )
    with pytest.raises(ValueError, match="requires span and points"):
        unchecked_param_axis(target, lookup, span="200 MHz")
    with pytest.raises(ValueError, match="requires values or span and points"):
        unchecked_param_axis(target, lookup)


def test_parameter_around_scan_requires_a_quantity_point() -> None:
    with pytest.raises(TypeError, match="typed quantity point"):
        sc.param_axis(
            sc.coordinate("gain", sc.ScalarType(sc.FloatType())),
            _parameter_lookup("gain", sc.ScalarType(sc.FloatType())),
            span="0.2 ratio",
            points=3,
        )


def test_flat_scans_lower_to_a_cartesian_product() -> None:
    scan = sc.cartesian(
        sc.axis(_point("source"), [4.9, 5.1], unit="GHz"),
        sc.axis(_point("target"), [5.0, 5.2], unit="GHz"),
    )

    domain = lower_scans_point_domain(iter_scan_leaves(scan))

    assert isinstance(domain, PointProduct)
    assert tuple(
        factor.id for factor in domain.factors if isinstance(factor, PointAxis)
    ) == ("source", "target")


def test_linear_center_is_the_only_point_domain_parameter_contract_source() -> None:
    explicit = lower_scan_points(
        _leaf(sc.axis(_point("explicit"), [4.9, 5.1], unit="GHz"))
    )
    linear = lower_scan_points(
        _leaf(
            sc.axis(
                _point("linear"),
                center=sc.parameter("frequency_center", _FREQUENCY),
                span="2 GHz",
                points=3,
            )
        )
    )

    assert point_domain_intent_parameter_contracts(explicit) == ()
    assert point_domain_intent_parameter_contracts(linear) == (
        ParameterValueContract("frequency_center", _FREQUENCY),
    )
