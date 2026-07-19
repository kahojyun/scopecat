"""Durable records for externally relevant effects and recovery evidence.

The journal records host-controlled effect transitions and the identities and
hashes needed to reconcile them. Pure computation and best-effort progress do
not become recovery facts merely because they can be observed at runtime.
Provider payload contents and private configuration are evidence artifacts,
not fields to copy into journal transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.kernel.problems import Problem
from scopecat.records.instrument import InstrumentReadback

type ExecutionEffect = Literal[
    "action",
    "pure",
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
    "skipped",
]
type ExecutionStage = Literal[
    "provide_instruments",
    "setup_cleanup",
    "setup_terminal_readback",
    "initial_readback",
    "point",
    "compute",
    "apply_state",
    "action",
    "collect",
    "append_measurement",
    "seal_measurement",
    "abort",
    "cleanup",
    "terminal_readback",
    "domain_submit",
    "domain_fetch",
]


class ExecutionTransition(BaseModel):
    """Immutable carrier shared by effect evidence and live observation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.execution_transition.v3"] = (
        "scopecat.execution_transition.v3"
    )
    sequence: int | None = Field(default=None, ge=0)
    run_id: str
    operation_id: str
    stage: ExecutionStage
    effect: ExecutionEffect
    state: JournalEntryState
    attempt: int = Field(default=1, ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    point_index: int | None = Field(default=None, ge=0)
    instrument_id: str | None = None
    problems: tuple[Problem, ...] = ()
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


ExecutionJournalEntry = ExecutionTransition


class CollectionChunk(BaseModel):
    """Durable payload for one successful driver collection call."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.collection_chunk.v2"] = (
        "scopecat.collection_chunk.v2"
    )
    run_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    command_content_hash: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    point_index: int = Field(ge=0)
    instrument_id: str = Field(min_length=1)
    readback: InstrumentReadback

    @property
    def content_hash(self) -> str:
        return model_wire_content_hash(self)


class CollectionChunkReceipt(BaseModel):
    """Immutable reference to a chunk resolvable by its repository."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    operation_id: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class PayloadEvidence(BaseModel):
    """Durable structural evidence for one transient command payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.payload_evidence.v1"] = (
        "scopecat.payload_evidence.v1"
    )
    run_id: str
    operation_id: str
    point_index: int | None = Field(default=None, ge=0)
    payload_id: str
    schema_id: str
    content_hash: str
    fingerprint: object


class CommittedPayloadEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    content_hash: str
