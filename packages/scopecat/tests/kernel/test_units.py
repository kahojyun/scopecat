"""Tests for the explicit unit registry and concrete quantity operations."""

from __future__ import annotations

import math

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
