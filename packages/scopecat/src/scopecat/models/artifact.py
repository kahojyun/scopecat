"""Artifact and processing models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.diagnostics import Diagnostic


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    path: str
    media_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    """Content-addressed or storage-backed reference to external data."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    uri: str | None = None
    path: str | None = None
    content_hash: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_location(self) -> ArtifactRef:
        if self.uri is None and self.path is None and self.content_hash is None:
            msg = "artifact ref requires uri, path, or content_hash"
            raise ValueError(msg)
        return self


MeasurementDatasetRole = Literal["raw", "derived"]


class ProcessingJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.processing_job.v1"
    id: str
    run_id: str
    step: str
    input_artifact_ids: list[str]
    input_record_refs: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    output_artifacts: list[Artifact] = Field(default_factory=list)
    status: str = "planned"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
