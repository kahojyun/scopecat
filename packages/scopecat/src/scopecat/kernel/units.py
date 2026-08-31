"""Small explicit unit registry for the minimal core."""

from __future__ import annotations

from decimal import Decimal

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

_DIMENSIONLESS_PRODUCT_KINDS: frozenset[frozenset[str]] = frozenset(
    {frozenset({"frequency", "time"})}
)

_ALL_LINEAR_UNIT_KINDS: frozenset[str] = frozenset(
    kind
    for kind in set(UNIT_KINDS.values())
    if all(
        unit in UNIT_SCALE_TO_BASE
        for unit, registered_kind in UNIT_KINDS.items()
        if registered_kind == kind
    )
)


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


def unit_product_is_dimensionless(left_kind: str, right_kind: str) -> bool:
    """Return whether multiplying two linear dimensions cancels their units."""

    return frozenset({left_kind, right_kind}) in _DIMENSIONLESS_PRODUCT_KINDS


def unit_kind_has_linear_ratios(kind: str) -> bool:
    """Return whether every registered unit in a dimension is linearly scaled."""

    return kind in _ALL_LINEAR_UNIT_KINDS


def is_linear_unit(unit: str) -> bool:
    """Return whether a unit has a linear scale into its dimension's base unit."""

    return unit in UNIT_SCALE_TO_BASE


def multiply_quantities_to_dimensionless(
    left_value: float,
    left_unit: str,
    right_value: float,
    right_unit: str,
) -> float | None:
    """Multiply inverse linear quantities, returning their unitless value."""

    left_kind = unit_kind(left_unit)
    right_kind = unit_kind(right_unit)
    if (
        left_kind is None
        or right_kind is None
        or not unit_product_is_dimensionless(left_kind, right_kind)
    ):
        return None
    left_base = _linear_base_decimal(left_value, left_unit)
    right_base = _linear_base_decimal(right_value, right_unit)
    if left_base is None or right_base is None:
        return None
    return float(left_base * right_base)


def divide_quantities_to_dimensionless(
    left_value: float,
    left_unit: str,
    right_value: float,
    right_unit: str,
) -> float | None:
    """Divide compatible linear quantities, returning their unitless ratio."""

    if unit_kind(left_unit) != unit_kind(right_unit):
        return None
    left_base = _linear_base_decimal(left_value, left_unit)
    right_base = _linear_base_decimal(right_value, right_unit)
    if left_base is None or right_base is None:
        return None
    if right_base == 0:
        msg = "cannot divide quantity by zero"
        raise ZeroDivisionError(msg)
    return float(left_base / right_base)


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


def convert_linear_value(
    value: float,
    source_unit: str,
    target_unit: str,
) -> float | None:
    """Convert directly between linear units without an intermediate float.

    Registry scales are authored as decimal factors.  Evaluating the ratio in
    decimal arithmetic keeps exact grid values such as 1 us = 1000 ns from
    acquiring binary floating-point residue before timing compilation.
    """

    source_scale = UNIT_SCALE_TO_BASE.get(source_unit)
    target_scale = UNIT_SCALE_TO_BASE.get(target_unit)
    if source_scale is None or target_scale is None:
        return None
    return float(
        Decimal(str(value)) * Decimal(str(source_scale)) / Decimal(str(target_scale))
    )


def _linear_base_decimal(value: float, unit: str) -> Decimal | None:
    scale = UNIT_SCALE_TO_BASE.get(unit)
    if scale is None:
        return None
    return Decimal(str(value)) * Decimal(str(scale))
