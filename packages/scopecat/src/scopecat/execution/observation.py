"""Transient, typed observation contracts for live run monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import JsonValue

from scopecat.records.artifact import CommandPayload
from scopecat.records.execution_journal import (
    ExecutionEffect,
    ExecutionStage,
    JournalEntryState,
)
from scopecat.records.run import RunCertainty, RunResult


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeProgress:
    completed_points: int
    total_points: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _RuntimeEvent:
    run_id: str
    experiment_id: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class RunStartedEvent(_RuntimeEvent):
    """Live notification emitted after a run becomes durably active."""

    progress: RuntimeProgress
    instrument_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    kind: Literal["run_started"] = field(default="run_started", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeTransitionEvent(_RuntimeEvent):
    """Lossy observation of one transient or durably committed transition.

    ``sequence`` is present only when the source transition belongs to the
    durable effect ledger.
    """

    occurred_at: datetime
    operation_id: str
    stage: ExecutionStage
    effect: ExecutionEffect
    state: JournalEntryState
    progress: RuntimeProgress
    sequence: int | None = None
    point_index: int | None = None
    point_indices: tuple[int, ...] = ()
    instrument_id: str | None = None
    metrics: dict[str, JsonValue] = field(default_factory=dict)
    kind: Literal["transition"] = field(default="transition", init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunFinishedEvent(_RuntimeEvent):
    """Live notification emitted only after the terminal outcome commits."""

    progress: RuntimeProgress
    result: RunResult
    certainty: RunCertainty
    measurement_count: int
    problem_count: int
    compute_evaluated_node_count: int
    compute_payload_count: int
    kind: Literal["run_finished"] = field(default="run_finished", init=False)


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
    payload: CommandPayload
    summary: dict[str, JsonValue]


RuntimePayloadObserver = Callable[[RuntimePayloadObservation], None]
