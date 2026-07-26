"""Measurement record models shared by execution and analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.units import compatible_units
from scopecat.records._metadata import JsonMetadata
from scopecat.records._schema_utils import (
    ensure_unique_ids,
    missing_references,
    validate_shape_rank,
    validate_supported_unit,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

MEASUREMENT_RECORD_SCHEMA_VERSION = "scopecat.measurement_record.v1"
MEASUREMENT_DATASET_FORMAT_VERSION = "scopecat.measurement_dataset_schema.v1"
MeasurementDatasetRole = Literal["raw", "derived"]

MeasurementVariableRole = Literal["coordinate", "observable"]
MeasurementDType = Literal["float64", "int64", "complex128", "bool", "string"]
MeasurementArrayData = list[object]


class MeasurementDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    size: int | None = Field(default=None, ge=0)
    unit: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)


class MeasurementVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: MeasurementVariableRole
    dtype: MeasurementDType
    unit: str | None = None
    dims: list[str] = Field(default_factory=list)
    shape: list[int] = Field(default_factory=list)
    label: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @model_validator(mode="after")
    def validate_shape(self) -> MeasurementVariable:
        message = f"measurement variable {self.id} shape length must match dims length"
        validate_shape_rank(
            shape=self.shape,
            dims=self.dims,
            message=message,
        )
        return self


class MeasurementDatasetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal["scopecat.measurement_dataset_schema.v1"] = (
        MEASUREMENT_DATASET_FORMAT_VERSION
    )
    dataset_id: str
    dataset_role: MeasurementDatasetRole
    record_schema: str = MEASUREMENT_RECORD_SCHEMA_VERSION
    dimensions: list[MeasurementDimension] = Field(default_factory=list)
    variables: list[MeasurementVariable] = Field(default_factory=list)
    primary_coordinates: list[str] = Field(default_factory=list)
    primary_observables: list[str] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> MeasurementDatasetSchema:
        dimension_ids = [dimension.id for dimension in self.dimensions]
        ensure_unique_ids(
            dimension_ids,
            "measurement dataset schema dimension ids must be unique",
        )

        variable_ids = [variable.id for variable in self.variables]
        ensure_unique_ids(
            variable_ids,
            "measurement dataset schema variable ids must be unique",
        )

        dimension_id_set = set(dimension_ids)
        variable_by_id = {variable.id: variable for variable in self.variables}
        for variable in self.variables:
            missing_dims = missing_references(variable.dims, dimension_id_set)
            if missing_dims:
                msg = (
                    f"measurement variable {variable.id} references unknown "
                    f"dimensions: {', '.join(missing_dims)}"
                )
                raise ValueError(msg)

        for variable_id in self.primary_coordinates:
            variable = variable_by_id.get(variable_id)
            if variable is None:
                msg = f"primary coordinate {variable_id} is not a variable"
                raise ValueError(msg)
            if variable.role != "coordinate":
                msg = f"primary coordinate {variable_id} must have coordinate role"
                raise ValueError(msg)

        for variable_id in self.primary_observables:
            variable = variable_by_id.get(variable_id)
            if variable is None:
                msg = f"primary observable {variable_id} is not a variable"
                raise ValueError(msg)
            if variable.role != "observable":
                msg = f"primary observable {variable_id} must have observable role"
                raise ValueError(msg)

        return self


class ComplexQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real: float
    imag: float
    unit: str

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        validated = validate_supported_unit(value)
        assert validated is not None  # noqa: S101
        return validated


def _restore_measurement_array_leaves(
    value: object,
    *,
    dtype: object,
) -> object:
    if isinstance(value, list):
        selected = cast("list[object]", value)
        return [
            _restore_measurement_array_leaves(item, dtype=dtype) for item in selected
        ]
    if isinstance(value, Mapping):
        selected_mapping = cast("Mapping[str, object]", value)
        try:
            if dtype == "complex128":
                return ComplexQuantity.model_validate(selected_mapping)
            if dtype in {"float64", "int64"}:
                return Quantity.model_validate(selected_mapping)
        except ValidationError:
            # Keep malformed provider leaves available to the explicit value
            # contract so they become structured provider-contract problems.
            pass
        return selected_mapping
    return value


class MeasurementArray(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dtype: MeasurementDType = "float64"
    unit: str | None = None
    shape: list[int] = Field(min_length=1)
    values: MeasurementArrayData
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def restore_typed_leaves(cls, data: object) -> object:
        """Restore numeric leaf models lost by an ``Any``-typed wire decode."""

        if not isinstance(data, Mapping):
            return data
        selected = dict(cast("Mapping[str, object]", data))
        if "values" in selected:
            selected["values"] = _restore_measurement_array_leaves(
                selected["values"],
                dtype=selected.get("dtype", "float64"),
            )
        return selected

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @model_validator(mode="after")
    def validate_values_shape(self) -> MeasurementArray:
        actual_shape = _array_shape(self.values)
        if actual_shape != self.shape:
            msg = f"measurement array shape {actual_shape} does not match {self.shape}"
            raise ValueError(msg)
        return self


type MeasurementValue = Quantity | ComplexQuantity | MeasurementArray
type CoordinateValue = Quantity | EntityRef | str | int | float | bool | None


class MeasurementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    logical_point_id: str | None = None
    point_index: int
    instrument_ids: list[str] = Field(default_factory=list)
    coordinates: dict[str, CoordinateValue]
    observables: dict[str, MeasurementValue]
    metadata: JsonMetadata = Field(default_factory=dict)


class MeasurementDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_schema: MeasurementDatasetSchema = Field(alias="schema")
    records: list[MeasurementRecord]
    metadata: JsonMetadata = Field(default_factory=dict)


def validate_measurement_records_against_schema(
    records: Sequence[MeasurementRecord],
    schema: MeasurementDatasetSchema,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
) -> list[Problem]:
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
    if schema.dataset_role != dataset_role:
        problems.append(
            _problem(
                "measurement_dataset_role_mismatch",
                f"measurement dataset schema role {schema.dataset_role} "
                f"does not match artifact role {dataset_role}",
                ("dataset_schema", "dataset_role"),
            )
        )
    if schema.record_schema != MEASUREMENT_RECORD_SCHEMA_VERSION:
        problems.append(
            _problem(
                "measurement_record_schema_mismatch",
                f"measurement dataset record_schema {schema.record_schema} "
                f"does not match {MEASUREMENT_RECORD_SCHEMA_VERSION}",
                ("dataset_schema", "record_schema"),
            )
        )

    problems.extend(_validate_dimension_sizes(records=records, schema=schema))
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
    for variable in schema.variables:
        if variable.role == "observable" and variable.dtype in {"bool", "string"}:
            problems.append(
                _problem(
                    "measurement_dataset_unsupported_dtype",
                    "measurement records store numeric scalar or array values "
                    f"and do not support {variable.dtype} for {variable.id}",
                    ("dataset_schema", "variables", variable.id, "dtype"),
                )
            )
        problems.extend(
            _validate_variable_shape(
                variable=variable,
                record_count=len(records),
            )
        )

    for record in records:
        problems.extend(
            _validate_record_variables(
                record=record,
                variables=coordinate_variables,
                actual=record.coordinates,
                role="coordinate",
            )
        )
        problems.extend(
            _validate_record_variables(
                record=record,
                variables=observable_variables,
                actual=record.observables,
                role="observable",
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
    *, records: Sequence[MeasurementRecord], schema: MeasurementDatasetSchema
) -> list[Problem]:
    problems: list[Problem] = []
    for dimension in schema.dimensions:
        if dimension.size is None:
            continue
        if dimension.kind != "point" and dimension.id != "point":
            continue
        if dimension.size != len(records):
            problems.append(
                _problem(
                    "measurement_dataset_record_count_mismatch",
                    f"measurement dataset dimension {dimension.id} size "
                    f"{dimension.size} does not match {len(records)} records",
                    ("dataset_schema", "dimensions", dimension.id, "size"),
                )
            )
    return problems


def _validate_variable_shape(
    *, variable: MeasurementVariable, record_count: int
) -> list[Problem]:
    problems: list[Problem] = []
    if (
        variable.shape
        and variable.dims
        and variable.dims[0] == "point"
        and variable.shape[0] != record_count
    ):
        problems.append(
            _problem(
                "measurement_dataset_variable_shape_mismatch",
                f"measurement variable {variable.id} shape {variable.shape} "
                f"does not match {record_count} records",
                ("dataset_schema", "variables", variable.id, "shape"),
            )
        )
    return problems


def _validate_record_variables(
    *,
    record: MeasurementRecord,
    variables: dict[str, MeasurementVariable],
    actual: Mapping[str, MeasurementValue | CoordinateValue],
    role: Literal["coordinate", "observable"],
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
        value_unit = _measurement_value_unit(value)
        if variable.unit is not None and (
            value_unit is None or not compatible_units(variable.unit, value_unit)
        ):
            problems.append(
                _problem(
                    "measurement_record_unit_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} uses unit {value_unit}, expected "
                    f"{variable.unit}-compatible units",
                    ("records", record.point_index, field_name, variable_id, "unit"),
                )
            )
        value_dtype = _measurement_value_dtype(value)
        if variable.dtype != value_dtype and not _dtype_compatible(
            variable.dtype, value
        ):
            problems.append(
                _problem(
                    "measurement_record_dtype_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} has dtype {value_dtype}, expected "
                    f"{variable.dtype}",
                    ("records", record.point_index, field_name, variable_id),
                )
            )
        expected_shape = _per_record_shape(variable)
        value_shape = _measurement_value_shape(value)
        if value_shape != expected_shape:
            problems.append(
                _problem(
                    "measurement_record_shape_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} has shape {value_shape}, expected "
                    f"{expected_shape}",
                    ("records", record.point_index, field_name, variable_id),
                )
            )
    return problems


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


def _measurement_value_unit(value: MeasurementValue | CoordinateValue) -> str | None:
    if isinstance(value, Quantity | ComplexQuantity | MeasurementArray):
        return value.unit
    return None


def _measurement_value_dtype(
    value: MeasurementValue | CoordinateValue,
) -> MeasurementDType:
    if isinstance(value, MeasurementArray):
        return value.dtype
    if isinstance(value, ComplexQuantity):
        return "complex128"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int64"
    if isinstance(value, str | EntityRef) or value is None:
        return "string"
    return "float64"


def _dtype_compatible(
    dtype: MeasurementDType,
    value: MeasurementValue | CoordinateValue,
) -> bool:
    if dtype == "float64":
        return _measurement_value_dtype(value) == "int64"
    if dtype == "complex128":
        return _measurement_value_dtype(value) in {"float64", "int64"}
    if dtype == "int64" and isinstance(value, Quantity):
        return int(value.value) == value.value
    return False


def _measurement_value_shape(value: MeasurementValue | CoordinateValue) -> list[int]:
    if isinstance(value, MeasurementArray):
        return list(value.shape)
    return []


def _per_record_shape(variable: MeasurementVariable) -> list[int]:
    if variable.dims and variable.dims[0] == "point":
        return list(variable.shape[1:])
    return list(variable.shape)


def _array_shape(values: object) -> list[int]:
    if not isinstance(values, list):
        return []
    items = cast("list[object]", values)
    if not items:
        return [0]
    first_shape = _array_shape(items[0])
    for value in items[1:]:
        if _array_shape(value) != first_shape:
            msg = "measurement array values must be rectangular"
            raise ValueError(msg)
    return [len(items), *first_shape]
