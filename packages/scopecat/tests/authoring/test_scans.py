from __future__ import annotations

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

    with pytest.raises(TypeError, match="scan point quantity type"):
        sc.axis(frequency, center=duration, span="20 MHz", points=3)
    with pytest.raises(TypeError, match="incompatible with point dimension"):
        sc.axis(
            frequency,
            center=sc.Quantity(value=5.0, unit="GHz"),
            span="20 ns",
            points=3,
        )


def test_scan_capture_requires_finite_durable_values() -> None:
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz", finite=False)),
    )

    with pytest.raises(ValueError, match="finite"):
        sc.axis(frequency, [sc.Quantity(value=float("inf"), unit="GHz")])
