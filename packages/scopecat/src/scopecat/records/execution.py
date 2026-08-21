"""Structured execution evidence models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem
from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    StateMemberIdentity,
    state_member_identity,
)


class DomainJobCheckpoint(BaseModel):
    """Serializable pending state for one submitted target job.

    ``resume_token`` contains the target-owned JSON state needed to advance the
    same job after this boundary. ``progress`` is inspectable evidence only and
    must not be required for resumption. Revisions are strictly monotonic within
    one job and let execution reject stale or replayed transitions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    job_id: str
    revision: int = Field(ge=1)
    resume_token: dict[str, JsonValue]
    progress: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("execution_key", "job_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value:
            raise ValueError("domain job checkpoint identities must be non-empty")
        return value


class DomainExecutionReceipt(BaseModel):
    """Provider outcome evidence for one terminal target job.

    ``completed`` supplies correlated result evidence and proves that the
    realtime call completed. ``not_executed`` proves that realtime execution
    did not begin, even if declared setup work changed state. ``unknown`` means
    hardware may have changed without a correlated completion. Both negative
    statuses carry problems and no result evidence. ``execution_evidence`` is
    target-owned structured context reported with the call outcome. It is not
    host instrument readback and does not imply that the described state can
    be restored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    status: Literal["completed", "not_executed", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    execution_evidence: dict[str, JsonValue] = Field(default_factory=dict)
    problems: tuple[Problem, ...] = ()

    @field_validator("execution_key")
    @classmethod
    def validate_execution_key(cls, value: str) -> str:
        if not value:
            raise ValueError("domain execution receipts require an execution key")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> DomainExecutionReceipt:
        has_result = (
            self.result_fingerprint is not None and self.result_count is not None
        )
        if self.status == "completed":
            if not has_result or not self.result_fingerprint or self.problems:
                raise ValueError(
                    "completed domain receipts require result evidence and no problems"
                )
        elif (
            has_result
            or self.result_fingerprint is not None
            or self.result_count is not None
            or not self.problems
        ):
            raise ValueError(
                "negative domain receipts require problems and no result evidence"
            )
        return self


class DomainJobCheckpointTransition(BaseModel):
    """One pending job boundary that is durable before the next resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["checkpoint"] = "checkpoint"
    checkpoint: DomainJobCheckpoint

    @property
    def execution_key(self) -> str:
        return self.checkpoint.execution_key


class DomainJobTerminalTransition(BaseModel):
    """One terminal provider outcome durable before result realization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["terminal"] = "terminal"
    receipt: DomainExecutionReceipt

    @property
    def execution_key(self) -> str:
        return self.receipt.execution_key


type DomainJobTransitionRecord = Annotated[
    DomainJobCheckpointTransition | DomainJobTerminalTransition,
    Field(discriminator="kind"),
]


class InstrumentStateEvidenceSummary(BaseModel):
    """Compact, neutral index of state transitions kept outside datasets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_ids: tuple[str, ...]
    baseline_change_count: int = Field(ge=0)
    final_change_count: int = Field(ge=0)
    baseline_changed_instrument_ids: tuple[str, ...]
    final_changed_instrument_ids: tuple[str, ...]
    missing_final_instrument_ids: tuple[str, ...]


class InstrumentStateEvidence(BaseModel):
    """Durable state evidence across provisioning and execution.

    ``observed_state`` is the fresh read after ownership is acquired.
    ``baseline_state`` is the execution baseline after the run policy.
    ``final_state`` is best-effort terminal readback gathered during hardware
    release. It may be incomplete and does not imply a successful run.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    observed_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    baseline_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_baseline_evidence(self) -> InstrumentStateEvidence:
        observed_ids = [state.instrument_id for state in self.observed_state]
        baseline_ids = [state.instrument_id for state in self.baseline_state]
        if observed_ids != baseline_ids:
            raise ValueError(
                "observed and baseline state must identify instruments "
                "in the same order"
            )
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("instrument baseline evidence ids must be unique")
        final_ids = [state.instrument_id for state in self.final_state]
        if len(final_ids) != len(set(final_ids)):
            raise ValueError("instrument final evidence ids must be unique")
        unknown_final_ids = sorted(set(final_ids) - set(observed_ids))
        if unknown_final_ids:
            raise ValueError(
                "final state references instruments absent from baseline evidence: "
                + ", ".join(unknown_final_ids)
            )
        return self


def summarize_instrument_state_evidence(
    evidence: InstrumentStateEvidence,
) -> InstrumentStateEvidenceSummary:
    """Summarize property changes without treating intentional changes as faults."""

    observed = {state.instrument_id: state for state in evidence.observed_state}
    baseline = {state.instrument_id: state for state in evidence.baseline_state}
    final = {state.instrument_id: state for state in evidence.final_state}
    baseline_changes = {
        instrument_id: _changed_property_count(
            observed[instrument_id],
            baseline[instrument_id],
        )
        for instrument_id in observed
    }
    final_changes = {
        instrument_id: _changed_property_count(
            baseline[instrument_id],
            final[instrument_id],
        )
        for instrument_id in final
    }
    instrument_ids = tuple(observed)
    return InstrumentStateEvidenceSummary(
        instrument_ids=instrument_ids,
        baseline_change_count=sum(baseline_changes.values()),
        final_change_count=sum(final_changes.values()),
        baseline_changed_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if baseline_changes[instrument_id]
        ),
        final_changed_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if final_changes.get(instrument_id, 0)
        ),
        missing_final_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in final
        ),
    )


def _changed_property_count(
    before: InstrumentStateSnapshot,
    after: InstrumentStateSnapshot,
) -> int:
    before_values = _state_property_values(before)
    after_values = _state_property_values(after)
    return sum(
        before_values.get(identity) != after_values.get(identity)
        for identity in before_values.keys() | after_values.keys()
    )


def _state_property_values(
    state: InstrumentStateSnapshot,
) -> dict[StateMemberIdentity, object]:
    return {
        state_member_identity(item.target): item.value for item in state.observations
    }
