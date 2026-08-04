"""Small explicit unit registry for the minimal core."""

from __future__ import annotations

UNIT_KINDS: dict[str, str] = {
    "s": "time",
    "ms": "time",
    "us": "time",
    "ns": "time",
    "Hz": "frequency",
    "kHz": "frequency",
    "MHz": "frequency",
    "GHz": "frequency",
    "V": "voltage",
    "mV": "voltage",
    "A": "current",
    "mA": "current",
    "uA": "current",
    "K": "temperature",
    "mK": "temperature",
    "Ohm": "resistance",
    "kOhm": "resistance",
    "dBm": "power",
    "W": "power",
    "dB": "level",
    "rad": "phase",
    "deg": "phase",
    "arb": "amplitude",
    "count": "count",
    "ratio": "ratio",
}

UNIT_SCALE_TO_BASE: dict[str, float] = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
    "Hz": 1.0,
    "kHz": 1e3,
    "MHz": 1e6,
    "GHz": 1e9,
    "V": 1.0,
    "mV": 1e-3,
    "A": 1.0,
    "mA": 1e-3,
    "uA": 1e-6,
    "K": 1.0,
    "mK": 1e-3,
    "Ohm": 1.0,
    "kOhm": 1e3,
    "W": 1.0,
    "rad": 1.0,
    "deg": 3.141592653589793 / 180.0,
    "arb": 1.0,
    "count": 1.0,
    "ratio": 1.0,
}


def is_supported_unit(unit: str) -> bool:
    return unit in UNIT_KINDS


def unit_kind(unit: str) -> str | None:
    return UNIT_KINDS.get(unit)


def compatible_units(left: str, right: str) -> bool:
    """Return whether values can be compared without changing semantics.

    Equal registered units never require conversion. Distinct units are
    compatible only when both have a linear conversion into the same
    dimension's base unit.
    """

    left_kind = unit_kind(left)
    if left_kind is None:
        return False
    if left == right:
        return True
    return (
        left_kind == unit_kind(right)
        and left in UNIT_SCALE_TO_BASE
        and right in UNIT_SCALE_TO_BASE
    )


def to_base_value(value: float, unit: str) -> float | None:
    """Convert a value to its category's base unit when conversion is linear."""

    scale = UNIT_SCALE_TO_BASE.get(unit)
    if scale is None:
        return None
    return value * scale


def from_base_value(value: float, unit: str) -> float | None:
    """Convert a base-unit value to the requested unit when conversion is linear."""

    scale = UNIT_SCALE_TO_BASE.get(unit)
    if scale is None:
        return None
    return value / scale
