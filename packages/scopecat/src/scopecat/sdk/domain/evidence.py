"""Durable evidence for completed domain target calls."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.sdk.domain.invocation import DomainInvocationIntent
from scopecat.sdk.domain.runtime import DomainExecutionReceipt


class CompletedDomainExecutionEvidence(BaseModel):
    """One target call known to have completed before result realization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_compute_node_id: str
    point_ordinals: tuple[int, ...]
    intent: DomainInvocationIntent
    receipt: DomainExecutionReceipt

    @model_validator(mode="after")
    def validate_completed_receipt(self) -> CompletedDomainExecutionEvidence:
        if self.receipt.status != "completed":
            raise ValueError("completed domain evidence requires a completed receipt")
        return self


class DomainExecutionEvidence(BaseModel):
    """Durable completed target calls, separate from host instrument state."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    executions: list[CompletedDomainExecutionEvidence] = Field(min_length=1)


__all__ = [
    "CompletedDomainExecutionEvidence",
    "DomainExecutionEvidence",
]
