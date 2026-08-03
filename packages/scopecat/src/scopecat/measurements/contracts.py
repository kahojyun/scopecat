"""Pure structural contracts for point-local measurement values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.units import compatible_units
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementDType,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementValue,
    MeasurementVariable,
    MeasurementVariableRole,
)

type MeasurementValueContractPathItem = str | int
type MeasurementValueContractFact = str | int | None | tuple[int | None, ...]


class MeasurementValueContractIssueCode(StrEnum):
    """Stable dimensions of a measurement-value contract violation."""

    DTYPE_MISMATCH = "dtype_mismatch"
    UNIT_MISMATCH = "unit_mismatch"
    SHAPE_MISMATCH = "shape_mismatch"
    VALUE_TYPE_MISMATCH = "value_type_mismatch"


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
    expected_shape: Sequence[int | None],
) -> tuple[MeasurementValueContractIssue, ...]:
    """Check one value against a logical product's point-local contract.

    Top-level dtype compatibility permits numeric widening. Available scalar
    and array leaves must match their value's own dtype tag.
    """

    selected_shape = tuple(expected_shape)
    issues: list[MeasurementValueContractIssue] = []
    actual_dtype = _measurement_value_dtype(value)
    if not _dtype_compatible(expected_dtype, actual_dtype):
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.DTYPE_MISMATCH,
                path=("dtype",),
                expected=expected_dtype,
                actual=actual_dtype,
            )
        )

    actual_unit = _measurement_value_unit(value)
    if not _unit_compatible(
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

    actual_shape = _measurement_value_shape(value)
    if not _shape_compatible(selected_shape, actual_shape):
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.SHAPE_MISMATCH,
                path=("shape",),
                expected=selected_shape,
                actual=actual_shape,
            )
        )

    if isinstance(value, MeasurementUnavailable):
        return tuple(issues)
    if isinstance(value, MeasurementScalar):
        _validate_value_type(
            value.value,
            dtype=value.dtype,
            path=("value",),
            issues=issues,
        )
    else:
        _validate_array_values(
            value.values,
            dtype=value.dtype,
            path=("values",),
            issues=issues,
        )
    return tuple(issues)


def _shape_compatible(
    expected: tuple[int | None, ...],
    actual: tuple[int, ...],
) -> bool:
    """Match rank exactly while treating a variable extent as one-axis wildcard."""

    return len(expected) == len(actual) and all(
        expected_extent is None or expected_extent == actual_extent
        for expected_extent, actual_extent in zip(expected, actual, strict=True)
    )


def validated_measurement_value_copy(value: MeasurementValue) -> MeasurementValue:
    """Detach a measurement value without repeating its construction checks."""

    return value.model_copy(deep=True)


def _measurement_value_dtype(
    value: MeasurementValue,
) -> MeasurementDType:
    return value.dtype


def _measurement_value_unit(
    value: MeasurementValue,
) -> str | None:
    return value.unit


def _measurement_value_shape(
    value: MeasurementValue,
) -> tuple[int, ...]:
    if isinstance(value, MeasurementArray | MeasurementUnavailable):
        return tuple(value.shape)
    return ()


def _dtype_compatible(
    expected: MeasurementDType,
    actual: MeasurementDType,
) -> bool:
    if actual == expected:
        return True
    if expected == "float64" and actual == "int64":
        return True
    return expected == "complex128" and actual in {"float64", "int64"}


def _unit_compatible(expected: str | None, actual: str | None) -> bool:
    if expected is None or actual is None:
        return expected is actual
    try:
        return compatible_units(expected, actual)
    except ValueError:
        return False


def _validate_array_values(
    value: object,
    *,
    dtype: MeasurementDType,
    path: tuple[MeasurementValueContractPathItem, ...],
    issues: list[MeasurementValueContractIssue],
) -> None:
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        for index, item in enumerate(selected):
            _validate_array_values(
                item,
                dtype=dtype,
                path=(*path, index),
                issues=issues,
            )
        return

    _validate_value_type(
        value,
        dtype=dtype,
        path=path,
        issues=issues,
    )


def _validate_value_type(
    value: object,
    *,
    dtype: MeasurementDType,
    path: tuple[MeasurementValueContractPathItem, ...],
    issues: list[MeasurementValueContractIssue],
) -> None:
    valid = False
    expected_type = ""
    if dtype == "complex128":
        expected_type = "ComplexComponents"
        valid = isinstance(value, ComplexComponents)
    elif dtype == "float64":
        expected_type = "float or int"
        valid = isinstance(value, int | float) and not isinstance(value, bool)
    elif dtype == "int64":
        expected_type = "int"
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif dtype == "bool":
        expected_type = "bool"
        valid = isinstance(value, bool)
    elif dtype == "string":
        expected_type = "str"
        valid = isinstance(value, str)

    if not valid:
        issues.append(
            MeasurementValueContractIssue(
                code=MeasurementValueContractIssueCode.VALUE_TYPE_MISMATCH,
                path=path,
                expected=expected_type,
                actual=type(value).__name__,
            )
        )


def validate_measurement_records_against_schema(
    records: Sequence[MeasurementRecord],
    schema: MeasurementDatasetSchema,
    dataset_id: str,
    *,
    allow_partial: bool = False,
) -> list[Problem]:
    """Validate persisted records through the canonical value contract."""

    problems: list[Problem] = []
    if schema.dataset_id != dataset_id:
        problems.append(
            _problem(
                "measurement_dataset_id_mismatch",
                f"measurement dataset schema id {schema.dataset_id} "
                f"does not match artifact id {dataset_id}",
                ("dataset_schema", "dataset_id"),
            )
        )
    problems.extend(
        _validate_dimension_sizes(
            records=records,
            schema=schema,
            allow_partial=allow_partial,
        )
    )
    dimension_sizes = {dimension.id: dimension.size for dimension in schema.dimensions}
    coordinate_variables = {
        variable.id: variable
        for variable in schema.variables
        if variable.role == "coordinate"
    }
    observable_variables = {
        variable.id: variable
        for variable in schema.variables
        if variable.role == "observable"
    }
    for record in records:
        problems.extend(
            _validate_record_variables(
                record=record,
                variables=coordinate_variables,
                actual=record.coordinates,
                role="coordinate",
                dimension_sizes=dimension_sizes,
            )
        )
        problems.extend(
            _validate_record_variables(
                record=record,
                variables=observable_variables,
                actual=record.observables,
                role="observable",
                dimension_sizes=dimension_sizes,
            )
        )
        extra_coordinates = set(record.coordinates) - set(coordinate_variables)
        for variable_id in sorted(extra_coordinates):
            problems.append(
                _problem(
                    "measurement_record_unexpected_coordinate",
                    f"measurement record {record.point_index} has unexpected "
                    f"coordinate {variable_id}",
                    ("records", record.point_index, "coordinates", variable_id),
                )
            )
        extra_observables = set(record.observables) - set(observable_variables)
        for variable_id in sorted(extra_observables):
            problems.append(
                _problem(
                    "measurement_record_unexpected_observable",
                    f"measurement record {record.point_index} has unexpected "
                    f"observable {variable_id}",
                    ("records", record.point_index, "observables", variable_id),
                )
            )
    return problems


def _validate_dimension_sizes(
    *,
    records: Sequence[MeasurementRecord],
    schema: MeasurementDatasetSchema,
    allow_partial: bool,
) -> list[Problem]:
    point_dimension = next(
        dimension for dimension in schema.dimensions if dimension.id == "point"
    )
    point_size = point_dimension.size
    assert point_size is not None
    if point_size != len(records) and not (
        allow_partial and len(records) <= point_size
    ):
        return [
            _problem(
                "measurement_dataset_record_count_mismatch",
                f"measurement dataset dimension point size {point_size} "
                f"does not match {len(records)} records",
                ("dataset_schema", "dimensions", "point", "size"),
            )
        ]
    return []


def _validate_record_variables(
    *,
    record: MeasurementRecord,
    variables: dict[str, MeasurementVariable],
    actual: Mapping[str, MeasurementValue],
    role: MeasurementVariableRole,
    dimension_sizes: Mapping[str, int | None],
) -> list[Problem]:
    problems: list[Problem] = []
    field_name = "coordinates" if role == "coordinate" else "observables"
    missing_code = (
        "measurement_record_missing_coordinate"
        if role == "coordinate"
        else "measurement_record_missing_observable"
    )
    for variable_id, variable in variables.items():
        value = actual.get(variable_id)
        if value is None:
            problems.append(
                _problem(
                    missing_code,
                    f"measurement record {record.point_index} is missing "
                    f"{role} {variable_id}",
                    ("records", record.point_index, field_name, variable_id),
                )
            )
            continue
        expected_shape = tuple(
            dimension_sizes[dimension_id] for dimension_id in variable.dims[1:]
        )
        for issue in measurement_value_contract_issues(
            value,
            expected_dtype=variable.dtype,
            expected_unit=variable.unit,
            expected_shape=expected_shape,
        ):
            problems.append(
                _record_contract_problem(
                    record=record,
                    variable_id=variable_id,
                    field_name=field_name,
                    issue=issue,
                )
            )
    return problems


def _record_contract_problem(
    *,
    record: MeasurementRecord,
    variable_id: str,
    field_name: str,
    issue: MeasurementValueContractIssue,
) -> Problem:
    if issue.code is MeasurementValueContractIssueCode.DTYPE_MISMATCH:
        code = "measurement_record_dtype_mismatch"
        dimension = "dtype"
    elif issue.code is MeasurementValueContractIssueCode.UNIT_MISMATCH:
        code = "measurement_record_unit_mismatch"
        dimension = "unit"
    elif issue.code is MeasurementValueContractIssueCode.SHAPE_MISMATCH:
        code = "measurement_record_shape_mismatch"
        dimension = "shape"
    else:
        code = "measurement_record_value_invalid"
        dimension = "value"
    return _problem(
        code,
        f"measurement record {record.point_index} variable {variable_id} has "
        f"incompatible {dimension} {issue.actual!r}, expected {issue.expected!r}",
        (
            "records",
            record.point_index,
            field_name,
            variable_id,
            *issue.path,
        ),
    )


def _problem(
    code: str,
    message: str,
    path: tuple[str | int, ...],
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.ANALYSIS,
        location=model_location("measurement_dataset", *path),
    )
