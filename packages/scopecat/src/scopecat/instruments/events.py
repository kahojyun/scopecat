"""Transient runtime event stream models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.artifact import CommandPayload

RuntimeEventKind = Literal[
    "run_started",
    "compute_finished",
    "point_started",
    "point_finished",
    "state_applied",
    "state_reconcile_finished",
    "collect_started",
    "collect_finished",
    "record_emitted",
    "run_finished",
]


class RuntimeEvent(BaseModel):
    """Runtime-observation event.

    Runtime events are transient monitor data. They are intentionally compact
    and should not be treated as durable execution IR.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: RuntimeEventKind
    run_id: str
    experiment_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    point_index: int | None = None
    instrument_id: str | None = None
    progress: dict[str, int] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


RuntimeEventSink = Callable[[RuntimeEvent], None]


@dataclass(frozen=True)
class RuntimePayloadObservation:
    """Transient rich payload observation for monitors and diagnostics.

    Payload observations may contain in-memory Python objects. They are never
    written as run evidence and should be treated as live runtime data.
    """

    run_id: str
    experiment_id: str
    point_index: int | None
    node_id: str | None
    payload_id: str
    schema_id: str
    compute_status: str | None
    payload: CommandPayload
    summary: dict[str, Any]


RuntimePayloadObserver = Callable[[RuntimePayloadObservation], None]


__all__ = [
    "RuntimeEvent",
    "RuntimeEventKind",
    "RuntimeEventSink",
    "RuntimePayloadObservation",
    "RuntimePayloadObserver",
]
