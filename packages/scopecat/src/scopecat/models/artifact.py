"""Artifact reference models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
