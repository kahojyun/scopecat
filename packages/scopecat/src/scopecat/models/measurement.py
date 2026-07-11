"""Measurement record models shared by execution and analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.diagnostics import Diagnostic
from scopecat.models._schema_utils import (
    ensure_unique_ids,
    missing_references,
    validate_shape_rank,
    validate_supported_unit,
)
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.units import compatible_units

MEASUREMENT_RECORD_SCHEMA_VERSION = "scopecat.measurement_record.v0"
MEASUREMENT_DATASET_SCHEMA_VERSION = "scopecat.measurement_dataset_schema.v0"
MeasurementDatasetRole = Literal["raw", "derived"]

MeasurementVariableRole = Literal[
    "coordinate",
    "observable",
    "auxiliary",
    "uncertainty",
    "status",
    "mask",
]
MeasurementDType = Literal["float64", "int64", "complex128", "bool", "string"]
MeasurementArrayData = list[Any]


class MeasurementDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    size: int | None = Field(default=None, ge=0)
    unit: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

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
    uncertainty_of: str | None = None
    status_of: str | None = None
    mask_of: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

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

    schema_version: str = MEASUREMENT_DATASET_SCHEMA_VERSION
    dataset_id: str
    dataset_role: MeasurementDatasetRole
    record_schema: str = MEASUREMENT_RECORD_SCHEMA_VERSION
    dimensions: list[MeasurementDimension] = Field(default_factory=list)
    variables: list[MeasurementVariable] = Field(default_factory=list)
    primary_coordinates: list[str] = Field(default_factory=list)
    primary_observables: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

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
        assert validated is not None
        return validated


class MeasurementArray(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dtype: MeasurementDType = "float64"
    unit: str | None = None
    shape: list[int] = Field(min_length=1)
    values: MeasurementArrayData
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

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

    schema_version: str = MEASUREMENT_RECORD_SCHEMA_VERSION
    run_id: str
    point_index: int
    coordinates: dict[str, CoordinateValue]
    observables: dict[str, MeasurementValue]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class MeasurementDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset_id: str
    dataset_schema: MeasurementDatasetSchema = Field(alias="schema")
    records: list[MeasurementRecord]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class MeasurementDatasetInputDiagnostics:
    missing_code: str
    empty_code: str
    invalid_code: str
    missing_schema_code: str
    invalid_schema_code: str
    noun: str
    diagnostic_path: str | None = None


def infer_measurement_dataset_schema(
    *,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
    records: Sequence[MeasurementRecord],
    dimension_id: str = "point",
    dimension_label: str | None = "Point",
    metadata: Mapping[str, JsonValue] | None = None,
) -> MeasurementDatasetSchema:
    """Infer the compatible point-table dataset schema for record JSONL data."""

    coordinate_values = _values_by_id(records=records, field_name="coordinates")
    observable_values = _values_by_id(records=records, field_name="observables")
    point_shape = [len(records)]
    variables: list[MeasurementVariable] = []
    dimensions = [
        MeasurementDimension(
            id=dimension_id,
            kind="point",
            label=dimension_label,
            size=len(records),
        )
    ]
    for variable_id, values in coordinate_values.items():
        variable, extra_dimensions = _measurement_variable(
            variable_id=variable_id,
            role="coordinate",
            values=values,
            dimension_id=dimension_id,
            shape=point_shape,
        )
        variables.append(variable)
        dimensions.extend(extra_dimensions)
    for variable_id, values in observable_values.items():
        variable, extra_dimensions = _measurement_variable(
            variable_id=variable_id,
            role="observable",
            values=values,
            dimension_id=dimension_id,
            shape=point_shape,
        )
        variables.append(variable)
        dimensions.extend(
            dimension
            for dimension in extra_dimensions
            if dimension.id not in {existing.id for existing in dimensions}
        )
    return MeasurementDatasetSchema(
        dataset_id=dataset_id,
        dataset_role=dataset_role,
        record_schema=MEASUREMENT_RECORD_SCHEMA_VERSION,
        dimensions=dimensions,
        variables=variables,
        primary_coordinates=list(coordinate_values),
        primary_observables=list(observable_values),
        metadata=dict(metadata or {}),
    )


def validate_measurement_records_against_schema(
    records: Sequence[MeasurementRecord],
    schema: MeasurementDatasetSchema,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if schema.dataset_id != dataset_id:
        diagnostics.append(
            _diagnostic(
                "measurement_dataset_id_mismatch",
                f"measurement dataset schema id {schema.dataset_id} "
                f"does not match artifact id {dataset_id}",
                "dataset_schema.dataset_id",
            )
        )
    if schema.dataset_role != dataset_role:
        diagnostics.append(
            _diagnostic(
                "measurement_dataset_role_mismatch",
                f"measurement dataset schema role {schema.dataset_role} "
                f"does not match artifact role {dataset_role}",
                "dataset_schema.dataset_role",
            )
        )
    if schema.record_schema != MEASUREMENT_RECORD_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "measurement_record_schema_mismatch",
                f"measurement dataset record_schema {schema.record_schema} "
                f"does not match {MEASUREMENT_RECORD_SCHEMA_VERSION}",
                "dataset_schema.record_schema",
            )
        )

    diagnostics.extend(_validate_dimension_sizes(records=records, schema=schema))
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
        if variable.role not in {"coordinate", "observable"}:
            diagnostics.append(
                _diagnostic(
                    "measurement_dataset_unsupported_variable_role",
                    "MeasurementRecord v0 supports coordinate and observable "
                    f"variables only, got {variable.role} for {variable.id}",
                    f"dataset_schema.variables.{variable.id}.role",
                )
            )
        if variable.role != "coordinate" and variable.dtype in {"bool", "string"}:
            diagnostics.append(
                _diagnostic(
                    "measurement_dataset_unsupported_dtype",
                    "MeasurementRecord v0 stores numeric scalar or array values "
                    f"and does not support {variable.dtype} for {variable.id}",
                    f"dataset_schema.variables.{variable.id}.dtype",
                )
            )
        diagnostics.extend(
            _validate_variable_shape(
                variable=variable,
                record_count=len(records),
            )
        )

    for record in records:
        diagnostics.extend(
            _validate_record_variables(
                record=record,
                variables=coordinate_variables,
                actual=record.coordinates,
                role="coordinate",
            )
        )
        diagnostics.extend(
            _validate_record_variables(
                record=record,
                variables=observable_variables,
                actual=record.observables,
                role="observable",
            )
        )
        extra_coordinates = set(record.coordinates) - set(coordinate_variables)
        for variable_id in sorted(extra_coordinates):
            diagnostics.append(
                _diagnostic(
                    "measurement_record_unexpected_coordinate",
                    f"measurement record {record.point_index} has unexpected "
                    f"coordinate {variable_id}",
                    f"records.{record.point_index}.coordinates.{variable_id}",
                )
            )
        extra_observables = set(record.observables) - set(observable_variables)
        for variable_id in sorted(extra_observables):
            diagnostics.append(
                _diagnostic(
                    "measurement_record_unexpected_observable",
                    f"measurement record {record.point_index} has unexpected "
                    f"observable {variable_id}",
                    f"records.{record.point_index}.observables.{variable_id}",
                )
            )
    return diagnostics


def _validate_dimension_sizes(
    *, records: Sequence[MeasurementRecord], schema: MeasurementDatasetSchema
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for dimension in schema.dimensions:
        if dimension.size is None:
            continue
        if dimension.kind != "point" and dimension.id != "point":
            continue
        if dimension.size != len(records):
            diagnostics.append(
                _diagnostic(
                    "measurement_dataset_record_count_mismatch",
                    f"measurement dataset dimension {dimension.id} size "
                    f"{dimension.size} does not match {len(records)} records",
                    f"dataset_schema.dimensions.{dimension.id}.size",
                )
            )
    return diagnostics


def _validate_variable_shape(
    *, variable: MeasurementVariable, record_count: int
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if (
        variable.shape
        and variable.dims
        and variable.dims[0] == "point"
        and variable.shape[0] != record_count
    ):
        diagnostics.append(
            _diagnostic(
                "measurement_dataset_variable_shape_mismatch",
                f"measurement variable {variable.id} shape {variable.shape} "
                f"does not match {record_count} records",
                f"dataset_schema.variables.{variable.id}.shape",
            )
        )
    return diagnostics


def _validate_record_variables(
    *,
    record: MeasurementRecord,
    variables: dict[str, MeasurementVariable],
    actual: Mapping[str, MeasurementValue | CoordinateValue],
    role: Literal["coordinate", "observable"],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    field_name = "coordinates" if role == "coordinate" else "observables"
    missing_code = (
        "measurement_record_missing_coordinate"
        if role == "coordinate"
        else "measurement_record_missing_observable"
    )
    for variable_id, variable in variables.items():
        value = actual.get(variable_id)
        if value is None:
            diagnostics.append(
                _diagnostic(
                    missing_code,
                    f"measurement record {record.point_index} is missing "
                    f"{role} {variable_id}",
                    f"records.{record.point_index}.{field_name}.{variable_id}",
                )
            )
            continue
        value_unit = _measurement_value_unit(value)
        if variable.unit is not None and (
            value_unit is None or not compatible_units(variable.unit, value_unit)
        ):
            diagnostics.append(
                _diagnostic(
                    "measurement_record_unit_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} uses unit {value_unit}, expected "
                    f"{variable.unit}-compatible units",
                    f"records.{record.point_index}.{field_name}.{variable_id}.unit",
                )
            )
        value_dtype = _measurement_value_dtype(value)
        if variable.dtype != value_dtype and not _dtype_compatible(
            variable.dtype, value
        ):
            diagnostics.append(
                _diagnostic(
                    "measurement_record_dtype_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} has dtype {value_dtype}, expected "
                    f"{variable.dtype}",
                    f"records.{record.point_index}.{field_name}.{variable_id}",
                )
            )
        expected_shape = _per_record_shape(variable)
        value_shape = _measurement_value_shape(value)
        if value_shape != expected_shape:
            diagnostics.append(
                _diagnostic(
                    "measurement_record_shape_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} has shape {value_shape}, expected "
                    f"{expected_shape}",
                    f"records.{record.point_index}.{field_name}.{variable_id}",
                )
            )
    return diagnostics


def _diagnostic(code: str, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _values_by_id(
    *,
    records: Sequence[MeasurementRecord],
    field_name: Literal["coordinates", "observables"],
) -> dict[str, list[MeasurementValue]]:
    values_by_id: dict[str, list[MeasurementValue]] = {}
    for record in records:
        values = getattr(record, field_name)
        for variable_id, value in values.items():
            values_by_id.setdefault(variable_id, []).append(value)
    return values_by_id


def _measurement_variable(
    *,
    variable_id: str,
    role: Literal["coordinate", "observable"],
    values: Sequence[MeasurementValue],
    dimension_id: str,
    shape: list[int],
) -> tuple[MeasurementVariable, list[MeasurementDimension]]:
    metadata: dict[str, JsonValue] = {}
    units = _measurement_value_units(values)
    unit: str | None = None
    if len(units) == 1:
        unit = units[0]
    elif units:
        metadata["units"] = list(units)
        metadata["unit_policy"] = "per_record"
    dtype = _common_dtype(values)
    value_shape = _common_value_shape(values)
    dimensions: list[MeasurementDimension] = []
    dims = [dimension_id]
    variable_shape = list(shape)
    if role == "observable" and value_shape:
        for index, size in enumerate(value_shape):
            array_dimension_id = f"{variable_id}_dim_{index}"
            dims.append(array_dimension_id)
            variable_shape.append(size)
            dimensions.append(
                MeasurementDimension(
                    id=array_dimension_id,
                    kind="array",
                    size=size,
                )
            )
    return MeasurementVariable(
        id=variable_id,
        role=role,
        dtype=dtype,
        unit=unit,
        dims=dims,
        shape=variable_shape,
        metadata=metadata,
    ), dimensions


def _measurement_value_units(values: Sequence[MeasurementValue]) -> tuple[str, ...]:
    units: list[str] = []
    for value in values:
        unit = _measurement_value_unit(value)
        if unit is not None and unit not in units:
            units.append(unit)
    return tuple(units)


def _measurement_value_unit(value: MeasurementValue | CoordinateValue) -> str | None:
    if isinstance(value, Quantity | ComplexQuantity | MeasurementArray):
        return value.unit
    return None


def _common_dtype(values: Sequence[MeasurementValue]) -> MeasurementDType:
    dtypes: list[MeasurementDType] = []
    for value in values:
        dtype = _measurement_value_dtype(value)
        if dtype not in dtypes:
            dtypes.append(dtype)
    if dtypes == ["int64"]:
        return "int64"
    if "complex128" in dtypes:
        return "complex128"
    if all(dtype in {"float64", "int64"} for dtype in dtypes):
        return "float64"
    return dtypes[0] if dtypes else "float64"


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


def _common_value_shape(values: Sequence[MeasurementValue]) -> list[int]:
    shapes: list[list[int]] = []
    for value in values:
        shape = _measurement_value_shape(value)
        if shape not in shapes:
            shapes.append(shape)
    return shapes[0] if len(shapes) == 1 else []


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
    items = cast(list[object], values)
    if not items:
        return [0]
    first_shape = _array_shape(items[0])
    for value in items[1:]:
        if _array_shape(value) != first_shape:
            msg = "measurement array values must be rectangular"
            raise ValueError(msg)
    return [len(items), *first_shape]
