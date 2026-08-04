from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.units import UNIT_KINDS, UNIT_SCALE_TO_BASE
from scopecat.kernel.value_identity import scalar_values_equal

_BASE_UNIT_BY_KIND = {
    "amplitude": "arb",
    "count": "count",
    "current": "A",
    "frequency": "Hz",
    "phase": "rad",
    "ratio": "ratio",
    "resistance": "Ohm",
    "temperature": "K",
    "time": "s",
    "voltage": "V",
}
_LINEAR_UNITS = tuple(
    unit for unit in UNIT_SCALE_TO_BASE if UNIT_KINDS[unit] in _BASE_UNIT_BY_KIND
)


@given(
    value=st.integers(min_value=-1_000_000, max_value=1_000_000),
    source_unit=st.sampled_from(_LINEAR_UNITS),
)
def test_quantity_semantic_equality_survives_compatible_unit_conversion(
    value: int,
    source_unit: str,
) -> None:
    target_unit = _BASE_UNIT_BY_KIND[UNIT_KINDS[source_unit]]
    source = Quantity(value, source_unit)

    assert scalar_values_equal(source, source.to(target_unit))


def test_quantity_semantic_equality_absorbs_scaled_float_noise() -> None:
    assert scalar_values_equal(
        Quantity(100.0, "uA"),
        Quantity(0.0001, "A"),
    )
    assert scalar_values_equal(
        Quantity(100.0, "ns"),
        Quantity(0.1, "us"),
    )


def test_non_linear_quantities_compare_only_in_the_same_unit() -> None:
    assert scalar_values_equal(
        Quantity(-20.0, "dBm"),
        Quantity(-20.0, "dBm"),
    )
    assert not scalar_values_equal(
        Quantity(-20.0, "dBm"),
        Quantity(-19.0, "dBm"),
    )

    with pytest.raises(ValueError, match="cannot compare quantity units"):
        scalar_values_equal(
            Quantity(-20.0, "dBm"),
            Quantity(0.001, "W"),
        )
