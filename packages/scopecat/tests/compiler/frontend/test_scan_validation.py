from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.scan_lowering import lower_scans_point_domain
from scopecat.compiler.frontend.scan_validation import (
    ScanValidationError,
    verify_scans,
)
from scopecat.kernel.quantity import Quantity
from scopecat.program.values import input as program_input

_FREQUENCY = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _point(axis_id: str, value_type: sc.ScalarType = _FREQUENCY):
    return sc.coordinate(axis_id, value_type)


def _values(axis_id: str):
    return sc.axis(_point(axis_id), [1.0, 2.0], unit="GHz")


def test_axes_are_verified_in_declaration_order() -> None:
    verified = verify_scans((_values("first"), _values("second"), _values("third")))
    resolved = lower_scans_point_domain(
        verified,
        inputs={},
    )

    assert tuple(axis.id for axis in verified) == ("first", "second", "third")
    assert tuple(axis.id for axis in resolved) == ("first", "second", "third")


def test_bound_input_can_center_a_scan() -> None:
    scan = sc.axis(
        _point("frequency"),
        center=program_input("center", _FREQUENCY),
        span="2 GHz",
        points=3,
    )

    verified = verify_scans(
        (scan,),
        inputs={"center": Quantity(value=5.0, unit="GHz")},
    )

    assert tuple(axis.id for axis in verified) == ("frequency",)


def test_unbound_input_cannot_center_a_scan() -> None:
    scan = sc.axis(
        _point("frequency"),
        center=program_input("center", _FREQUENCY),
        span="2 GHz",
        points=3,
    )

    with pytest.raises(ScanValidationError) as caught:
        verify_scans((scan,))

    assert [issue.code for issue in caught.value.issues] == [
        "scan_source_input_unbound"
    ]


def test_scan_source_cannot_depend_on_another_point() -> None:
    scan = sc.axis(
        _point("target"),
        center=_point("source"),
        span="2 GHz",
        points=3,
    )

    with pytest.raises(ScanValidationError) as caught:
        verify_scans((scan, _values("source")))

    assert [issue.code for issue in caught.value.issues] == [
        "scan_point_dependency_unsupported"
    ]


def test_parameter_axis_key_can_use_a_bound_input() -> None:
    device = program_input("device", sc.ScalarType(sc.StringType()))
    lookup = sc.parameter_lookup(
        "device_parameters",
        key={"device": device},
        column="frequency",
        value_type=_FREQUENCY,
    )
    scan = sc.param_axis(
        _point("frequency"),
        lookup,
        span="200 MHz",
        points=5,
    )

    verified = verify_scans((scan,), inputs={"device": "q0"})

    assert tuple(axis.id for axis in verified) == ("frequency",)
