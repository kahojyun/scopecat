"""Durable intent and evidence records for externally relevant effects.

The journal records host-controlled effect transitions and the identities and
hashes needed for crash containment. Pure computation and best-effort progress
do not become ledger facts merely because they can be observed at runtime.
Provider payload contents and private configuration are evidence artifacts,
not fields to copy into journal transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scopecat.kernel.content_identity import (
    content_fingerprint,
    stable_content_hash,
)
from scopecat.kernel.problems import Problem

type ExecutionEffect = Literal[
    "read",
    "state_write",
    "acquisition",
    "lifecycle",
    "persistence",
]
type JournalEntryState = Literal[
    "started",
    "completed",
    "failed",
    "unknown",
]
type ExecutionStage = Literal[
    "provide_instruments",
    "setup_cleanup",
    "setup_close",
    "setup_terminal_readback",
    "point",
    "compute",
    "apply_state",
    "collect",
    "initialize_measurement",
    "append_measurement",
    "seal_measurement",
    "abort",
    "cleanup",
    "close",
    "terminal_readback",
    "domain_submit",
    "domain_fetch",
]


class ExecutionTransition(BaseModel):
    """Immutable transition committed to the execution journal."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    sequence: int | None = Field(default=None, ge=0)
    run_id: str
    operation_id: str
    stage: ExecutionStage
    effect: ExecutionEffect
    state: JournalEntryState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    point_index: int | None = Field(default=None, ge=0)
    instrument_id: str | None = None
    problems: tuple[Problem, ...] = ()
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


def execution_transition_identity(
    transition: ExecutionTransition,
) -> dict[str, JsonValue]:
    """Return transport identity without daemon-assigned journal fields."""

    return cast(
        "dict[str, JsonValue]",
        transition.model_dump(
            mode="json",
            exclude={"sequence", "timestamp"},
        ),
    )


def execution_transition_content_hash(transition: ExecutionTransition) -> str:
    """Hash one transition without daemon-assigned journal fields."""

    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.execution_transition.v1",
                "transition": execution_transition_identity(transition),
            }
        )
    )
