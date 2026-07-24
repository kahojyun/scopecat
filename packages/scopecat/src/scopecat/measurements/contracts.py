"""Pure structural contracts for point-local measurement values."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from pydantic import ValidationError

from scopecat.kernel.units import compatible_units
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementDType,
    MeasurementValue,
)
from scopecat.records.parameter import Quantity

type MeasurementValueContractPathItem = str | int
type MeasurementValueContractFact = str | int | None | tuple[int, ...]


class MeasurementValueContractIssueCode(StrEnum):
    """Stable dimensions of a measurement-value contract violation."""

    DTYPE_MISMATCH = "dtype_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    ARRAY_STRUCTURE_MISMATCH = "array_structure_mismatch"
    ARRAY_ELEMENT_TYPE_MISMATCH = "array_element_type_mismatch"
    ARRAY_ELEMENT_UNIT_MISMATCH = "array_element_unit_mismatch"
    VALUE_MODEL_INVALID = "value_model_invalid"


@dataclass(frozen=True, slots=True)
class MeasurementValueContractIssue:
    """One typed mismatch with an exact value-relative location."""

    code: MeasurementValueContractIssueCode
    path: tuple[MeasurementValueContractPathItem, ...]
    expected: MeasurementValueContractFact
    actual: MeasurementValueContractFact


def measurement_value_contract_issues(
    value: MeasurementValue,
    *,
    expected_dtype: MeasurementDType,
    expected_unit: str | None,
    expected_shape: Sequence[int],
) -> tuple[MeasurementValueContractIssue, ...]:
    """Check one value against a logical product's point-local contract.

    Top-level dtype compatibility permits numeric widening. Array leaves are
    checked against the array's own dtype tag so that the tag cannot
    impersonate a typed payload.
    """

    if isinstance(value, MeasurementArray):
        try:
            declared_shape = tuple(value.shape)
        except TypeError:
            declared_shape = None
        if declared_shape is not None:
            structure_issues: list[MeasurementValueContractIssue] = []
            _validate_array_structure(
                value.values,
                declared_shape=declared_shape,
                path=("values",),
                issues=structure_issues,
            )
            if structure_issues:
                return tuple(structure_issues)

    try:
        selected_value = validated_measurement_value_copy(value)
    except ValidationError as error:
        errors = error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
        first_error = cast("dict[str, object]", cast("object", errors[0]))
        first_path = _validation_error_path(first_error.get("loc", ()))
        return (
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.VALUE_MODEL_INVALID,
                path=first_path,
                expected=type(value).__name__,
                actual=str(first_error.get("type", "validation_error")),
            ),
        )
    except (TypeError, ValueError) as error:
        return (
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.VALUE_MODEL_INVALID,
                path=(),
                expected=type(value).__name__,
                actual=type(error).__name__,
            ),
        )

    selected_shape = tuple(expected_shape)
    issues: list[MeasurementValueContractIssue] = []
    actual_dtype = _measurement_value_dtype(selected_value)
    if not _dtype_compatible(expected_dtype, actual_dtype, selected_value):
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.DTYPE_MISMATCH,
                path=("dtype",),
                expected=expected_dtype,
                actual=actual_dtype,
            )
        )

    actual_unit = _measurement_value_unit(selected_value)
    if expected_unit is not None and not _unit_compatible(
        expected_unit,
        actual_unit,
    ):
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.UNIT_MISMATCH,
                path=("unit",),
                expected=expected_unit,
                actual=actual_unit,
            )
        )

    actual_shape = _measurement_value_shape(selected_value)
    if actual_shape != selected_shape:
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.SHAPE_MISMATCH,
                path=("shape",),
                expected=selected_shape,
                actual=actual_shape,
            )
        )

    if isinstance(selected_value, MeasurementArray):
        _validate_array_node(
            selected_value.values,
            declared_shape=tuple(selected_value.shape),
            dtype=selected_value.dtype,
            unit=selected_value.unit,
            path=("values",),
            issues=issues,
        )
    return tuple(issues)


def validated_measurement_value_copy(value: MeasurementValue) -> MeasurementValue:
    """Revalidate and deeply detach one measurement value from caller state."""

    data = value.model_dump(mode="python", warnings=False)
    if isinstance(value, Quantity):
        return Quantity.model_validate(data)
    if isinstance(value, ComplexQuantity):
        return ComplexQuantity.model_validate(data)
    return MeasurementArray.model_validate(data)


def _validation_error_path(
    value: object,
) -> tuple[MeasurementValueContractPathItem, ...]:
    if not isinstance(value, tuple | list):
        return ()
    selected = cast("tuple[object, ...] | list[object]", value)
    return tuple(
        item if isinstance(item, str | int) else repr(item) for item in selected
    )


def _measurement_value_dtype(value: MeasurementValue) -> str:
    if isinstance(value, MeasurementArray):
        return value.dtype
    if isinstance(value, ComplexQuantity):
        return "complex128"
    return "float64"


def _measurement_value_unit(value: MeasurementValue) -> str | None:
    return value.unit


def _measurement_value_shape(value: MeasurementValue) -> tuple[int, ...]:
    if isinstance(value, MeasurementArray):
        return tuple(value.shape)
    return ()


def _dtype_compatible(
    expected: MeasurementDType,
    actual: str,
    value: MeasurementValue,
) -> bool:
    if actual == expected:
        return True
    if expected == "float64" and actual == "int64":
        return True
    if expected == "complex128" and actual in {"float64", "int64"}:
        return True
    if expected == "int64" and isinstance(value, Quantity):
        return _is_integral_number(value.value)
    return False


def _unit_compatible(expected: str, actual: str | None) -> bool:
    if actual is None:
        return False
    try:
        return compatible_units(expected, actual)
    except ValueError:
        return False


def _validate_array_node(
    value: object,
    *,
    declared_shape: tuple[int, ...],
    dtype: MeasurementDType,
    unit: str | None,
    path: tuple[MeasurementValueContractPathItem, ...],
    issues: list[MeasurementValueContractIssue],
) -> None:
    if declared_shape:
        expected_size = declared_shape[0]
        if not isinstance(value, list):
            issues.append(
                MeasurementValueContractIssue(
                    code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                    path=path,
                    expected=f"list[{expected_size}]",
                    actual=type(value).__name__,
                )
            )
            return
        selected = cast("list[object]", value)
        if len(selected) != expected_size:
            issues.append(
                MeasurementValueContractIssue(
                    code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                    path=path,
                    expected=expected_size,
                    actual=len(selected),
                )
            )
            return
        for index, item in enumerate(selected):
            _validate_array_node(
                item,
                declared_shape=declared_shape[1:],
                dtype=dtype,
                unit=unit,
                path=(*path, index),
                issues=issues,
            )
        return

    if isinstance(value, list):
        selected = cast("list[object]", value)
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                path=path,
                expected="scalar",
                actual=f"list[{len(selected)}]",
            )
        )
        return
    _validate_array_leaf(
        value,
        dtype=dtype,
        unit=unit,
        path=path,
        issues=issues,
    )


def _validate_array_structure(
    value: object,
    *,
    declared_shape: tuple[int, ...],
    path: tuple[MeasurementValueContractPathItem, ...],
    issues: list[MeasurementValueContractIssue],
) -> None:
    if declared_shape:
        expected_size = declared_shape[0]
        if not isinstance(value, list):
            issues.append(
                MeasurementValueContractIssue(
                    code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                    path=path,
                    expected=f"list[{expected_size}]",
                    actual=type(value).__name__,
                )
            )
            return
        selected = cast("list[object]", value)
        if len(selected) != expected_size:
            issues.append(
                MeasurementValueContractIssue(
                    code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                    path=path,
                    expected=expected_size,
                    actual=len(selected),
                )
            )
            return
        for index, item in enumerate(selected):
            _validate_array_structure(
                item,
                declared_shape=declared_shape[1:],
                path=(*path, index),
                issues=issues,
            )
        return
    if isinstance(value, list):
        selected = cast("list[object]", value)
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH,
                path=path,
                expected="scalar",
                actual=f"list[{len(selected)}]",
            )
        )


def _validate_array_leaf(
    value: object,
    *,
    dtype: MeasurementDType,
    unit: str | None,
    path: tuple[MeasurementValueContractPathItem, ...],
    issues: list[MeasurementValueContractIssue],
) -> None:
    valid = False
    expected_type = ""
    if dtype == "complex128":
        expected_type = "ComplexQuantity"
        valid = isinstance(value, ComplexQuantity)
    elif dtype == "float64":
        expected_type = "float, int, or Quantity"
        valid = isinstance(value, int | float | Quantity) and not isinstance(
            value, bool
        )
    elif dtype == "int64":
        expected_type = "int or integral Quantity"
        valid = (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, Quantity) and _is_integral_number(value.value)
        )
    elif dtype == "bool":
        expected_type = "bool"
        valid = isinstance(value, bool)
    elif dtype == "string":
        expected_type = "str"
        valid = isinstance(value, str)

    if not valid:
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.ARRAY_ELEMENT_TYPE_MISMATCH,
                path=path,
                expected=expected_type,
                actual=type(value).__name__,
            )
        )
        return
    if isinstance(value, Quantity | ComplexQuantity) and value.unit != unit:
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.ARRAY_ELEMENT_UNIT_MISMATCH,
                path=(*path, "unit"),
                expected=unit,
                actual=value.unit,
            )
        )


def _is_integral_number(value: float) -> bool:
    try:
        return int(value) == value
    except (OverflowError, ValueError):
        return False
