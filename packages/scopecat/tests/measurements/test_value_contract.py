from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.measurements.contracts import (
    MeasurementValueContractIssueCode,
    measurement_value_contract_issues,
)
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDType,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
)
from scopecat.sdk.instruments import (
    InstrumentReadback,
)


def test_complex_array_satisfies_exact_dtype_unit_shape_and_leaf_contract() -> None:
    value = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        values=[complex(0.25, -0.5), complex(0.75, 0.125)],
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
    value = MeasurementArray.create(
        dtype="float64",
        unit="V",
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


def test_complex_array_normalizes_numeric_and_wire_component_inputs() -> None:
    value = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        values=[
            {"real": 0.25, "imag": -0.5},
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


@pytest.mark.parametrize(
    ("dtype", "raw", "expected", "expected_type"),
    (
        ("float64", 1, 1.0, float),
        ("float64", 1.5, 1.5, float),
        ("int64", 2, 2, int),
        ("complex128", 2, complex(2.0, 0.0), complex),
        ("complex128", 2.5, complex(2.5, 0.0), complex),
        ("complex128", 2.5 - 0.25j, 2.5 - 0.25j, complex),
        (
            "complex128",
            {"real": 0.25, "imag": -0.5},
            complex(0.25, -0.5),
            complex,
        ),
        ("bool", True, True, bool),
        ("string", "ready", "ready", str),
    ),
)
def test_scalar_values_normalize_strictly_at_the_model_boundary(
    dtype: MeasurementDType,
    raw: object,
    expected: object,
    expected_type: type[object],
) -> None:
    value = MeasurementScalar.create(dtype=dtype, value=raw)

    assert value.value == expected
    assert type(value.value) is expected_type
    assert (
        measurement_value_contract_issues(
            value,
            expected_dtype=dtype,
            expected_unit=None,
            expected_shape=(),
        )
        == ()
    )


@pytest.mark.parametrize(
    ("dtype", "raw"),
    (
        ("float64", True),
        ("float64", 1 + 0j),
        ("int64", True),
        ("int64", 1.0),
        ("int64", 2**63),
        ("complex128", True),
        ("complex128", "1+2j"),
        ("complex128", {"real": 1.0}),
        ("complex128", {"real": 1.0, "imag": 2.0, "extra": 3.0}),
        ("complex128", {"real": True, "imag": 0.0}),
        ("bool", 1),
        ("bool", "true"),
        ("string", True),
        ("string", 1),
    ),
)
def test_scalar_values_reject_cross_dtype_coercion(
    dtype: MeasurementDType,
    raw: object,
) -> None:
    with pytest.raises(ValidationError):
        MeasurementScalar.create(dtype=dtype, value=raw)


def test_complex_scalar_uses_native_runtime_and_component_object_wire_value() -> None:
    value = MeasurementScalar.create(
        dtype="complex128",
        unit="ratio",
        value=complex(0.25, -0.5),
    )

    assert type(value.value) is complex
    assert value.model_dump(mode="json")["value"] == {
        "real": 0.25,
        "imag": -0.5,
    }
    restored = MeasurementScalar.model_validate_json(value.model_dump_json())
    assert type(restored.value) is complex
    assert restored == value


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
                value=complex(1.0, -0.5),
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


def test_unit_contract_requires_exact_units_without_implicit_conversion() -> None:
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
        expected_unit="GHz",
        expected_shape=(),
    )
    # Contract validation does not rescale the stored number. Accepting GHz as
    # MHz would therefore make downstream views label 5.0 GHz as 5.0 MHz.
    assert tuple(
        issue.code
        for issue in measurement_value_contract_issues(
            unitful,
            expected_dtype="float64",
            expected_unit="MHz",
            expected_shape=(),
        )
    ) == (MeasurementValueContractIssueCode.UNIT_MISMATCH,)
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


def test_persisted_numeric_dtype_requires_an_exact_match() -> None:
    integer = MeasurementScalar.create(dtype="int64", unit="count", value=2)
    integer_array = MeasurementArray.create(
        dtype="int64",
        unit=None,
        values=[1, 2],
    )
    floating = MeasurementScalar.create(dtype="float64", unit=None, value=2.0)

    cases: tuple[
        tuple[
            MeasurementValue,
            MeasurementDType,
            str | None,
            tuple[int, ...],
        ],
        ...,
    ] = (
        (integer, "float64", "count", ()),
        (integer_array, "float64", None, (2,)),
        (integer_array, "complex128", None, (2,)),
        (floating, "complex128", None, ()),
    )
    for value, expected_dtype, expected_unit, expected_shape in cases:
        [issue] = measurement_value_contract_issues(
            value,
            expected_dtype=expected_dtype,
            expected_unit=expected_unit,
            expected_shape=expected_shape,
        )
        assert issue.code is MeasurementValueContractIssueCode.DTYPE_MISMATCH
        assert issue.expected == expected_dtype
        assert issue.actual == value.dtype


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
    scalar_dtype: MeasurementDType = (
        "complex128" if isinstance(value, complex) else "float64"
    )
    with pytest.raises(ValidationError, match="finite"):
        MeasurementScalar.create(dtype=scalar_dtype, unit=None, value=value)
    with pytest.raises(ValidationError, match="finite"):
        MeasurementArray.create(
            dtype=scalar_dtype,
            unit=None,
            values=[value],
        )
    if isinstance(value, float):
        with pytest.raises(ValidationError, match="finite"):
            MeasurementScalar.create(
                dtype="complex128",
                unit=None,
                value={"real": value, "imag": 0.0},
            )
        with pytest.raises(ValidationError, match="finite"):
            MeasurementArray.create(
                dtype="complex128",
                unit=None,
                values=[{"real": value, "imag": 0.0}],
            )


@pytest.mark.parametrize(
    ("dtype", "raw"),
    (("bool", 1), ("int64", True), ("string", False)),
)
def test_nested_instrument_readback_rejects_invalid_scalar_wire_values(
    dtype: MeasurementDType,
    raw: object,
) -> None:
    with pytest.raises(ValidationError):
        InstrumentReadback.model_validate(
            {
                "values": {
                    "invalid": {
                        "kind": "scalar",
                        "dtype": dtype,
                        "unit": None,
                        "value": raw,
                    }
                }
            }
        )
