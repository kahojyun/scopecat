from __future__ import annotations

from collections.abc import Callable

import pytest

from scopecat.compiler.semantic.model import MeasurementPostprocessorId
from scopecat.compiler.typed.program import (
    TypedMeasurementPostprocessor,
    TypedMeasurementPostprocessorOutput,
)
from scopecat.execution.measurement_postprocessors import (
    execute_measurement_postprocessors,
)
from scopecat.kernel.errors import MeasurementPostprocessorExecutionError
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.measurements.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.measurements.values import seal_measurement_values
from tests.testkit.measurement_assembly import (
    MeasurementAssemblyScenario,
    measurement_assembly_scenario,
    measurement_value_candidates,
)


def _postprocessor(
    scenario: MeasurementAssemblyScenario,
    kernel: Callable[[MeasurementValue], dict[str, MeasurementValue]],
) -> TypedMeasurementPostprocessor:
    source, output = scenario.uses
    return TypedMeasurementPostprocessor(
        id=MeasurementPostprocessorId(SymbolId(local_id="normalize")),
        input_product_id=source.product_id,
        input_product_use_id=source.id,
        outputs=(
            TypedMeasurementPostprocessorOutput(
                id="output",
                product_id=output.product_id,
                product_use_ids=(output.id,),
            ),
        ),
        kernel=kernel,
    )


def test_postprocessor_runs_one_direct_kernel_per_point() -> None:
    scenario = measurement_assembly_scenario(point_values=(2.0, 4.0), use_count=2)
    observed: list[float] = []

    def kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
        assert isinstance(value, Quantity)
        observed.append(value.value)
        return {"output": Quantity(value.value + 1.0, "ratio")}

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
        Quantity(1.0, "ratio"),
        Quantity(101.0, "ratio"),
    ]


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (
            ComplexQuantity(real=1.0, imag=0.0, unit="ratio"),
            "measurement_postprocessor_output_dtype_mismatch",
        ),
        (
            Quantity(1.0, "V"),
            "measurement_postprocessor_output_unit_mismatch",
        ),
        (
            MeasurementArray(
                dtype="float64",
                unit="ratio",
                shape=[1],
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
