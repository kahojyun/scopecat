"""Pure structural contracts for point-local measurement values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementDType,
    MeasurementRecord,
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

    Persisted dtype tags must match exactly because this layer does not convert
    the stored value. Available values already match their own dtype tag because
    their models normalize at the construction boundary.
    """

    selected_shape = tuple(expected_shape)
    issues: list[MeasurementValueContractIssue] = []
    actual_dtype = _measurement_value_dtype(value)
    if expected_dtype != actual_dtype:
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

    return tuple(issues)


def _shape_compatible(
    expected: tuple[int | None, ...],
    actual: tuple[int | None, ...],
) -> bool:
    """Match rank exactly while treating an expected variable extent as a wildcard."""

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
) -> tuple[int | None, ...]:
    if isinstance(value, MeasurementArray | MeasurementUnavailable):
        return tuple(value.shape)
    return ()


def _unit_compatible(expected: str | None, actual: str | None) -> bool:
    """Require exact persisted units because this layer never converts values."""

    return expected == actual


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
    else:
        code = "measurement_record_shape_mismatch"
        dimension = "shape"
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
