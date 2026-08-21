"""Durable evidence for domain target execution attempts."""

from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.sdk.domain.invocation import DomainInvocationIntent
from scopecat.sdk.domain.runtime import DomainExecutionReceipt, DomainJobCheckpoint


class DomainExecutionAttemptEvidence(BaseModel):
    """One host-started target job and the transitions it produced.

    Checkpoints retain valid correlated pending transitions observed while the
    job was advanced. A missing receipt means the runtime raised, cancellation
    interrupted it, or its returned evidence was invalid. The run outcome
    retains the correlated problem; no provider status is inferred here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_compute_node_id: str
    point_ordinals: tuple[int, ...]
    execution_key: str
    intent: DomainInvocationIntent
    checkpoints: tuple[DomainJobCheckpoint, ...] = ()
    receipt: DomainExecutionReceipt | None = None

    @model_validator(mode="after")
    def validate_correlated_receipt(self) -> DomainExecutionAttemptEvidence:
        if any(
            checkpoint.execution_key != self.execution_key
            for checkpoint in self.checkpoints
        ):
            raise ValueError("domain attempt checkpoint belongs to another execution")
        if self.checkpoints:
            job_ids = {checkpoint.job_id for checkpoint in self.checkpoints}
            revisions = tuple(checkpoint.revision for checkpoint in self.checkpoints)
            if len(job_ids) != 1:
                raise ValueError("domain attempt checkpoints changed job identity")
            if any(later <= earlier for earlier, later in pairwise(revisions)):
                raise ValueError(
                    "domain attempt checkpoint revisions must strictly increase"
                )
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
