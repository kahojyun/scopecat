from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.measurements.contracts import (
    MeasurementValueContractIssueCode,
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDType,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
)
from scopecat.sdk.instruments import (
    InstrumentReadback,
)


def test_complex_array_satisfies_exact_dtype_unit_shape_and_leaf_contract() -> None:
    value = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        shape=[2],
        values=[
            ComplexComponents(real=0.25, imag=-0.5),
            ComplexComponents(real=0.75, imag=0.125),
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


def test_validated_array_copy_remains_detached_and_read_only() -> None:
    value = MeasurementArray.create(shape=(2,), values=[1.0, 2.0])

    copied = validated_measurement_value_copy(value)

    assert isinstance(copied, MeasurementArray)
    assert copied.values is not value.values
    assert not copied.values.flags.writeable


def test_contract_reports_typed_top_level_mismatches() -> None:
    value = MeasurementArray.create(
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


@pytest.mark.parametrize("reason", ["missing", "invalid", "overload"])
def test_unavailable_value_satisfies_its_declared_contract(
    reason: MeasurementUnavailableReason,
) -> None:
    value = MeasurementUnavailable.create(
        reason=reason,
        dtype="complex128",
        unit="ratio",
        shape=(2, 3),
        metadata={"instrument_status": reason},
    )

    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype="complex128",
            expected_unit="ratio",
            expected_shape=(2, 3),
        )
        == ()
    )


@pytest.mark.parametrize("actual_extent", [None, 4])
def test_variable_expected_extent_accepts_unknown_or_concrete_unavailable_extent(
    actual_extent: int | None,
) -> None:
    value = MeasurementUnavailable.create(
        reason="missing",
        dtype="float64",
        unit="V",
        shape=(actual_extent,),
        metadata={},
    )

    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype="float64",
            expected_unit="V",
            expected_shape=(None,),
        )
        == ()
    )


def test_mixed_fixed_and_variable_extents_accept_unknown_unavailable_extent() -> None:
    value = MeasurementUnavailable.create(
        reason="missing",
        dtype="float64",
        unit="V",
        shape=(2, None),
        metadata={},
    )

    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype="float64",
            expected_unit="V",
            expected_shape=(2, None),
        )
        == ()
    )


def test_fixed_expected_extent_rejects_unknown_unavailable_extent() -> None:
    value = MeasurementUnavailable.create(
        reason="missing",
        dtype="float64",
        unit="V",
        shape=(None,),
        metadata={},
    )

    [issue] = measurement_value_contract_issues(
        value,
        expected_dtype="float64",
        expected_unit="V",
        expected_shape=(4,),
    )

    assert issue.code is MeasurementValueContractIssueCode.SHAPE_MISMATCH
    assert (issue.expected, issue.actual) == ((4,), (None,))


def test_unavailable_value_still_checks_dtype_unit_and_shape() -> None:
    value = MeasurementUnavailable.create(
        reason="invalid",
        dtype="float64",
        unit="V",
        shape=(),
        metadata={},
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="int64",
        expected_unit="ratio",
        expected_shape=(1,),
    )

    assert tuple(issue.code for issue in issues) == (
        MeasurementValueContractIssueCode.DTYPE_MISMATCH,
        MeasurementValueContractIssueCode.UNIT_MISMATCH,
        MeasurementValueContractIssueCode.SHAPE_MISMATCH,
    )


def test_complex_array_normalizes_numeric_and_component_inputs() -> None:
    value = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        shape=[2],
        values=[
            ComplexComponents(real=0.25, imag=-0.5),
            0.75,
        ],
    )

    assert value.values.tolist() == [complex(0.25, -0.5), complex(0.75, 0.0)]
    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype="complex128",
            expected_unit="ratio",
            expected_shape=(2,),
        )
        == ()
    )


def test_scalar_tag_requires_a_matching_value_type() -> None:
    value = MeasurementScalar.create(
        dtype="int64",
        unit=None,
        value=1.5,
    )

    issues = measurement_value_contract_issues(
        value,
        expected_dtype="int64",
        expected_unit=None,
        expected_shape=(),
    )

    assert tuple(issue.code for issue in issues) == (
        MeasurementValueContractIssueCode.VALUE_TYPE_MISMATCH,
    )
    assert issues[0].path == ("value",)
    assert (issues[0].expected, issues[0].actual) == ("int", "float")


@pytest.mark.parametrize(
    ("dtype", "unit", "values"),
    (
        ("float64", "ratio", [1, 1.5]),
        ("int64", "count", [1, 2]),
        ("bool", None, [True, False]),
        ("string", None, ["first", "second"]),
    ),
)
def test_array_leaf_types_follow_the_array_dtype_tag(
    dtype: MeasurementDType,
    unit: str | None,
    values: list[object],
) -> None:
    value = MeasurementArray.create(
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
    with pytest.raises(ValidationError, match=f"values do not match {dtype}"):
        MeasurementArray.create(
            dtype=dtype,
            unit=None,
            shape=[1],
            values=[value],
        )


@pytest.mark.parametrize(
    ("value", "expected_dtype"),
    (
        (MeasurementScalar.create(dtype="float64", unit=None, value=1.5), "float64"),
        (MeasurementScalar.create(dtype="int64", unit=None, value=1), "int64"),
        (MeasurementScalar.create(dtype="bool", unit=None, value=True), "bool"),
        (MeasurementScalar.create(dtype="string", unit=None, value="ready"), "string"),
        (
            MeasurementScalar.create(
                dtype="complex128",
                unit=None,
                value=ComplexComponents(real=1.0, imag=-0.5),
            ),
            "complex128",
        ),
    ),
)
def test_scalar_values_support_every_public_dtype(
    value: MeasurementScalar,
    expected_dtype: MeasurementDType,
) -> None:
    assert not measurement_value_contract_issues(
        value,
        expected_dtype=expected_dtype,
        expected_unit=None,
        expected_shape=(),
    )


def test_unit_contract_is_strict_in_both_directions() -> None:
    unitless = MeasurementScalar.create(dtype="float64", unit=None, value=1.0)
    unitful = MeasurementScalar.create(dtype="float64", unit="GHz", value=5.0)

    assert not measurement_value_contract_issues(
        unitless,
        expected_dtype="float64",
        expected_unit=None,
        expected_shape=(),
    )
    assert not measurement_value_contract_issues(
        unitful,
        expected_dtype="float64",
        expected_unit="MHz",
        expected_shape=(),
    )
    assert tuple(
        issue.code
        for issue in measurement_value_contract_issues(
            unitless,
            expected_dtype="float64",
            expected_unit="ratio",
            expected_shape=(),
        )
    ) == (MeasurementValueContractIssueCode.UNIT_MISMATCH,)
    assert tuple(
        issue.code
        for issue in measurement_value_contract_issues(
            unitful,
            expected_dtype="float64",
            expected_unit=None,
            expected_shape=(),
        )
    ) == (MeasurementValueContractIssueCode.UNIT_MISMATCH,)


def test_top_level_numeric_dtype_widening_is_preserved() -> None:
    integer = MeasurementScalar.create(dtype="int64", unit="count", value=2)
    integer_array = MeasurementArray.create(
        dtype="int64",
        unit=None,
        shape=[2],
        values=[1, 2],
    )

    assert not measurement_value_contract_issues(
        integer,
        expected_dtype="float64",
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


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        complex(float("nan"), 0.0),
        complex(0.0, float("inf")),
    ],
)
def test_non_finite_numeric_values_are_rejected(value: complex) -> None:
    if isinstance(value, float):
        with pytest.raises(ValidationError, match="finite"):
            MeasurementScalar.create(dtype="float64", unit=None, value=value)
    with pytest.raises(ValidationError, match="finite"):
        MeasurementArray.create(
            dtype="complex128" if isinstance(value, complex) else "float64",
            unit=None,
            shape=[1],
            values=[value],
        )
    if isinstance(value, float):
        with pytest.raises(ValidationError, match="finite"):
            ComplexComponents(real=value, imag=0.0)
        with pytest.raises(ValidationError, match="finite"):
            MeasurementArray.create(
                dtype="complex128",
                unit=None,
                shape=[1],
                values=[{"real": value, "imag": 0.0}],
            )


def test_scalar_bool_and_int_values_preserve_wire_types_across_tags() -> None:
    readback = InstrumentReadback.model_validate(
        {
            "values": {
                "claimed_bool": {
                    "kind": "scalar",
                    "dtype": "bool",
                    "unit": None,
                    "value": 1,
                },
                "claimed_int": {
                    "kind": "scalar",
                    "dtype": "int64",
                    "unit": None,
                    "value": True,
                },
            }
        }
    )

    claimed_bool = readback.values["claimed_bool"]
    claimed_int = readback.values["claimed_int"]
    assert isinstance(claimed_bool, MeasurementScalar)
    assert isinstance(claimed_int, MeasurementScalar)
    assert type(claimed_bool.value) is int
    assert type(claimed_int.value) is bool
    assert [
        issue.code
        for issue in measurement_value_contract_issues(
            claimed_bool,
            expected_dtype="bool",
            expected_unit=None,
            expected_shape=(),
        )
    ] == [MeasurementValueContractIssueCode.VALUE_TYPE_MISMATCH]
    assert [
        issue.code
        for issue in measurement_value_contract_issues(
            claimed_int,
            expected_dtype="int64",
            expected_unit=None,
            expected_shape=(),
        )
    ] == [MeasurementValueContractIssueCode.VALUE_TYPE_MISMATCH]
