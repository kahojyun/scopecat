from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.product_identity import ProductUseId
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
    select_measurement_values,
)
from scopecat.records.parameter import Quantity
from tests.testkit.measurement_assembly import (
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def _selection(*, point_values: tuple[float, ...] = (0.0, 1.0), use_count: int = 3):
    scenario = measurement_assembly_scenario(
        point_values=point_values,
        use_count=use_count,
    )
    selected = select_measurement_values(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in scenario.uses),
    )
    return scenario, selected


def _codes(error: CheckFailed | ProviderContractError) -> set[str]:
    return {problem.code for problem in error.problems}


def test_selection_is_canonical_and_declaration_order_independent() -> None:
    scenario = measurement_assembly_scenario(use_count=3)

    selected = select_measurement_values(
        scenario.linked_points,
        required_product_use_ids=tuple(use.id for use in reversed(scenario.uses)),
    )

    assert selected.product_use_ids == tuple(use.id for use in scenario.uses)


def test_selection_rejects_duplicate_and_unknown_uses() -> None:
    scenario = measurement_assembly_scenario(use_count=1)

    with pytest.raises(CheckFailed) as duplicate:
        select_measurement_values(
            scenario.linked_points,
            required_product_use_ids=(scenario.uses[0].id, scenario.uses[0].id),
        )
    with pytest.raises(CheckFailed) as unknown:
        select_measurement_values(
            scenario.linked_points,
            required_product_use_ids=(ProductUseId("foreign"),),
        )

    assert "measurement_value_required_use_duplicate" in _codes(duplicate.value)
    assert "measurement_value_required_use_unknown" in _codes(unknown.value)


def test_sealing_canonicalizes_candidate_order_and_copies_values() -> None:
    scenario, selected = _selection()
    candidates = list(measurement_value_candidates(scenario, scenario.uses))

    values = seal_measurement_values(selected, tuple(reversed(candidates)))
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
    scenario, selected = _selection(use_count=2)
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
        seal_measurement_values(selected, candidates)

    assert code in _codes(captured.value)


def test_sealing_rejects_values_outside_the_product_contract() -> None:
    scenario, selected = _selection(point_values=(0.0,), use_count=1)
    point = scenario.linked_points.point_domain.points[0]

    with pytest.raises(ProviderContractError) as captured:
        seal_measurement_values(
            selected,
            (
                MeasurementValueCandidate(
                    point.logical_id,
                    scenario.uses[0].id,
                    Quantity(value=1.0, unit="V"),
                ),
            ),
        )

    assert "measurement_value_unit_mismatch" in _codes(captured.value)


def test_zero_points_and_empty_inventories_close_without_special_cases() -> None:
    zero_scenario, zero_selected = _selection(point_values=(), use_count=1)
    empty_scenario, empty_selected = _selection(use_count=0)

    assert seal_measurement_values(zero_selected, ()).values == ()
    assert seal_measurement_values(empty_selected, ()).values == ()
    assert zero_scenario.uses
    assert not empty_scenario.uses
