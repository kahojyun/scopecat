"""Durable evidence for domain target execution attempts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.sdk.domain.invocation import DomainInvocationIntent
from scopecat.sdk.domain.runtime import DomainExecutionReceipt


class DomainExecutionAttemptEvidence(BaseModel):
    """One host-started target call and any valid receipt it produced.

    A missing receipt means the runtime raised, cancellation interrupted it, or
    its returned evidence was invalid. The run outcome retains the correlated
    problem; no provider status is inferred here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_compute_node_id: str
    point_ordinals: tuple[int, ...]
    execution_key: str
    intent: DomainInvocationIntent
    receipt: DomainExecutionReceipt | None = None

    @model_validator(mode="after")
    def validate_correlated_receipt(self) -> DomainExecutionAttemptEvidence:
        if (
            self.receipt is not None
            and self.receipt.execution_key != self.execution_key
        ):
            raise ValueError("domain attempt receipt belongs to another execution")
        return self


class DomainExecutionEvidence(BaseModel):
    """Durable target attempts, separate from host instrument state."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    attempts: list[DomainExecutionAttemptEvidence] = Field(min_length=1)


__all__ = [
    "DomainExecutionAttemptEvidence",
    "DomainExecutionEvidence",
]
