"""Typed small data table and array artifact models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.diagnostics import Diagnostic
from scopecat.models._schema_utils import (
    array_shape,
    declared_shape_for_dims,
    ensure_unique_ids,
    missing_references,
    validate_array_dtype,
    validate_scalar_dtype,
    validate_shape_rank,
    validate_supported_unit,
)

DATA_TABLE_SCHEMA_VERSION = "scopecat.data_table_schema.v0"
DATA_TABLE_ARTIFACT_SCHEMA_VERSION = "scopecat.data_table.v0"
DATA_ARRAY_SCHEMA_VERSION = "scopecat.data_array_schema.v0"
DATA_ARRAY_ARTIFACT_SCHEMA_VERSION = "scopecat.data_array.v0"
CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION = "scopecat.chunked_artifact_manifest.v1"

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
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        return validate_supported_unit(value)


class DataTableSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = DATA_TABLE_SCHEMA_VERSION
    columns: list[DataColumn]
    primary_key: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

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

    schema_version: str = DATA_TABLE_ARTIFACT_SCHEMA_VERSION
    data_schema: DataTableSchema = Field(alias="schema")
    rows: list[dict[str, Any]]

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
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    metadata: dict[str, Any] = Field(default_factory=dict)

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

    schema_version: str = DATA_ARRAY_SCHEMA_VERSION
    dimensions: list[DataArrayDimension]
    variables: list[DataArrayVariable]
    primary_variables: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

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

    schema_version: str = DATA_ARRAY_ARTIFACT_SCHEMA_VERSION
    data_schema: DataArraySchema = Field(alias="schema")
    variables: dict[str, Any]

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


class ArtifactChunk(BaseModel):
    """One ordered payload fragment for a larger data artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_ref: str
    index: int
    values: list[Any] = Field(default_factory=list)
    final: bool = False


class ChunkedArtifactManifest(BaseModel):
    """Completion report for a chunked data artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.chunked_artifact_manifest.v1"] = (
        CHUNKED_ARTIFACT_MANIFEST_SCHEMA_VERSION
    )
    artifact_ref: str
    chunks: list[ArtifactChunk] = Field(default_factory=list)
    value_count: int = 0
    complete: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ArtifactRequirement(BaseModel):
    """Artifact slot required or accepted before downstream analysis."""

    model_config = ConfigDict(extra="forbid")

    label: str
    required: bool = True


class PointArtifactStatus(BaseModel):
    """Artifact eligibility for one logical point."""

    model_config = ConfigDict(extra="forbid")

    point_id: int
    available: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    missing_optional: list[str] = Field(default_factory=list)
    eligible: bool


class ArtifactAvailabilityReport(BaseModel):
    """Point eligibility report based on required artifact refs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.artifact_availability_report.v1"] = (
        "scopecat.artifact_availability_report.v1"
    )
    points: list[PointArtifactStatus] = Field(default_factory=list)
    eligible_point_ids: list[int] = Field(default_factory=list)
    partial_point_ids: list[int] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def assemble_chunked_artifact(
    artifact_ref: str,
    chunks: Sequence[ArtifactChunk],
    *,
    expected_chunks: int | None = None,
) -> ChunkedArtifactManifest:
    if expected_chunks is not None and expected_chunks <= 0:
        msg = "expected_chunks must be positive"
        raise ValueError(msg)

    diagnostics: list[Diagnostic] = []
    by_index: dict[int, ArtifactChunk] = {}
    for chunk in chunks:
        if chunk.artifact_ref != artifact_ref:
            diagnostics.append(
                _diagnostic(
                    "chunk_artifact_mismatch",
                    f"chunk {chunk.index} belongs to {chunk.artifact_ref!r}",
                    f"chunks.{chunk.index}.artifact_ref",
                )
            )
            continue
        if chunk.index < 0:
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_chunk",
                    f"chunk index {chunk.index} is negative",
                    f"chunks.{chunk.index}.index",
                )
            )
            continue
        if chunk.index in by_index:
            diagnostics.append(
                _diagnostic(
                    "duplicate_artifact_chunk",
                    f"duplicate chunk index {chunk.index}",
                    f"chunks.{chunk.index}.index",
                )
            )
            continue
        by_index[chunk.index] = chunk

    ordered = [chunk for _, chunk in sorted(by_index.items())]
    expected = expected_chunks
    if expected is None:
        final_chunks = [chunk for chunk in ordered if chunk.final]
        if len(final_chunks) == 1:
            expected = final_chunks[0].index + 1
        elif len(final_chunks) > 1:
            diagnostics.append(
                _diagnostic(
                    "multiple_final_artifact_chunks",
                    f"artifact {artifact_ref!r} has multiple final chunks",
                    "chunks",
                )
            )

    if expected is not None:
        missing = [index for index in range(expected) if index not in by_index]
        if missing:
            diagnostics.append(
                _diagnostic(
                    "missing_artifact_chunks",
                    f"missing chunks {missing!r}",
                    "chunks",
                )
            )

    complete = expected is not None and not diagnostics and len(ordered) == expected
    return ChunkedArtifactManifest(
        artifact_ref=artifact_ref,
        chunks=ordered,
        value_count=sum(len(chunk.values) for chunk in ordered),
        complete=complete,
        diagnostics=diagnostics,
    )


def evaluate_artifact_availability(
    rows: Sequence[Mapping[str, Any]],
    requirements: Sequence[ArtifactRequirement],
    *,
    point_count: int,
) -> ArtifactAvailabilityReport:
    diagnostics: list[Diagnostic] = []
    by_point: dict[int, Mapping[str, Any]] = {}
    for row_index, row in enumerate(rows):
        point_id = row.get("point_id")
        if not isinstance(point_id, int) or isinstance(point_id, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_point",
                    f"row {row_index} has invalid point_id {point_id!r}",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if point_id < 0 or point_id >= point_count:
            diagnostics.append(
                _diagnostic(
                    "invalid_artifact_point",
                    f"row {row_index} point_id {point_id} is out of range",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        if point_id in by_point:
            diagnostics.append(
                _diagnostic(
                    "duplicate_artifact_point",
                    f"row {row_index} repeats point_id {point_id}",
                    f"rows.{row_index}.point_id",
                )
            )
            continue
        by_point[point_id] = row

    point_statuses: list[PointArtifactStatus] = []
    for point_id in range(point_count):
        row = by_point.get(point_id, {})
        available: list[str] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        for requirement in requirements:
            if _has_artifact_ref(row.get(requirement.label)):
                available.append(requirement.label)
            elif requirement.required:
                missing_required.append(requirement.label)
                diagnostics.append(
                    _diagnostic(
                        "missing_required_artifact",
                        (
                            f"point {point_id} is missing required artifact "
                            f"{requirement.label!r}"
                        ),
                        f"points.{point_id}.{requirement.label}",
                    )
                )
            else:
                missing_optional.append(requirement.label)
                diagnostics.append(
                    _diagnostic(
                        "missing_optional_artifact",
                        (
                            f"point {point_id} is missing optional artifact "
                            f"{requirement.label!r}"
                        ),
                        f"points.{point_id}.{requirement.label}",
                    )
                )
        point_statuses.append(
            PointArtifactStatus(
                point_id=point_id,
                available=available,
                missing_required=missing_required,
                missing_optional=missing_optional,
                eligible=not missing_required,
            )
        )

    return ArtifactAvailabilityReport(
        points=point_statuses,
        eligible_point_ids=[
            point.point_id for point in point_statuses if point.eligible
        ],
        partial_point_ids=[
            point.point_id
            for point in point_statuses
            if point.eligible and point.missing_optional
        ],
        diagnostics=diagnostics,
    )


def data_table_artifact_metadata(
    *,
    schema: DataTableSchema,
    source_step: str | None = None,
    source_artifact_ids: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _data_artifact_metadata(
        data_shape="table",
        schema=schema.model_dump(mode="json"),
        source_step=source_step,
        source_artifact_ids=source_artifact_ids,
        metadata=metadata,
    )


def data_array_artifact_metadata(
    *,
    schema: DataArraySchema,
    source_step: str | None = None,
    source_artifact_ids: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _data_artifact_metadata(
        data_shape="array",
        schema=schema.model_dump(mode="json"),
        source_step=source_step,
        source_artifact_ids=source_artifact_ids,
        metadata=metadata,
    )


def _data_artifact_metadata(
    *,
    data_shape: Literal["table", "array"],
    schema: dict[str, Any],
    source_step: str | None,
    source_artifact_ids: Sequence[str],
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    artifact_metadata = dict(metadata or {})
    artifact_metadata.update(
        {
            "data_shape": data_shape,
            "data_schema": schema,
        }
    )
    if source_step is not None:
        artifact_metadata["source_step"] = source_step
    if source_artifact_ids:
        artifact_metadata["source_artifact_ids"] = list(source_artifact_ids)
    return artifact_metadata


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _has_artifact_ref(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    artifact_value = cast("Mapping[str, object]", value)
    artifact_ref = artifact_value.get("artifact_ref")
    return isinstance(artifact_ref, str) and artifact_ref.strip() != ""
