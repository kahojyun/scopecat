"""Lightweight semantic and transport models for derived datasets."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.units import is_supported_unit
from scopecat.records.metadata import JsonMetadata

type DerivedDatasetRole = Literal["coordinate", "observable"]


class DerivedDatasetField(BaseModel):
    """One named Arrow column with the semantics needed outside its library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source_name: str
    arrow_type: str
    nullable: bool
    role: DerivedDatasetRole = "observable"
    unit: str | None = None
    label: str | None = None
    attributes: JsonMetadata = Field(default_factory=dict)

    @field_validator("name", "source_name", "arrow_type")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("derived dataset field text must be non-empty")
        return value

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_unit(value):
            raise ValueError(f"unsupported derived dataset unit: {value}")
        return value


class DerivedDatasetSchema(BaseModel):
    """Versioned semantic schema paired with an exact Arrow IPC schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[DerivedDatasetField, ...]
    layout: Literal["table", "xarray_1d"] = "table"
    dimension: str | None = None
    attributes: JsonMetadata = Field(default_factory=dict)
    schema_id: Literal["scopecat.derived-dataset.v3"] = "scopecat.derived-dataset.v3"

    @field_validator("fields")
    @classmethod
    def validate_fields(
        cls,
        value: tuple[DerivedDatasetField, ...],
    ) -> tuple[DerivedDatasetField, ...]:
        if not value:
            raise ValueError("derived datasets require at least one field")
        names = tuple(field.name for field in value)
        if len(names) != len(set(names)):
            raise ValueError("derived dataset field names must be unique")
        return value

    @model_validator(mode="after")
    def validate_layout(self) -> DerivedDatasetSchema:
        if (self.layout == "xarray_1d") != (self.dimension is not None):
            raise ValueError(
                "xarray derived datasets require exactly one named dimension"
            )
        return self


class DerivedDatasetPayload(BaseModel):
    """Transport payload used while a derived dataset is being published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema: DerivedDatasetSchema
    arrow_ipc_base64: str


__all__ = [
    "DerivedDatasetField",
    "DerivedDatasetPayload",
    "DerivedDatasetRole",
    "DerivedDatasetSchema",
]
