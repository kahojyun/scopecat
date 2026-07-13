"""Transient, typed observation contracts for live run monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scopecat._execution.journal import (
    ExecutionEffect,
    ExecutionStage,
    JournalEntryState,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.run import RunCertainty, RunResult


class RuntimeProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_points: int = Field(ge=0)
    total_points: int = Field(ge=0)


class _RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    experiment_id: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunStartedEvent(_RuntimeEvent):
    """Live notification emitted after a run becomes durably active."""

    kind: Literal["run_started"] = "run_started"
    progress: RuntimeProgress
    instrument_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()


class RuntimeTransitionEvent(_RuntimeEvent):
    """Lossy observation of one transient or durably committed transition.

    ``sequence`` is present only when the source transition belongs to the
    durable effect ledger.
    """

    kind: Literal["transition"] = "transition"
    sequence: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    operation_id: str
    stage: ExecutionStage
    effect: ExecutionEffect
    state: JournalEntryState
    point_index: int | None = Field(default=None, ge=0)
    instrument_id: str | None = None
    progress: RuntimeProgress
    metrics: dict[str, JsonValue] = Field(default_factory=dict)


class RunFinishedEvent(_RuntimeEvent):
    """Live notification emitted only after the terminal manifest commits."""

    kind: Literal["run_finished"] = "run_finished"
    progress: RuntimeProgress
    result: RunResult
    certainty: RunCertainty
    termination_reason: str
    measurement_count: int = Field(ge=0)
    problem_count: int = Field(ge=0)
    compute_evaluated_node_count: int = Field(ge=0)
    compute_reused_node_count: int = Field(ge=0)
    compute_payload_count: int = Field(ge=0)


type RuntimeEvent = RunStartedEvent | RuntimeTransitionEvent | RunFinishedEvent
RuntimeEventSink = Callable[[RuntimeEvent], None]


@dataclass(frozen=True)
class RuntimePayloadObservation:
    """Opt-in live observation that may contain an in-memory Python payload."""

    run_id: str
    experiment_id: str
    point_index: int | None
    semantic_operation_id: str | None
    payload_id: str
    schema_id: str
    compute_status: str | None
    payload: CommandPayload
    summary: dict[str, JsonValue]


RuntimePayloadObserver = Callable[[RuntimePayloadObservation], None]


__all__ = [
    "RunFinishedEvent",
    "RunStartedEvent",
    "RuntimeEvent",
    "RuntimeEventSink",
    "RuntimePayloadObservation",
    "RuntimePayloadObserver",
    "RuntimeProgress",
    "RuntimeTransitionEvent",
]
