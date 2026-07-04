"""Run lifecycle models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry

RunStatus = Literal[
    "completed",
    "failed",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class RunConfigSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_config_source.v1"
    kind: Literal["config_registry"] = "config_registry"
    selector: str
    entry_id: str


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_manifest.v5"
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: RunStatus
    config_source: RunConfigSource | None = None
    records: list[RunRecordEntry] = Field(default_factory=list)
    datasets: list[RunDatasetEntry] = Field(default_factory=list)
    artifacts: list[RunArtifactEntry] = Field(default_factory=list)
