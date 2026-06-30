"""Execution layer models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionProfile(BaseModel):
    """Runner selection and dry-run state for an experiment."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.execution_profile.v0"
    runner_id: str
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
