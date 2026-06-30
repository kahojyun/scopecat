"""Parameter proposal workflow use cases."""

from __future__ import annotations

from pathlib import Path

from scopecat.proposals import accept_parameter_proposal
from scopecat.workflows._types import AcceptProposalWorkflowResult


def accept_proposal(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    reviewer: str,
    operator: str,
    entry_id: str | None = None,
    note: str = "",
) -> AcceptProposalWorkflowResult:
    acceptance, review, registration_job, entry, active_state, activation = (
        accept_parameter_proposal(
            run_id=run_id,
            selector=selector,
            workspace=workspace,
            reviewer=reviewer,
            operator=operator,
            entry_id=entry_id,
            note=note,
        )
    )
    return AcceptProposalWorkflowResult(
        acceptance=acceptance,
        review=review,
        registration_job=registration_job,
        entry=entry,
        active_state=active_state,
        activation=activation,
    )
