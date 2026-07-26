"""Durable outcomes for proposed parameter changes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.run_outcome import utc_now
from scopecat.records.config import ConfigContentHash
from scopecat.records.parameter import StoredParameterValue


class ParameterChangeApprovalRecord(BaseModel):
    """The one immutable operator approval for a parameter proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    proposal_id: str
    actor: str
    note: str = ""
    approved_at: datetime = Field(default_factory=utc_now)

    @field_validator("run_id", "proposal_id", "actor")
    @classmethod
    def validate_non_empty_identity(cls, value: str) -> str:
        if not value.strip():
            msg = "parameter change approval identity fields must be non-empty"
            raise ValueError(msg)
        return value


class ParameterValueDelta(BaseModel):
    """Durable before/after state for one proposed parameter change.

    The source config identifies the authoritative base; ``before`` verifies that
    base while ``after`` is the proposed value used to resolve a candidate.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    parameter_id: str
    before: StoredParameterValue
    after: StoredParameterValue

    @model_validator(mode="after")
    def validate_values(self) -> ParameterValueDelta:
        if not self.parameter_id:
            msg = "parameter delta id must be non-empty"
            raise ValueError(msg)
        if self.before.id != self.parameter_id or self.after.id != self.parameter_id:
            msg = "parameter delta before/after ids must match parameter_id"
            raise ValueError(msg)
        if self.before == self.after:
            msg = f"parameter delta {self.parameter_id!r} must change its value"
            raise ValueError(msg)
        return self


class ParameterChangeProposal(BaseModel):
    """Immutable parameter changes proposed against one source config."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    id: str
    source_run_id: str
    analysis_record_id: str
    base_config_id: str
    base_config_content_hash: ConfigContentHash
    reason: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    deltas: tuple[ParameterValueDelta, ...] = Field(min_length=1)
    proposed_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "id",
        "source_run_id",
        "analysis_record_id",
        "base_config_id",
        "reason",
    )
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            msg = "parameter change proposal string fields must be non-empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_deltas(self) -> ParameterChangeProposal:
        seen: set[str] = set()
        for delta in self.deltas:
            if delta.parameter_id in seen:
                msg = f"duplicate parameter delta: {delta.parameter_id}"
                raise ValueError(msg)
            seen.add(delta.parameter_id)
        return self
