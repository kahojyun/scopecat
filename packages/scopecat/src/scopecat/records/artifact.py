"""Run-local payload, dataset, record, and command payload models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat.records._metadata import JsonMetadata


class RunContentEntry(BaseModel):
    """One content-addressable run-local manifest entry."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role: Literal["artifact", "dataset", "record"]
    id: str
    kind: str
    title: str | None = None
    media_type: str | None = None
    filename: str | None = None
    data_schema: dict[str, object] | None = Field(default=None, alias="schema")
    content_hash: str = Field(min_length=1)
    produced_by: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("id", "kind")
    @classmethod
    def validate_storage_segment(cls, value: str) -> str:
        return _validate_run_segment(value)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or "\\" in value:
            raise ValueError("run content filename must be a basename")
        path = PurePosixPath(value)
        if path.name != value or path.is_absolute() or ".." in path.parts:
            raise ValueError("run content filename must be a basename")
        return value


class CommandPayload(BaseModel):
    """Runtime command payload referenced by instrument state commands."""

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_id: str = Field(min_length=1)
    uri: str | None = None
    content_hash: str | None = None
    media_type: str | None = None
    operation_id: str | None = None
    semantic_operation_id: str | None = None
    implementation_id: str | None = None
    point_index: int | None = Field(default=None, ge=0)
    metadata: JsonMetadata = Field(default_factory=dict)
    payload: object | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_location(self) -> CommandPayload:
        if self.uri is None and self.content_hash is None and self.payload is None:
            msg = "command payload requires uri, content_hash, or payload"
            raise ValueError(msg)
        return self


def _validate_run_segment(value: str) -> str:
    if not value or "\\" in value:
        msg = "run-local ref field must be a single path segment"
        raise ValueError(msg)
    path = PurePosixPath(value)
    if path.name != value or path.is_absolute() or ".." in path.parts:
        msg = "run-local ref field must be a single path segment"
        raise ValueError(msg)
    return value
