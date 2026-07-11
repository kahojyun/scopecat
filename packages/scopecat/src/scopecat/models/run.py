"""Run lifecycle models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.config import ConfigContentHash

RunStatus = Literal[
    "planned",
    "running",
    "completed",
    "failed",
    "interrupted",
    "unknown",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class RunConfigSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_config_source.v2"] = (
        "scopecat.run_config_source.v2"
    )
    kind: Literal["config_registry"] = "config_registry"
    selector: str
    entry_id: str
    config_ref: str
    content_hash: ConfigContentHash
    registry_generation: int | None = Field(default=None, ge=1)


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.run_manifest.v6"] = "scopecat.run_manifest.v6"
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: RunStatus
    config_source: RunConfigSource | None = None
    records: list[RunRecordEntry] = Field(default_factory=list)
    datasets: list[RunDatasetEntry] = Field(default_factory=list)
    artifacts: list[RunArtifactEntry] = Field(default_factory=list)
