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
