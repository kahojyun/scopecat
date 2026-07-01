"""Measurement record models shared by execution and analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.diagnostics import Diagnostic
from scopecat.models._schema_utils import (
    ensure_unique_ids,
    missing_references,
    validate_shape_rank,
    validate_supported_unit,
)
from scopecat.models.artifact import MeasurementDatasetRole
from scopecat.models.parameter import Quantity
from scopecat.units import compatible_units

MEASUREMENT_RECORD_SCHEMA_VERSION = "scopecat.measurement_record.v0"
MEASUREMENT_DATASET_SCHEMA_VERSION = "scopecat.measurement_dataset_schema.v0"

MeasurementVariableRole = Literal[
    "coordinate",
    "observable",
    "auxiliary",
    "uncertainty",
    "status",
    "mask",
]
MeasurementDType = Literal["float64", "int64", "bool", "string"]


class MeasurementDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    size: int | None = Field(default=None, ge=0)
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    metadata: dict[str, Any] = Field(default_factory=dict)

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
    metadata: dict[str, Any] = Field(default_factory=dict)

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


class MeasurementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MEASUREMENT_RECORD_SCHEMA_VERSION
    run_id: str
    point_index: int
    coordinates: dict[str, Quantity]
    observables: dict[str, Quantity]
    metadata: dict[str, Any] = Field(default_factory=dict)


class MeasurementDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    artifact_id: str
    ref: str | None = None
    dataset_schema: MeasurementDatasetSchema = Field(alias="schema")
    records: list[MeasurementRecord]
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    metadata: dict[str, Any] | None = None,
) -> MeasurementDatasetSchema:
    """Infer the compatible point-table dataset schema for record JSONL data."""

    coordinate_units = _quantity_units(records=records, field_name="coordinates")
    observable_units = _quantity_units(records=records, field_name="observables")
    point_shape = [len(records)]
    variables = [
        _measurement_variable(
            variable_id=variable_id,
            role="coordinate",
            units=units,
            dimension_id=dimension_id,
            shape=point_shape,
        )
        for variable_id, units in coordinate_units.items()
    ] + [
        _measurement_variable(
            variable_id=variable_id,
            role="observable",
            units=units,
            dimension_id=dimension_id,
            shape=point_shape,
        )
        for variable_id, units in observable_units.items()
    ]
    return MeasurementDatasetSchema(
        dataset_id=dataset_id,
        dataset_role=dataset_role,
        record_schema=MEASUREMENT_RECORD_SCHEMA_VERSION,
        dimensions=[
            MeasurementDimension(
                id=dimension_id,
                kind="point",
                label=dimension_label,
                size=len(records),
            )
        ],
        variables=variables,
        primary_coordinates=list(coordinate_units),
        primary_observables=list(observable_units),
        metadata=metadata or {},
    )


def build_measurement_dataset_artifact_metadata(
    *,
    schema: MeasurementDatasetSchema,
    source_step: str | None = None,
    source_artifact_ids: Sequence[str] = (),
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "dataset_role": schema.dataset_role,
        "record_schema": schema.record_schema,
        "dataset_schema": schema.model_dump(mode="json"),
    }
    if source_step is not None:
        metadata["source_step"] = source_step
    if source_artifact_ids:
        metadata["source_artifact_ids"] = list(source_artifact_ids)
    return metadata


def measurement_dataset_artifact_metadata(
    *,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
    records: Sequence[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None = None,
    source_step: str | None = None,
    source_artifact_ids: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = (
        _schema_with_metadata(expected_schema, metadata)
        if expected_schema is not None
        else infer_measurement_dataset_schema(
            dataset_id=dataset_id,
            dataset_role=dataset_role,
            records=records,
            metadata=metadata,
        )
    )
    return build_measurement_dataset_artifact_metadata(
        schema=schema,
        source_step=source_step,
        source_artifact_ids=source_artifact_ids,
    )


def infer_measurement_dataset_artifact_metadata(
    *,
    dataset_id: str,
    dataset_role: MeasurementDatasetRole,
    records: Sequence[MeasurementRecord],
    source_step: str | None = None,
    source_artifact_ids: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return measurement_dataset_artifact_metadata(
        dataset_id=dataset_id,
        dataset_role=dataset_role,
        records=records,
        expected_schema=None,
        source_step=source_step,
        source_artifact_ids=source_artifact_ids,
        metadata=metadata,
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
        if variable.dtype in {"bool", "string"}:
            diagnostics.append(
                _diagnostic(
                    "measurement_dataset_unsupported_dtype",
                    "MeasurementRecord v0 stores Quantity values and does not "
                    f"support {variable.dtype} for {variable.id}",
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
    if len(variable.shape) > 1:
        diagnostics.append(
            _diagnostic(
                "measurement_dataset_unsupported_variable_shape",
                "MeasurementRecord v0 supports scalar JSONL variables over one "
                f"record dimension, got shape {variable.shape} for {variable.id}",
                f"dataset_schema.variables.{variable.id}.shape",
            )
        )
        return diagnostics
    if variable.shape and variable.shape[0] != record_count:
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
    actual: dict[str, Quantity],
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
        quantity = actual.get(variable_id)
        if quantity is None:
            diagnostics.append(
                _diagnostic(
                    missing_code,
                    f"measurement record {record.point_index} is missing "
                    f"{role} {variable_id}",
                    f"records.{record.point_index}.{field_name}.{variable_id}",
                )
            )
            continue
        if variable.unit is not None and not compatible_units(
            variable.unit, quantity.unit
        ):
            diagnostics.append(
                _diagnostic(
                    "measurement_record_unit_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} uses unit {quantity.unit}, expected "
                    f"{variable.unit}-compatible units",
                    f"records.{record.point_index}.{field_name}.{variable_id}.unit",
                )
            )
        if variable.dtype == "int64" and int(quantity.value) != quantity.value:
            diagnostics.append(
                _diagnostic(
                    "measurement_record_dtype_mismatch",
                    f"measurement record {record.point_index} variable "
                    f"{variable_id} must be integer-valued",
                    f"records.{record.point_index}.{field_name}.{variable_id}.value",
                )
            )
    return diagnostics


def _schema_with_metadata(
    schema: MeasurementDatasetSchema, metadata: dict[str, Any] | None
) -> MeasurementDatasetSchema:
    if not metadata:
        return schema
    merged_metadata = {**schema.metadata, **metadata}
    return schema.model_copy(update={"metadata": merged_metadata})


def _diagnostic(code: str, message: str, path: str | None = None) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _quantity_units(
    *,
    records: Sequence[MeasurementRecord],
    field_name: Literal["coordinates", "observables"],
) -> dict[str, tuple[str, ...]]:
    units_by_id: dict[str, list[str]] = {}
    for record in records:
        quantities = getattr(record, field_name)
        for variable_id, quantity in quantities.items():
            units = units_by_id.setdefault(variable_id, [])
            if quantity.unit not in units:
                units.append(quantity.unit)
    return {variable_id: tuple(units) for variable_id, units in units_by_id.items()}


def _measurement_variable(
    *,
    variable_id: str,
    role: Literal["coordinate", "observable"],
    units: tuple[str, ...],
    dimension_id: str,
    shape: list[int],
) -> MeasurementVariable:
    metadata: dict[str, Any] = {}
    unit: str | None = None
    if len(units) == 1:
        unit = units[0]
    elif units:
        metadata["units"] = list(units)
        metadata["unit_policy"] = "per_record"
    return MeasurementVariable(
        id=variable_id,
        role=role,
        dtype="float64",
        unit=unit,
        dims=[dimension_id],
        shape=list(shape),
        metadata=metadata,
    )
