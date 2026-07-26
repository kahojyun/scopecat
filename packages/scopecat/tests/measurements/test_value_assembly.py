from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
)
from tests.testkit.measurement_assembly import (
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def _scenario(*, point_values: tuple[float, ...] = (0.0, 1.0), use_count: int = 3):
    return measurement_assembly_scenario(
        point_values=point_values,
        use_count=use_count,
    )


def _codes(error: CheckFailed | ProviderContractError) -> set[str]:
    return {problem.code for problem in error.problems}


def test_catalog_rejects_unsupported_scalar_measurement_dtype() -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    unsupported = replace(scenario.catalog.product_defs[0], dtype="bool")

    with pytest.raises(CheckFailed) as captured:
        replace(
            scenario.catalog,
            product_defs=(unsupported, *scenario.catalog.product_defs[1:]),
        )

    assert "measurement_value_scalar_dtype_unsupported" in _codes(captured.value)


def test_sealing_canonicalizes_candidate_order_and_copies_values() -> None:
    scenario = _scenario()
    candidates = list(measurement_value_candidates(scenario, scenario.uses))

    values = seal_measurement_values(
        scenario.catalog,
        tuple(reversed(candidates)),
        points=scenario.points,
    )
    exposed = candidates[0].value
    assert isinstance(exposed, Quantity)
    object.__setattr__(exposed, "value", 999.0)

    assert [value.product_use_id for value in values.values[:3]] == [
        use.id for use in scenario.uses
    ]
    retained = values.value_for_output(
        scenario.linked_points.point_domain.points[0].logical_id,
        scenario.uses[0].id,
    ).value
    assert isinstance(retained, Quantity)
    assert retained.value == 0.0


@pytest.mark.parametrize(
    ("mode", "code"),
    (
        ("missing", "measurement_value_output_missing"),
        ("duplicate", "measurement_value_duplicate"),
        ("unknown-use", "measurement_value_use_unknown"),
    ),
)
def test_sealing_requires_one_exact_candidate_per_point_and_use(
    mode: str,
    code: str,
) -> None:
    scenario = _scenario(use_count=2)
    candidates = list(measurement_value_candidates(scenario, scenario.uses))
    if mode == "missing":
        candidates.pop()
    elif mode == "duplicate":
        candidates.append(candidates[0])
    else:
        candidates[-1] = replace(
            candidates[-1],
            product_use_id=ProductUseId("foreign"),
        )

    with pytest.raises(ProviderContractError) as captured:
        seal_measurement_values(scenario.catalog, candidates, points=scenario.points)

    assert code in _codes(captured.value)


def test_sealing_rejects_values_outside_the_product_contract() -> None:
    scenario = _scenario(point_values=(0.0,), use_count=1)
    point = scenario.linked_points.point_domain.points[0]

    with pytest.raises(ProviderContractError) as captured:
        seal_measurement_values(
            scenario.catalog,
            (
                MeasurementValueCandidate(
                    point.logical_id,
                    scenario.uses[0].id,
                    Quantity(value=1.0, unit="V"),
                ),
            ),
            points=scenario.points,
        )

    assert "measurement_value_unit_mismatch" in _codes(captured.value)


def test_zero_points_and_empty_inventories_close_without_special_cases() -> None:
    zero_scenario = _scenario(point_values=(), use_count=1)
    empty_scenario = _scenario(use_count=0)

    assert (
        seal_measurement_values(
            zero_scenario.catalog,
            (),
            points=zero_scenario.points,
        ).values
        == ()
    )
    assert (
        seal_measurement_values(
            empty_scenario.catalog,
            (),
            points=empty_scenario.points,
        ).values
        == ()
    )
    assert zero_scenario.uses
    assert not empty_scenario.uses
