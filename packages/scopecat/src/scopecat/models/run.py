"""Run lifecycle models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import Artifact

RunStatus = Literal[
    "completed",
    "failed",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_manifest.v0"
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: RunStatus
    config_profile_snapshot_ref: str
    plan_snapshot_ref: str
    artifact_refs: list[Artifact] = Field(default_factory=list)
