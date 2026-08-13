from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from scopecat_testkit.measurement_assembly import (
    measurement_assembly_scenario,
    measurement_value_candidates,
)

from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.measurements.points import RunPointContract
from scopecat.measurements.results import (
    InstrumentAcquisitionEvidence,
    MeasurementScalar,
)
from scopecat.measurements.values import (
    MeasurementValueCatalog,
    seal_measurement_values,
)
from scopecat.program.point_domain import point_axis_values


def _scenario(*, point_values: tuple[float, ...] = (0.0, 1.0), use_count: int = 3):
    return measurement_assembly_scenario(
        point_values=point_values,
        use_count=use_count,
    )


def _codes(error: ProviderContractError) -> set[str]:
    return {problem.code for problem in error.problems}


def test_catalog_fingerprint_ignores_unserializable_opaque_axis_values() -> None:
    def catalog(payload: object) -> MeasurementValueCatalog:
        return MeasurementValueCatalog(
            point_contract=RunPointContract(
                experiment_id="opaque-axis",
                experiment_kind="test",
                point_count=1,
                point_limit=1,
                coordinate_columns=(),
                domain_axes=(
                    point_axis_values(
                        "opaque",
                        Scalar(Payload("opaque")),
                        (PayloadValue(schema_id="opaque", payload=payload),),
                    ),
                ),
            ),
            product_uses=(),
            product_defs=(),
        )

    assert (
        catalog(object()).contract_fingerprint == catalog(object()).contract_fingerprint
    )


@pytest.mark.parametrize("dtype", ["bool", "string"])
def test_catalog_accepts_every_scalar_measurement_dtype(dtype: str) -> None:
    scenario = measurement_assembly_scenario(use_count=3)
    selected = replace(
        scenario.catalog.product_defs[0],
        dtype=dtype,
        unit=None,
    )

    catalog = replace(
        scenario.catalog,
        product_defs=(selected, *scenario.catalog.product_defs[1:]),
    )

    assert catalog.product_defs[0].dtype == dtype
    assert catalog.contract_fingerprint != scenario.catalog.contract_fingerprint


def test_sealing_canonicalizes_candidate_order() -> None:
    scenario = _scenario()
    candidates = list(measurement_value_candidates(scenario, scenario.uses))
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    candidates[0] = replace(candidates[0], evidence=evidence)

    values = seal_measurement_values(
        scenario.catalog,
        tuple(reversed(candidates)),
        points=scenario.points,
    )
    assert [value.product_use_id for value in values.values[:3]] == [
        use.id for use in scenario.uses
    ]
    retained = values.value_for_output(
        scenario.bound_points.point_domain.points[0].logical_id,
        scenario.uses[0].id,
    ).value
    assert isinstance(retained, MeasurementScalar)
    assert retained.dtype == "float64"
    assert retained.unit == "ratio"
    assert retained.value == 0.0
    assert (
        values.value_for_output(
            scenario.bound_points.point_domain.points[0].logical_id,
            scenario.uses[0].id,
        ).evidence
        == evidence
    )


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
