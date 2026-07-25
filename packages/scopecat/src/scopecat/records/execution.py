"""Structured execution evidence models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from scopecat.records.instrument import InstrumentStateSnapshot


class InstrumentStateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    initial_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
