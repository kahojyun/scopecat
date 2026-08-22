"""Bounded terminal evidence for domain target execution."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.sdk.domain.execution import DomainTransitionPolicy


class DomainExecutionEvidence(BaseModel):
    """Compact terminal index of the run's target-job transition ledger.

    Per-job details selected by each transition policy remain in the ordered
    ledger. The terminal record stays bounded by target and policy diversity
    instead of duplicating every job into one large JSON object.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    detail_source: Literal["run_domain_job_transitions"] = "run_domain_job_transitions"
    detail_complete: bool = True
    attempt_count: int = Field(ge=1)
    checkpoint_count: int = Field(ge=0)
    receipt_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    not_executed_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    target_ids: tuple[str, ...] = Field(min_length=1)
    transition_policies: tuple[DomainTransitionPolicy, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> DomainExecutionEvidence:
        if self.receipt_count > self.attempt_count:
            raise ValueError("domain receipts cannot outnumber attempts")
        if (
            self.completed_count + self.not_executed_count + self.unknown_count
            != self.receipt_count
        ):
            raise ValueError("domain receipt status counts must cover every receipt")
        if tuple(sorted(set(self.target_ids))) != self.target_ids:
            raise ValueError("domain target ids must be sorted and unique")
        if tuple(sorted(set(self.transition_policies))) != self.transition_policies:
            raise ValueError("domain transition policies must be sorted and unique")
        return self


__all__ = [
    "DomainExecutionEvidence",
]
