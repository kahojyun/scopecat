"""Structured execution evidence models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import Problem
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.run import RunOutcome, RunStatus

EXECUTION_SUMMARY_SCHEMA_VERSION = "scopecat.execution_summary.v2"
INSTRUMENT_STATE_EVIDENCE_SCHEMA_VERSION = "scopecat.instrument_state_evidence.v3"


class StateExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    payload_count: int = 0


class ComputeExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluated_node_count: int = 0
    reused_node_count: int = 0
    payload_count: int = 0


class ExecutionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.execution_summary.v2"] = (
        EXECUTION_SUMMARY_SCHEMA_VERSION
    )
    run_id: str
    experiment_id: str
    outcome: RunOutcome
    point_count: int = Field(ge=0)
    completed_point_count: int = Field(ge=0)
    measurement_count: int = Field(ge=0)
    instrument_ids: list[str]
    problem_count: int = Field(ge=0)
    problems: tuple[Problem, ...] = ()
    state: StateExecutionSummary = Field(default_factory=StateExecutionSummary)
    compute: ComputeExecutionSummary = Field(default_factory=ComputeExecutionSummary)

    @model_validator(mode="after")
    def validate_outcome_projection(self) -> ExecutionSummary:
        if self.outcome.run_id != self.run_id:
            msg = "execution summary outcome belongs to a different run"
            raise ValueError(msg)
        if self.problem_count != len(self.problems):
            msg = "execution summary problem_count does not match problems"
            raise ValueError(msg)
        if self.problems != self.outcome.problems:
            msg = "execution summary problems must project the durable outcome"
            raise ValueError(msg)
        if self.completed_point_count > self.point_count:
            msg = "completed point count exceeds planned point count"
            raise ValueError(msg)
        return self

    @property
    def status(self) -> RunStatus:
        return self.outcome.status


class InstrumentStateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.instrument_state_evidence.v3"] = (
        INSTRUMENT_STATE_EVIDENCE_SCHEMA_VERSION
    )
    run_id: str
    initial_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)


__all__ = [
    "ComputeExecutionSummary",
    "ExecutionSummary",
    "InstrumentStateEvidence",
    "StateExecutionSummary",
]
