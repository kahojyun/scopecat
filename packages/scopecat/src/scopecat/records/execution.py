"""Structured execution evidence models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.records.instrument import InstrumentStateSnapshot


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
        return self
