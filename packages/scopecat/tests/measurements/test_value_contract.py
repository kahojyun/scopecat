from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest

from scopecat.execution.effect_interpreter import validate_readback
from scopecat.execution.local.program import CollectionResultBinding, CollectOperation
from scopecat.kernel.problems import ModelLocation
from scopecat.kernel.product_identity import ProductUseId, product_id
from scopecat.measurements.contracts import (
    MeasurementValueContractIssueCode,
    measurement_value_contract_issues,
)
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
    CollectAxisRequest,
    CollectCommand,
    CollectProductRequest,
    InstrumentReadback,
)


def test_complex_array_satisfies_exact_dtype_unit_shape_and_leaf_contract() -> None:
    value = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[2],
        values=[
            ComplexQuantity(real=0.25, imag=-0.5, unit="ratio"),
            ComplexQuantity(real=0.75, imag=0.125, unit="ratio"),
        ],
    )

    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype="complex128",
            expected_unit="ratio",
            expected_shape=(2,),
        )
        == ()
    )


def test_contract_reports_typed_top_level_mismatches() -> None:
    value = MeasurementArray(
        dtype="float64",
        unit="V",
        shape=[2],
        values=[0.25, 0.75],
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="int64",
        expected_unit="ratio",
        expected_shape=(3,),
    )

    assert tuple(issue.code for issue in issues) == (
        MeasurementValueContractIssueCode.DTYPE_MISMATCH,
        MeasurementValueContractIssueCode.UNIT_MISMATCH,
        MeasurementValueContractIssueCode.SHAPE_MISMATCH,
    )
    assert tuple(issue.path for issue in issues) == (
        ("dtype",),
        ("unit",),
        ("shape",),
    )
    assert (issues[0].expected, issues[0].actual) == ("int64", "float64")
    assert (issues[1].expected, issues[1].actual) == ("ratio", "V")
    assert (issues[2].expected, issues[2].actual) == ((3,), (2,))


def test_contract_checks_actual_nested_array_structure() -> None:
    value = MeasurementArray(
        dtype="float64",
        unit=None,
        shape=[2, 1],
        values=[[0.25], [0.75]],
    )
    value.values[1] = []

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="float64",
        expected_unit=None,
        expected_shape=(2, 1),
    )

    assert len(issues) == 1
    assert issues[0].code is MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH
    assert issues[0].path == ("values", 1)
    assert (issues[0].expected, issues[0].actual) == (1, 0)


def test_complex_array_tag_requires_complex_quantity_leaves() -> None:
    value = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[2],
        values=[
            ComplexQuantity(real=0.25, imag=-0.5, unit="ratio"),
            0.75,
        ],
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="complex128",
        expected_unit="ratio",
        expected_shape=(2,),
    )

    assert len(issues) == 1
    assert (
        issues[0].code is MeasurementValueContractIssueCode.ARRAY_ELEMENT_TYPE_MISMATCH
    )
    assert issues[0].path == ("values", 1)
    assert (issues[0].expected, issues[0].actual) == (
        "ComplexQuantity",
        "float",
    )


def test_contract_revalidates_mutated_complex_models() -> None:
    scalar = ComplexQuantity(real=0.25, imag=-0.5, unit="ratio")
    object.__setattr__(scalar, "real", "not-a-number")
    array = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[1],
        values=[ComplexQuantity(real=0.75, imag=0.125, unit="ratio")],
    )
    object.__setattr__(array.values[0], "imag", "not-a-number")

    scalar_issues = measurement_value_contract_issues(
        scalar,
        expected_dtype="complex128",
        expected_unit="ratio",
        expected_shape=(),
    )
    array_issues = measurement_value_contract_issues(
        array,
        expected_dtype="complex128",
        expected_unit="ratio",
        expected_shape=(1,),
    )

    assert tuple(issue.code for issue in scalar_issues) == (
        MeasurementValueContractIssueCode.VALUE_MODEL_INVALID,
    )
    assert tuple(issue.code for issue in array_issues) == (
        MeasurementValueContractIssueCode.ARRAY_ELEMENT_TYPE_MISMATCH,
    )


def test_nested_quantity_units_must_equal_the_array_unit() -> None:
    value = MeasurementArray(
        dtype="float64",
        unit="ns",
        shape=[2],
        values=[
            Quantity(value=1.0, unit="ns"),
            Quantity(value=2.0, unit="us"),
        ],
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="float64",
        expected_unit="ns",
        expected_shape=(2,),
    )

    assert len(issues) == 1
    assert (
        issues[0].code is MeasurementValueContractIssueCode.ARRAY_ELEMENT_UNIT_MISMATCH
    )
    assert issues[0].path == ("values", 1, "unit")
    assert (issues[0].expected, issues[0].actual) == ("ns", "us")


def test_nested_complex_units_must_equal_the_array_unit() -> None:
    value = MeasurementArray(
        dtype="complex128",
        unit="ratio",
        shape=[1],
        values=[ComplexQuantity(real=0.25, imag=-0.5, unit="V")],
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="complex128",
        expected_unit="ratio",
        expected_shape=(1,),
    )

    assert tuple(issue.code for issue in issues) == (
        MeasurementValueContractIssueCode.ARRAY_ELEMENT_UNIT_MISMATCH,
    )
    assert issues[0].path == ("values", 0, "unit")
    assert (issues[0].expected, issues[0].actual) == ("ratio", "V")


@pytest.mark.parametrize(
    ("dtype", "unit", "values"),
    (
        ("float64", "ratio", [1, 1.5, Quantity(value=2.0, unit="ratio")]),
        ("int64", "count", [1, Quantity(value=2.0, unit="count")]),
        ("bool", None, [True, False]),
        ("string", None, ["first", "second"]),
    ),
)
def test_array_leaf_types_follow_the_array_dtype_tag(
    dtype: MeasurementDType,
    unit: str | None,
    values: list[object],
) -> None:
    value = MeasurementArray(
        dtype=dtype,
        unit=unit,
        shape=[len(values)],
        values=values,
    )

    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype=dtype,
            expected_unit=unit,
            expected_shape=(len(values),),
        )
        == ()
    )


@pytest.mark.parametrize(
    ("dtype", "value"),
    (
        ("float64", True),
        ("int64", 1.0),
        ("bool", 1),
        ("string", True),
    ),
)
def test_array_dtype_tags_reject_other_leaf_types(
    dtype: MeasurementDType,
    value: object,
) -> None:
    array = MeasurementArray(
        dtype=dtype,
        unit=None,
        shape=[1],
        values=[value],
    )

    issues = measurement_value_contract_issues(
        array,
        expected_dtype=dtype,
        expected_unit=None,
        expected_shape=(1,),
    )

    assert tuple(issue.code for issue in issues) == (
        MeasurementValueContractIssueCode.ARRAY_ELEMENT_TYPE_MISMATCH,
    )


def test_top_level_numeric_dtype_widening_is_preserved() -> None:
    integral = Quantity(value=2.0, unit="count")
    fractional = Quantity(value=2.5, unit="count")
    integer_array = MeasurementArray(
        dtype="int64",
        unit=None,
        shape=[2],
        values=[1, 2],
    )

    assert not measurement_value_contract_issues(
        integral,
        expected_dtype="int64",
        expected_unit="count",
        expected_shape=(),
    )
    assert not measurement_value_contract_issues(
        integer_array,
        expected_dtype="float64",
        expected_unit=None,
        expected_shape=(2,),
    )
    assert not measurement_value_contract_issues(
        integer_array,
        expected_dtype="complex128",
        expected_unit=None,
        expected_shape=(2,),
    )
    assert tuple(
        issue.code
        for issue in measurement_value_contract_issues(
            fractional,
            expected_dtype="int64",
            expected_unit="count",
            expected_shape=(),
        )
    ) == (MeasurementValueContractIssueCode.DTYPE_MISMATCH,)


def _collect_operation(
    *,
    dtype: MeasurementDType,
    unit: str | None,
    shape: Sequence[int],
) -> CollectOperation:
    operation_id = "point.collect.source"
    logical_product_id = product_id("iq")
    product_use_id = ProductUseId("record:iq")
    return CollectOperation(
        operation_id=operation_id,
        instrument_id="source",
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id="source",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="iq",
                    dtype=dtype,
                    unit=unit,
                    dimensions=[
                        CollectAxisRequest(
                            id=f"axis-{index}",
                            kind="array",
                            size=size,
                        )
                        for index, size in enumerate(shape)
                    ],
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key="iq",
                product_use_id=product_use_id,
                product_id=logical_product_id,
            ),
        ),
    )


def test_execution_readback_preserves_top_level_problem_codes() -> None:
    operation = _collect_operation(dtype="int64", unit="ratio", shape=(3,))
    readback = InstrumentReadback(
        values={
            "iq": MeasurementArray(
                dtype="float64",
                unit="V",
                shape=[2],
                values=[0.25, 0.75],
            )
        }
    )

    problems = validate_readback(operation, readback)

    assert tuple(problem.code for problem in problems) == (
        "instrument_readback_dtype_mismatch",
        "instrument_readback_unit_mismatch",
        "instrument_readback_shape_mismatch",
    )
    assert all(isinstance(problem.location, ModelLocation) for problem in problems)
    assert tuple(
        cast("ModelLocation", problem.location).path for problem in problems
    ) == (
        ("values", "iq", "dtype"),
        ("values", "iq", "unit"),
        ("values", "iq", "shape"),
    )


def test_execution_readback_maps_leaf_issues_to_value_mismatch() -> None:
    operation = _collect_operation(
        dtype="complex128",
        unit="ratio",
        shape=(2,),
    )
    readback = InstrumentReadback(
        values={
            "iq": MeasurementArray(
                dtype="complex128",
                unit="ratio",
                shape=[2],
                values=[
                    ComplexQuantity(real=0.25, imag=-0.5, unit="ratio"),
                    0.75,
                ],
            )
        }
    )

    problems = validate_readback(operation, readback)

    assert tuple(problem.code for problem in problems) == (
        "instrument_readback_value_mismatch",
    )
    assert isinstance(problems[0].location, ModelLocation)
    assert problems[0].location.path == ("values", "iq", "values", 1)
    assert "array_element_type_mismatch" in problems[0].message


def test_execution_readback_maps_nested_structure_to_shape_mismatch() -> None:
    operation = _collect_operation(
        dtype="float64",
        unit=None,
        shape=(2, 1),
    )
    value = MeasurementArray(
        dtype="float64",
        unit=None,
        shape=[2, 1],
        values=[[0.25], [0.75]],
    )
    readback = InstrumentReadback(values={"iq": value})
    retained = cast("MeasurementArray", readback.values["iq"])
    retained.values[1] = []

    problems = validate_readback(operation, readback)

    assert tuple(problem.code for problem in problems) == (
        "instrument_readback_shape_mismatch",
    )
    assert isinstance(problems[0].location, ModelLocation)
    assert problems[0].location.path == ("values", "iq", "values", 1)
    assert "structure" in problems[0].message
