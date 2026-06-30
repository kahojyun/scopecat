"""Run lifecycle models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import Artifact

RunStatus = Literal[
    "planned",
    "validated",
    "completed",
    "blocked",
    "failed",
]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_event.v0"
    timestamp: datetime = Field(default_factory=utc_now)
    severity: Literal["info", "warning", "error"] = "info"
    event_type: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.run_manifest.v0"
    run_id: str
    created_at: datetime = Field(default_factory=utc_now)
    status: RunStatus
    runner_id: str
    dry_run: bool = False
    workspace_ref: str
    device_ref: str
    experiment_ref: str
    config_profile_snapshot_ref: str
    plan_snapshot_ref: str
    runner_versions: dict[str, str] = Field(default_factory=dict)
    events_ref: str
    artifact_refs: list[Artifact] = Field(default_factory=list)
    finalization_summary: str
