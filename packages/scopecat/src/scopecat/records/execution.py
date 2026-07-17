"""Structured execution evidence models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.records.instrument import InstrumentStateSnapshot

INSTRUMENT_STATE_EVIDENCE_SCHEMA_VERSION = "scopecat.instrument_state_evidence.v3"


class InstrumentStateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_state_evidence.v3"] = (
        INSTRUMENT_STATE_EVIDENCE_SCHEMA_VERSION
    )
    run_id: str
    initial_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
