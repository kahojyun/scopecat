"""Tests for the explicit unit registry and concrete quantity operations."""

from __future__ import annotations

import math
from typing import assert_type

import pytest

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import compatible_units


def test_distinct_units_require_a_shared_linear_conversion() -> None:
    assert compatible_units("MHz", "GHz")
    assert compatible_units("mV", "V")
    assert not compatible_units("dBm", "W")
    assert not compatible_units("GHz", "ns")
    assert not compatible_units("unknown-left", "unknown-right")
    assert not compatible_units("unknown", "unknown")


def test_same_non_linear_unit_is_compatible_without_conversion() -> None:
    power = Quantity(-20.0, "dBm")

    assert compatible_units("dBm", "dBm")
    assert power.to("dBm") == power
    assert power + Quantity(3.0, "dBm") == Quantity(-17.0, "dBm")

    with pytest.raises(ValueError, match="cannot convert 'dBm' to 'W'"):
        power.to("W")


def test_linear_conversion_preserves_full_float_precision() -> None:
    assert Quantity(180.0, "deg").to("rad") == Quantity(math.pi, "rad")


def test_linear_conversion_preserves_exact_decimal_grid_values() -> None:
    assert Quantity(1.0, "us").to("ns") == Quantity(1000.0, "ns")
    assert Quantity(20_000.0, "ns").to("us") == Quantity(20.0, "us")
    assert Quantity(0.016, "us").to("ns") == Quantity(16.0, "ns")


def test_quantity_arithmetic_does_not_quantize_sub_picounit_values() -> None:
    tiny = Quantity(4e-13, "ns")

    assert (Quantity(0.0, "ns") + tiny).value == tiny.value
    assert (tiny - Quantity(1e-13, "ns")).value == tiny.value - 1e-13
    assert (tiny * 0.5).value == tiny.value * 0.5
    assert (tiny / 2).value == tiny.value / 2


def test_quantity_arithmetic_can_reduce_units_to_plain_numbers() -> None:
    frequency = Quantity(5.0, "GHz")
    delay = Quantity(20.0, "ns")

    assert_type(frequency * delay, float)
    assert_type(2.0 * frequency, Quantity)
    assert frequency * delay == 100.0
    assert delay * frequency == 100.0
    assert Quantity(5_000.0, "MHz") / frequency == 1.0
    assert Quantity(180.0, "deg") / Quantity(math.pi, "rad") == 1.0
    assert Quantity(1.0, "W") / Quantity(2.0, "W") == 0.5


def test_quantity_arithmetic_rejects_unrepresented_derived_units() -> None:
    with pytest.raises(TypeError, match="unsupported operand type"):
        _ = Quantity(1.0, "V") * Quantity(2.0, "s")

    with pytest.raises(TypeError, match="unsupported operand type"):
        _ = Quantity(-20.0, "dBm") / Quantity(-10.0, "dBm")

    with pytest.raises(ZeroDivisionError, match="quantity by zero"):
        _ = Quantity(1.0, "V") / Quantity(0.0, "mV")
