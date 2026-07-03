"""Run execution snapshots."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentStateSnapshot,
)

EXECUTION_SNAPSHOT_SCHEMA_VERSION = "scopecat.execution_snapshot.v1"


class ExecutionPointSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_index: int
    changed_field_count: int
    acquired_record_count: int


class ExecutionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EXECUTION_SNAPSHOT_SCHEMA_VERSION
    run_id: str
    experiment_id: str
    status: str
    instrument_ids: list[str]
    descriptions: list[InstrumentDescription] = Field(default_factory=list)
    initial_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    point_count: int
    measurement_count: int
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    points: list[ExecutionPointSnapshot] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
