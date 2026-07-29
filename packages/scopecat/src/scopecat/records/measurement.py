"""Measurement record models shared by execution and analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from scopecat.records._metadata import JsonMetadata
from scopecat.records._schema_utils import (
    ensure_unique_ids,
    missing_references,
    validate_supported_unit,
)

MEASUREMENT_RECORD_SCHEMA_VERSION = "scopecat.measurement_record.v3"
MEASUREMENT_DATASET_FORMAT_VERSION = "scopecat.measurement_dataset_schema.v3"

MeasurementVariableRole = Literal["coordinate", "observable"]
MeasurementDType = Literal["float64", "int64", "complex128", "bool", "string"]
MeasurementUnavailableReason = Literal["missing", "invalid", "overload"]
MeasurementArrayData = Sequence[object]


class MeasurementDimension(BaseModel):
    """One concrete extent; physical coordinate values are variables."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str | None = None
    size: int = Field(ge=0)
    metadata: JsonMetadata = Field(default_factory=dict)


class MeasurementVariable(BaseModel):
    """A point-local variable whose shape is derived from its dimensions."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    role: MeasurementVariableRole
    dtype: MeasurementDType
    unit: str | None = None
    dims: list[str] = Field(min_length=1)
    label: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @field_validator("dims")
    @classmethod
    def validate_dims(cls, value: list[str]) -> list[str]:
        ensure_unique_ids(
            value,
            "measurement variable dimensions must be unique",
        )
        if value[0] != "point":
            raise ValueError("measurement variables must use point as first dimension")
        return value

    @model_validator(mode="after")
    def validate_unitless_dtype(self) -> MeasurementVariable:
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} measurement variables cannot have a unit")
        return self


class MeasurementDatasetSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal["scopecat.measurement_dataset_schema.v3"] = (
        MEASUREMENT_DATASET_FORMAT_VERSION
    )
    dataset_id: str = Field(min_length=1)
    record_schema: Literal["scopecat.measurement_record.v3"] = (
        MEASUREMENT_RECORD_SCHEMA_VERSION
    )
    dimensions: list[MeasurementDimension]
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
        namespace_collisions = dimension_id_set & set(variable_by_id)
        if namespace_collisions:
            raise ValueError(
                "measurement dimensions and variables must have distinct ids: "
                + ", ".join(sorted(namespace_collisions))
            )
        point_dimensions = [
            dimension for dimension in self.dimensions if dimension.kind == "point"
        ]
        if len(point_dimensions) != 1 or point_dimensions[0].id != "point":
            raise ValueError(
                "measurement dataset schema must define exactly one point "
                "dimension with id point"
            )

        for variable in self.variables:
            missing_dims = missing_references(variable.dims, dimension_id_set)
            if missing_dims:
                msg = (
                    f"measurement variable {variable.id} references unknown "
                    f"dimensions: {', '.join(missing_dims)}"
                )
                raise ValueError(msg)
        ensure_unique_ids(
            self.primary_coordinates,
            "measurement dataset primary coordinate ids must be unique",
        )
        ensure_unique_ids(
            self.primary_observables,
            "measurement dataset primary observable ids must be unique",
        )

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


class ComplexComponents(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    real: float
    imag: float

    @field_validator("real", "imag", mode="before")
    @classmethod
    def validate_component(cls, value: object) -> float:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError("complex components must be numeric")
        selected = float(value)
        if not math.isfinite(selected):
            raise ValueError("complex components must be finite")
        return selected


type MeasurementScalarData = bool | int | float | str | ComplexComponents


class MeasurementScalar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["scalar"]
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    value: MeasurementScalarData
    metadata: JsonMetadata = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        value: MeasurementScalarData,
        dtype: MeasurementDType = "float64",
        unit: str | None = None,
        metadata: JsonMetadata | None = None,
    ) -> Self:
        """Construct a scalar while keeping the wire discriminator required."""

        return cls(
            kind="scalar",
            dtype=dtype,
            unit=unit,
            value=value,
            metadata={} if metadata is None else metadata,
        )

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @field_validator("value")
    @classmethod
    def validate_finite_value(
        cls,
        value: MeasurementScalarData,
    ) -> MeasurementScalarData:
        _validate_finite_numbers(value)
        return value

    @model_validator(mode="after")
    def validate_unitless_dtype(self) -> MeasurementScalar:
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} measurement scalars cannot have a unit")
        return self


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
                return ComplexComponents.model_validate(selected_mapping)
        except ValidationError:
            pass
        return selected_mapping
    return value


class MeasurementArray(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["array"]
    dtype: MeasurementDType = "float64"
    unit: str | None = None
    shape: Sequence[int] = Field(min_length=1)
    values: MeasurementArrayData
    metadata: JsonMetadata = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        shape: Sequence[int],
        values: MeasurementArrayData,
        dtype: MeasurementDType = "float64",
        unit: str | None = None,
        metadata: JsonMetadata | None = None,
    ) -> Self:
        """Construct an array while keeping the wire discriminator required."""

        return cls(
            kind="array",
            dtype=dtype,
            unit=unit,
            shape=shape,
            values=values,
            metadata={} if metadata is None else metadata,
        )

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

        _validate_finite_numbers(value)
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
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(f"{self.dtype} measurement arrays cannot have a unit")
        return self


class MeasurementUnavailable(BaseModel):
    """A complete scalar or array result with no usable value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["unavailable"]
    reason: MeasurementUnavailableReason
    dtype: MeasurementDType
    unit: str | None
    shape: tuple[Annotated[int, Field(ge=0)], ...]
    metadata: JsonMetadata

    @classmethod
    def create(
        cls,
        *,
        reason: MeasurementUnavailableReason,
        dtype: MeasurementDType,
        unit: str | None,
        shape: Sequence[int],
        metadata: JsonMetadata,
    ) -> Self:
        """Construct an unavailable result with its complete value contract."""

        return cls(
            kind="unavailable",
            reason=reason,
            dtype=dtype,
            unit=unit,
            shape=tuple(shape),
            metadata=metadata,
        )

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @model_validator(mode="after")
    def validate_unitless_dtype(self) -> MeasurementUnavailable:
        if self.dtype in {"bool", "string"} and self.unit is not None:
            raise ValueError(
                f"{self.dtype} unavailable measurements cannot have a unit"
            )
        return self


type MeasurementValue = Annotated[
    MeasurementScalar | MeasurementArray | MeasurementUnavailable,
    Field(discriminator="kind"),
]


class MeasurementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    logical_point_id: str | None = None
    point_index: int
    instrument_ids: list[str] = Field(default_factory=list)
    coordinates: dict[str, MeasurementValue]
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


def _validate_finite_numbers(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("measurement values must be finite")
    if isinstance(value, complex) and not (
        math.isfinite(value.real) and math.isfinite(value.imag)
    ):
        raise ValueError("measurement values must be finite")
    if isinstance(value, ComplexComponents):
        return
    if isinstance(value, Mapping):
        selected_mapping = cast("Mapping[object, object]", value)
        for item in selected_mapping.values():
            _validate_finite_numbers(item)
        return
    if isinstance(value, list | tuple):
        selected_sequence = cast("list[object] | tuple[object, ...]", value)
        for item in selected_sequence:
            _validate_finite_numbers(item)
