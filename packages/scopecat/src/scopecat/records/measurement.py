"""Measurement record models shared by execution and analysis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records._metadata import JsonMetadata
from scopecat.records._schema_utils import (
    ensure_unique_ids,
    missing_references,
    validate_shape_rank,
    validate_supported_unit,
)

MEASUREMENT_RECORD_SCHEMA_VERSION = "scopecat.measurement_record.v1"
MEASUREMENT_DATASET_FORMAT_VERSION = "scopecat.measurement_dataset_schema.v1"

MeasurementVariableRole = Literal["coordinate", "observable"]
MeasurementDType = Literal["float64", "int64", "complex128", "bool", "string"]
MeasurementArrayData = Sequence[object]


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
    model_config = ConfigDict(extra="forbid", frozen=True)

    real: float
    imag: float
    unit: str

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        validated = validate_supported_unit(value)
        assert validated is not None
        return validated


def _restore_measurement_array_leaves(
    value: object,
    *,
    dtype: object,
) -> object:
    if isinstance(value, list | tuple):
        selected = cast("list[object] | tuple[object, ...]", value)
        return tuple(
            _restore_measurement_array_leaves(item, dtype=dtype) for item in selected
        )
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
    model_config = ConfigDict(extra="forbid", frozen=True)

    dtype: MeasurementDType = "float64"
    unit: str | None = None
    shape: Sequence[int] = Field(min_length=1)
    values: MeasurementArrayData
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @field_validator("shape")
    @classmethod
    def freeze_shape(cls, value: Sequence[int]) -> Sequence[int]:
        return tuple(value)

    @field_validator("values")
    @classmethod
    def restore_and_freeze_values(
        cls,
        value: MeasurementArrayData,
        info: ValidationInfo,
    ) -> MeasurementArrayData:
        """Restore typed leaves and freeze nested sequences in one pass."""

        dtype = info.data.get("dtype")
        return cast(
            "MeasurementArrayData",
            _restore_measurement_array_leaves(
                value,
                dtype=dtype if isinstance(dtype, str) else "float64",
            ),
        )

    @model_validator(mode="after")
    def validate_values_shape(self) -> MeasurementArray:
        actual_shape = _array_shape(self.values)
        if actual_shape != self.shape:
            msg = f"measurement array shape {actual_shape} does not match {self.shape}"
            raise ValueError(msg)
        return self


type MeasurementValue = Quantity | ComplexQuantity | MeasurementArray
type CoordinateValue = Quantity | EntityRef | str | int | float | bool


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


def _array_shape(values: object) -> tuple[int, ...]:
    if not isinstance(values, tuple):
        return ()
    items = cast("tuple[object, ...]", values)
    if not items:
        return (0,)
    first_shape = _array_shape(items[0])
    for value in items[1:]:
        if _array_shape(value) != first_shape:
            msg = "measurement array values must be rectangular"
            raise ValueError(msg)
    return (len(items), *first_shape)
