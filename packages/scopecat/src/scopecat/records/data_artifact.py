"""Typed small data table and array artifact models."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat.records._metadata import JsonMetadata
from scopecat.records._schema_utils import (
    array_shape,
    declared_shape_for_dims,
    ensure_unique_ids,
    missing_references,
    validate_array_dtype,
    validate_scalar_dtype,
    validate_shape_rank,
    validate_supported_unit,
)

DATA_TABLE_FORMAT_VERSION = "scopecat.data_table.v0"
DATA_ARRAY_FORMAT_VERSION = "scopecat.data_array.v0"

DataDType = Literal["float64", "int64", "bool", "string"]
DataVariableRole = Literal[
    "identifier",
    "coordinate",
    "observable",
    "auxiliary",
    "uncertainty",
    "status",
    "mask",
    "metadata",
]


class DataColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: DataVariableRole
    dtype: DataDType
    unit: str | None = None
    label: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)


class DataTableSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[DataColumn]
    primary_key: list[str] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> DataTableSchema:
        column_ids = [column.id for column in self.columns]
        ensure_unique_ids(column_ids, "data table column ids must be unique")
        missing_key_columns = missing_references(self.primary_key, set(column_ids))
        if missing_key_columns:
            msg = (
                "data table primary_key references unknown columns: "
                f"{', '.join(missing_key_columns)}"
            )
            raise ValueError(msg)
        return self


class DataTableArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format_version: Literal["scopecat.data_table.v0"] = DATA_TABLE_FORMAT_VERSION
    data_schema: DataTableSchema = Field(alias="schema")
    rows: list[dict[str, object]]

    @model_validator(mode="after")
    def validate_rows(self) -> DataTableArtifact:
        columns = {column.id: column for column in self.data_schema.columns}
        expected_ids = set(columns)
        for index, row in enumerate(self.rows):
            actual_ids = set(row)
            missing = sorted(expected_ids - actual_ids)
            extra = sorted(actual_ids - expected_ids)
            if missing:
                msg = f"data table row {index} is missing columns: {', '.join(missing)}"
                raise ValueError(msg)
            if extra:
                msg = f"data table row {index} has extra columns: {', '.join(extra)}"
                raise ValueError(msg)
            for column_id, column in columns.items():
                validate_scalar_dtype(
                    row[column_id],
                    column.dtype,
                    f"data table row {index} column {column_id}",
                )
        return self


class DataArrayDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    size: int = Field(ge=0)
    label: str | None = None
    unit: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)


class DataArrayVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: DataVariableRole
    dtype: DataDType
    dims: list[str] = Field(default_factory=list)
    shape: list[int] = Field(default_factory=list)
    unit: str | None = None
    label: str | None = None
    uncertainty_of: str | None = None
    status_of: str | None = None
    mask_of: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)

    @model_validator(mode="after")
    def validate_shape(self) -> DataArrayVariable:
        message = f"data array variable {self.id} shape length must match dims length"
        validate_shape_rank(
            shape=self.shape,
            dims=self.dims,
            message=message,
        )
        return self


class DataArraySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[DataArrayDimension]
    variables: list[DataArrayVariable]
    primary_variables: list[str] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> DataArraySchema:
        dimension_ids = [dimension.id for dimension in self.dimensions]
        ensure_unique_ids(dimension_ids, "data array dimension ids must be unique")
        variable_ids = [variable.id for variable in self.variables]
        ensure_unique_ids(variable_ids, "data array variable ids must be unique")

        dimension_by_id = {dimension.id: dimension for dimension in self.dimensions}
        for variable in self.variables:
            missing_dims = missing_references(variable.dims, set(dimension_by_id))
            if missing_dims:
                msg = (
                    f"data array variable {variable.id} references unknown "
                    f"dimensions: {', '.join(missing_dims)}"
                )
                raise ValueError(msg)
            expected_shape = declared_shape_for_dims(
                dims=variable.dims,
                sizes_by_dimension={
                    dimension_id: dimension.size
                    for dimension_id, dimension in dimension_by_id.items()
                },
            )
            if variable.shape != expected_shape:
                msg = (
                    f"data array variable {variable.id} shape {variable.shape} "
                    f"does not match dimensions {expected_shape}"
                )
                raise ValueError(msg)

        missing_primary = [
            variable_id
            for variable_id in self.primary_variables
            if variable_id not in variable_ids
        ]
        if missing_primary:
            msg = (
                "data array primary_variables reference unknown variables: "
                f"{', '.join(missing_primary)}"
            )
            raise ValueError(msg)
        return self


class DataArrayArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format_version: Literal["scopecat.data_array.v0"] = DATA_ARRAY_FORMAT_VERSION
    data_schema: DataArraySchema = Field(alias="schema")
    variables: dict[str, object]

    @model_validator(mode="after")
    def validate_variables(self) -> DataArrayArtifact:
        schema_variables = {
            variable.id: variable for variable in self.data_schema.variables
        }
        expected_ids = set(schema_variables)
        actual_ids = set(self.variables)
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        if missing:
            msg = f"data array is missing variables: {', '.join(missing)}"
            raise ValueError(msg)
        if extra:
            msg = f"data array has extra variables: {', '.join(extra)}"
            raise ValueError(msg)
        for variable_id, variable in schema_variables.items():
            value = self.variables[variable_id]
            actual_shape = array_shape(value, f"data array variable {variable_id}")
            if actual_shape != variable.shape:
                msg = (
                    f"data array variable {variable_id} shape {actual_shape} "
                    f"does not match declared shape {variable.shape}"
                )
                raise ValueError(msg)
            validate_array_dtype(
                value,
                variable.dtype,
                f"data array variable {variable_id}",
            )
        return self
