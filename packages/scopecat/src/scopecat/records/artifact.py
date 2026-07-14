"""Run-local payload, dataset, record, and command payload models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from scopecat.records._metadata import JsonMetadata


class RunArtifactEntry(BaseModel):
    """Run-local user payload or attachment.

    Framework workflow state belongs in ``RunRecordEntry``. Structured datasets
    belong in ``RunDatasetEntry``. ``RunArtifactEntry`` is intentionally limited
    to files a user would naturally browse, download, or attach to analysis.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    title: str | None = None
    media_type: str | None = None
    produced_by: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("id", "kind")
    @classmethod
    def validate_storage_segment(cls, value: str) -> str:
        return _validate_run_segment(value)


class RunDatasetEntry(BaseModel):
    """Run-local structured dataset entry."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    kind: str
    media_type: str | None = None
    role: str | None = None
    data_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    produced_by: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("id", "kind")
    @classmethod
    def validate_storage_segment(cls, value: str) -> str:
        return _validate_run_segment(value)


class RunRecordEntry(BaseModel):
    """Run-local framework/workflow record entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    media_type: str | None = "application/json"

    @field_validator("id", "kind")
    @classmethod
    def validate_storage_segment(cls, value: str) -> str:
        return _validate_run_segment(value)


class CommandPayload(BaseModel):
    """Runtime command payload referenced by instrument state commands.

    Payloads are transient command inputs produced while lowering in-memory
    compute results. ``evidence_ref`` points to durable structural identity
    evidence; it is deliberately distinct from ``uri``, which denotes
    replayable payload content when a domain codec provides one.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_id: str = Field(min_length=1)
    uri: str | None = None
    evidence_ref: str | None = None
    content_hash: str | None = None
    media_type: str | None = None
    operation_id: str | None = None
    semantic_operation_id: str | None = None
    implementation_id: str | None = None
    point_index: int | None = Field(default=None, ge=0)
    compute_status: Literal["evaluated", "reused"] | None = None
    metadata: JsonMetadata = Field(default_factory=dict)
    payload: Any | None = Field(default=None, exclude=True)

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
