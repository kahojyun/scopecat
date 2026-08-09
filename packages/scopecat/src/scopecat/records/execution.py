"""Structured execution evidence models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.instrument import (
    InstrumentStateSnapshot,
    PropertyTargetIdentity,
    property_target_identity,
)


class InstrumentStateEvidenceSummary(BaseModel):
    """Compact, neutral index of state transitions kept outside datasets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_ids: tuple[str, ...]
    prepared_change_count: int = Field(ge=0)
    final_change_count: int = Field(ge=0)
    prepared_changed_instrument_ids: tuple[str, ...]
    final_changed_instrument_ids: tuple[str, ...]
    missing_final_instrument_ids: tuple[str, ...]


class InstrumentStateEvidence(BaseModel):
    """Durable state evidence across preparation and execution.

    ``observed_state`` is the fresh read after ownership is acquired.
    ``prepared_state`` is the execution baseline after the run policy.
    ``final_state`` is best-effort terminal readback gathered during hardware
    release. It may be incomplete and does not imply a successful run.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    observed_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    prepared_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_preparation_evidence(self) -> InstrumentStateEvidence:
        observed_ids = [state.instrument_id for state in self.observed_state]
        prepared_ids = [state.instrument_id for state in self.prepared_state]
        if observed_ids != prepared_ids:
            raise ValueError(
                "observed and prepared state must identify instruments "
                "in the same order"
            )
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("instrument preparation evidence ids must be unique")
        final_ids = [state.instrument_id for state in self.final_state]
        if len(final_ids) != len(set(final_ids)):
            raise ValueError("instrument final evidence ids must be unique")
        unknown_final_ids = sorted(set(final_ids) - set(observed_ids))
        if unknown_final_ids:
            raise ValueError(
                "final state references instruments absent from preparation: "
                + ", ".join(unknown_final_ids)
            )
        return self


def summarize_instrument_state_evidence(
    evidence: InstrumentStateEvidence,
) -> InstrumentStateEvidenceSummary:
    """Summarize property changes without treating intentional changes as faults."""

    observed = {state.instrument_id: state for state in evidence.observed_state}
    prepared = {state.instrument_id: state for state in evidence.prepared_state}
    final = {state.instrument_id: state for state in evidence.final_state}
    prepared_changes = {
        instrument_id: _changed_property_count(
            observed[instrument_id],
            prepared[instrument_id],
        )
        for instrument_id in observed
    }
    final_changes = {
        instrument_id: _changed_property_count(
            prepared[instrument_id],
            final[instrument_id],
        )
        for instrument_id in final
    }
    instrument_ids = tuple(observed)
    return InstrumentStateEvidenceSummary(
        instrument_ids=instrument_ids,
        prepared_change_count=sum(prepared_changes.values()),
        final_change_count=sum(final_changes.values()),
        prepared_changed_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if prepared_changes[instrument_id]
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
) -> dict[PropertyTargetIdentity, object]:
    return {
        property_target_identity(
            item.interface_id,
            item.component_path,
            item.property_id,
        ): item.value
        for item in state.properties
    }
