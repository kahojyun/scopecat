"""Structured execution evidence models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    StateMemberIdentity,
    state_member_identity,
)


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
