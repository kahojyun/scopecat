from __future__ import annotations

import numpy as np
import pytest

import scopecat as sc


def test_around_scan_requires_compatible_quantity_dimensions() -> None:
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    duration = sc.coordinate(
        "duration",
        sc.ScalarType(sc.QuantityType(unit="ns")),
    )

    with pytest.raises(TypeError, match="axis point quantity type"):
        sc.axis(frequency, center=duration, span="20 MHz", points=3)
    with pytest.raises(TypeError, match="incompatible"):
        sc.axis(
            frequency,
            center=sc.Quantity(value=5.0, unit="GHz"),
            span="20 ns",
            points=3,
        )


def test_dbm_is_a_valid_generated_scan_coordinate_unit() -> None:
    power = sc.coordinate(
        "power",
        sc.ScalarType(sc.QuantityType(unit="dBm")),
    )

    sc.axis(power, start=-30.0, stop=0.0, unit="dBm", points=7)
    sc.axis(power, center=-20.0, span=6.0, unit="dBm", points=5)


def test_numpy_linspace_values_remain_a_valid_dbm_axis() -> None:
    power = sc.coordinate(
        "power",
        sc.ScalarType(sc.QuantityType(unit="dBm")),
    )

    sc.axis(power, np.linspace(-30.0, 0.0, 7), unit="dBm")


def test_generated_scan_rejects_non_convertible_coordinate_units() -> None:
    power = sc.coordinate(
        "power",
        sc.ScalarType(sc.QuantityType(unit="dBm")),
    )

    with pytest.raises(TypeError, match=r"axis.stop.*compatible with 'dBm'"):
        sc.axis(
            power,
            start=sc.Quantity(-30.0, "dBm"),
            stop=sc.Quantity(1.0, "W"),
            points=3,
        )
    with pytest.raises(TypeError, match=r"axis.span.*compatible with 'dBm'"):
        sc.axis(
            power,
            center=sc.Quantity(-20.0, "dBm"),
            span=sc.Quantity(1.0, "W"),
            points=3,
        )


def test_dynamic_center_must_declare_an_explicit_coordinate_unit() -> None:
    generic_frequency = sc.ScalarType(sc.QuantityType(dimension="frequency"))
    frequency = sc.coordinate("frequency", generic_frequency)

    with pytest.raises(TypeError, match="center must declare a unit"):
        sc.axis(
            frequency,
            center=sc.parameter("center", generic_frequency),
            span=200.0,
            unit="MHz",
            points=3,
        )


def test_generated_scan_rejects_non_durable_float_endpoints() -> None:
    value = sc.coordinate(
        "value",
        sc.ScalarType(sc.FloatType(finite=False)),
    )

    with pytest.raises(ValueError, match="finite"):
        sc.axis(value, start=0.0, stop=float("inf"), points=3)


def test_generated_scan_does_not_ignore_an_empty_unit() -> None:
    power = sc.coordinate(
        "power",
        sc.ScalarType(sc.QuantityType(unit="dBm")),
    )

    with pytest.raises(ValueError, match="unsupported unit"):
        sc.axis(power, start=-30.0, stop=0.0, unit="", points=3)


def test_scan_forms_are_mutually_exclusive_and_complete() -> None:
    power = sc.coordinate(
        "power",
        sc.ScalarType(sc.QuantityType(unit="dBm")),
    )

    with pytest.raises(ValueError, match="exactly one"):
        sc.axis(
            power,
            (-30.0, -20.0),
            unit="dBm",
            start=-30.0,
            stop=0.0,
            points=7,
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        sc.axis(
            power,
            start=-30.0,
            stop=0.0,
            center=-20.0,
            span=6.0,
            unit="dBm",
            points=7,
        )
    with pytest.raises(ValueError, match="requires start, stop, and points"):
        sc.axis(power, start=-30.0, unit="dBm", points=7)
    with pytest.raises(ValueError, match="at least 2"):
        sc.axis(power, start=-30.0, stop=0.0, unit="dBm", points=1)


def test_quantity_strings_accept_scientific_notation() -> None:
    delay = sc.coordinate(
        "delay",
        sc.ScalarType(sc.QuantityType(unit="s")),
    )

    sc.axis(delay, start="-1e-12 s", stop="1e-12 s", points=3)


def test_scan_capture_requires_finite_durable_values() -> None:
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz", finite=False)),
    )

    with pytest.raises(ValueError, match="finite"):
        sc.axis(frequency, [sc.Quantity(value=float("inf"), unit="GHz")])
