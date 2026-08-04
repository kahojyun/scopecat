from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from scopecat.compiler.bound_facts import (
    BoundMeasurementPostprocessor,
    BoundMeasurementPostprocessorOutput,
)
from scopecat.execution.measurement_postprocessors import (
    execute_measurement_postprocessors,
)
from scopecat.kernel.errors import MeasurementPostprocessorExecutionError
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.products import ProductAxisDef
from scopecat.measurements.results import (
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementValue,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    seal_measurement_values,
)
from scopecat.program.logical import MeasurementPostprocessorId
from tests.testkit.measurement_assembly import (
    MeasurementAssemblyScenario,
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def _postprocessor(
    scenario: MeasurementAssemblyScenario,
    kernel: Callable[[MeasurementValue], dict[str, MeasurementValue]],
    *,
    id: str = "normalize",
    input_index: int = 0,
    output_index: int = 1,
) -> BoundMeasurementPostprocessor:
    source = scenario.uses[input_index]
    output = scenario.uses[output_index]
    return BoundMeasurementPostprocessor(
        id=MeasurementPostprocessorId(SymbolId(local_id=id)),
        input_product_id=source.product_id,
        input_product_use_id=source.id,
        outputs=(
            BoundMeasurementPostprocessorOutput(
                id="output",
                product_id=output.product_id,
                product_use_ids=(output.id,),
            ),
        ),
        kernel=kernel,
    )


def _with_product_axes(
    scenario: MeasurementAssemblyScenario,
    axes_by_product_index: dict[int, tuple[ProductAxisDef, ...]],
) -> MeasurementAssemblyScenario:
    products = list(scenario.catalog.product_defs)
    for product_index, axes in axes_by_product_index.items():
        products[product_index] = replace(products[product_index], axes=axes)
    return replace(
        scenario,
        catalog=replace(scenario.catalog, product_defs=tuple(products)),
    )


def _axis(id: str, size: int | None) -> ProductAxisDef:
    return ProductAxisDef(
        id=id,
        dimension_id=id,
        kind="sample",
        size=size,
    )


def test_postprocessor_runs_one_direct_kernel_per_point() -> None:
    scenario = measurement_assembly_scenario(point_values=(2.0, 4.0), use_count=2)
    observed: list[float] = []

    def kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
        assert isinstance(value, MeasurementScalar)
        assert isinstance(value.value, int | float)
        observed.append(float(value.value))
        return {
            "output": MeasurementScalar.create(
                dtype="float64",
                value=value.value + 1.0,
                unit="ratio",
            )
        }

    completed = execute_measurement_postprocessors(
        (_postprocessor(scenario, kernel),),
        measurement_value_candidates(scenario, (scenario.uses[0],)),
        points=scenario.points,
        catalog=scenario.catalog,
    )
    sealed = seal_measurement_values(
        scenario.catalog,
        completed,
        points=scenario.points,
    )

    assert observed == [0.0, 100.0]
    output_use = scenario.uses[1]
    assert [
        sealed.value_for_output(point.logical_id, output_use.id).value
        for point in scenario.points
    ] == [
        MeasurementScalar.create(dtype="float64", value=1.0, unit="ratio"),
        MeasurementScalar.create(dtype="float64", value=101.0, unit="ratio"),
    ]


def test_postprocessor_chain_feeds_derived_outputs_to_downstream_nodes() -> None:
    scenario = measurement_assembly_scenario(point_values=(2.0, 4.0), use_count=3)
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    observed: list[tuple[str, float]] = []

    def increment(value: MeasurementValue) -> dict[str, MeasurementValue]:
        assert isinstance(value, MeasurementScalar)
        assert isinstance(value.value, int | float)
        observed.append(("increment", float(value.value)))
        return {
            "output": MeasurementScalar.create(
                dtype="float64",
                value=value.value + 1.0,
                unit="ratio",
            )
        }

    def double(value: MeasurementValue) -> dict[str, MeasurementValue]:
        assert isinstance(value, MeasurementScalar)
        assert isinstance(value.value, int | float)
        observed.append(("double", float(value.value)))
        return {
            "output": MeasurementScalar.create(
                dtype="float64",
                value=value.value * 2.0,
                unit="ratio",
            )
        }

    source_candidates = tuple(
        replace(candidate, evidence=evidence)
        for candidate in measurement_value_candidates(scenario, (scenario.uses[0],))
    )
    completed = execute_measurement_postprocessors(
        (
            _postprocessor(
                scenario,
                increment,
                id="increment",
                input_index=0,
                output_index=1,
            ),
            _postprocessor(
                scenario,
                double,
                id="double",
                input_index=1,
                output_index=2,
            ),
        ),
        source_candidates,
        points=scenario.points,
        catalog=scenario.catalog,
    )
    sealed = seal_measurement_values(
        scenario.catalog,
        completed,
        points=scenario.points,
    )

    assert observed == [
        ("increment", 0.0),
        ("increment", 100.0),
        ("double", 1.0),
        ("double", 101.0),
    ]
    final_use = scenario.uses[2]
    final_values = [
        sealed.value_for_output(point.logical_id, final_use.id)
        for point in scenario.points
    ]
    assert [value.value for value in final_values] == [
        MeasurementScalar.create(dtype="float64", value=2.0, unit="ratio"),
        MeasurementScalar.create(dtype="float64", value=202.0, unit="ratio"),
    ]
    assert all(value.evidence == evidence for value in final_values)


def test_postprocessor_retains_instrument_acquisition_evidence() -> None:
    scenario = measurement_assembly_scenario(point_values=(2.0,), use_count=2)
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    [source] = measurement_value_candidates(scenario, (scenario.uses[0],))
    [_, derived] = execute_measurement_postprocessors(
        (_postprocessor(scenario, lambda value: {"output": value}),),
        (replace(source, evidence=evidence),),
        points=scenario.points,
        catalog=scenario.catalog,
    )

    assert derived.evidence == evidence


def test_postprocessor_chain_propagates_unavailable_without_running_kernels() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=3)
    [source] = measurement_value_candidates(scenario, (scenario.uses[0],))
    unavailable = MeasurementUnavailable.create(
        reason="overload",
        dtype="float64",
        unit="ratio",
        shape=(),
        metadata={"instrument_status": "input saturated"},
    )

    def kernel(_value: MeasurementValue) -> dict[str, MeasurementValue]:
        raise AssertionError("unavailable inputs must not reach user kernels")

    completed = execute_measurement_postprocessors(
        (
            _postprocessor(
                scenario,
                kernel,
                id="first",
                input_index=0,
                output_index=1,
            ),
            _postprocessor(
                scenario,
                kernel,
                id="second",
                input_index=1,
                output_index=2,
            ),
        ),
        (
            MeasurementValueCandidate(
                logical_point_id=source.logical_point_id,
                product_use_id=source.product_use_id,
                value=unavailable,
            ),
        ),
        points=scenario.points,
        catalog=scenario.catalog,
    )

    propagated = completed[-1].value
    assert propagated == MeasurementUnavailable.create(
        reason="overload",
        dtype="float64",
        unit="ratio",
        shape=(),
        metadata={"instrument_status": "input saturated"},
    )


def test_postprocessor_chain_propagates_unknown_ragged_extent_without_kernels() -> None:
    scenario = _with_product_axes(
        measurement_assembly_scenario(point_values=(0.0,), use_count=3),
        {
            1: (_axis("sample", None),),
            2: (_axis("sample", None),),
        },
    )
    [source] = measurement_value_candidates(scenario, (scenario.uses[0],))
    unavailable = MeasurementUnavailable.create(
        reason="overload",
        dtype="float64",
        unit="ratio",
        shape=(),
        metadata={"instrument_status": "input saturated"},
    )

    def kernel(_value: MeasurementValue) -> dict[str, MeasurementValue]:
        raise AssertionError("unavailable inputs must not reach user kernels")

    completed = execute_measurement_postprocessors(
        (
            _postprocessor(
                scenario,
                kernel,
                id="first",
                input_index=0,
                output_index=1,
            ),
            _postprocessor(
                scenario,
                kernel,
                id="second",
                input_index=1,
                output_index=2,
            ),
        ),
        (
            MeasurementValueCandidate(
                logical_point_id=source.logical_point_id,
                product_use_id=source.product_use_id,
                value=unavailable,
            ),
        ),
        points=scenario.points,
        catalog=scenario.catalog,
    )

    intermediate = completed[-2].value
    propagated = completed[-1].value
    assert isinstance(intermediate, MeasurementUnavailable)
    assert isinstance(propagated, MeasurementUnavailable)
    assert intermediate.shape == (None,)
    assert propagated.shape == (None,)


def test_postprocessor_propagates_mixed_fixed_and_ragged_output_shape() -> None:
    scenario = _with_product_axes(
        measurement_assembly_scenario(point_values=(0.0,), use_count=2),
        {1: (_axis("channel", 2), _axis("sample", None))},
    )
    [source] = measurement_value_candidates(scenario, (scenario.uses[0],))
    unavailable = MeasurementUnavailable.create(
        reason="missing",
        dtype="float64",
        unit="ratio",
        shape=(),
        metadata={},
    )

    def kernel(_value: MeasurementValue) -> dict[str, MeasurementValue]:
        raise AssertionError("unavailable inputs must not reach user kernels")

    [_, derived] = execute_measurement_postprocessors(
        (_postprocessor(scenario, kernel),),
        (
            MeasurementValueCandidate(
                logical_point_id=source.logical_point_id,
                product_use_id=source.product_use_id,
                value=unavailable,
            ),
        ),
        points=scenario.points,
        catalog=scenario.catalog,
    )

    assert isinstance(derived.value, MeasurementUnavailable)
    assert derived.value.shape == (2, None)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (
            MeasurementScalar.create(
                dtype="complex128",
                value=complex(1.0, 0.0),
                unit="ratio",
            ),
            "measurement_postprocessor_output_dtype_mismatch",
        ),
        (
            MeasurementScalar.create(dtype="float64", value=1.0, unit="V"),
            "measurement_postprocessor_output_unit_mismatch",
        ),
        (
            MeasurementArray.create(
                dtype="float64",
                unit="ratio",
                values=[1.0],
            ),
            "measurement_postprocessor_output_shape_mismatch",
        ),
    ],
)
def test_postprocessor_validates_each_output_product_contract(
    value: MeasurementValue,
    code: str,
) -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)

    with pytest.raises(MeasurementPostprocessorExecutionError) as caught:
        execute_measurement_postprocessors(
            (_postprocessor(scenario, lambda _source: {"output": value}),),
            measurement_value_candidates(scenario, (scenario.uses[0],)),
            points=scenario.points,
            catalog=scenario.catalog,
        )

    assert [problem.code for problem in caught.value.problems] == [code]


def test_postprocessor_kernel_exception_becomes_one_execution_problem() -> None:
    scenario = measurement_assembly_scenario(point_values=(0.0,), use_count=2)

    def fail(_value: MeasurementValue) -> dict[str, MeasurementValue]:
        raise RuntimeError("classification failed")

    with pytest.raises(MeasurementPostprocessorExecutionError) as caught:
        execute_measurement_postprocessors(
            (_postprocessor(scenario, fail),),
            measurement_value_candidates(scenario, (scenario.uses[0],)),
            points=scenario.points,
            catalog=scenario.catalog,
        )

    [problem] = caught.value.problems
    assert problem.code == "measurement_postprocessor_kernel_failed"
    assert problem.details["exception_type"] == "builtins.RuntimeError"
