"""Persisted analysis record models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.records._metadata import JsonMetadata

ANALYSIS_RECORD_SCHEMA_VERSION = "scopecat.analysis.v3"

AnalysisRecordOutputKind = Literal[
    "note",
    "table",
    "array",
    "figure",
    "artifact",
    "parameter_change_proposal",
]


class AnalysisRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    kind: Literal["artifact", "dataset", "uri"]
    role: str
    title: str | None = None
    metadata: JsonMetadata | None = None


class AnalysisRecordOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AnalysisRecordOutputKind
    title: str
    content: object
    metadata: JsonMetadata = Field(default_factory=dict)


class AnalysisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.analysis.v3"] = ANALYSIS_RECORD_SCHEMA_VERSION
    run_id: str
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: list[AnalysisRecordInput] = Field(default_factory=list)
    outputs: list[AnalysisRecordOutput]
