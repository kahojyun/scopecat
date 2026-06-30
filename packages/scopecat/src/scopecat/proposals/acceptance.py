"""One-step proposal acceptance workflow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryRegistrationJob,
    activate_config_registry_entry,
    register_accepted_parameter_proposal,
)
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.run import utc_now
from scopecat.proposals.application import (
    preflight_parameter_proposal_acceptance,
    write_accepted_parameter_proposal_candidate,
)
from scopecat.proposals.review import (
    ProposalReviewRecord,
    load_parameter_proposal,
    review_parameter_proposal,
)
from scopecat.runs import open_run_store


class ParameterProposalAcceptancePolicyRecord(BaseModel):
    """Durable policy input used to accept a parameter proposal."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    reviewer: str
    operator: str
    entry_id: str | None = None
    note: str = ""


class ParameterProposalAcceptanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.parameter_proposal_acceptance_result.v2"
    run_id: str
    proposal_id: str
    proposal_artifact_id: str
    review_ref: str
    acceptance_ref: str
    candidate_artifact_id: str
    config_registry_entry_id: str
    active_entry_id: str
    active_config_ref: str
    active_state_ref: str
    activation_record_id: str
    policy: ParameterProposalAcceptancePolicyRecord
    artifact_refs: list[Artifact] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    accepted_at: datetime = Field(default_factory=utc_now)


def accept_parameter_proposal(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    reviewer: str,
    operator: str,
    entry_id: str | None = None,
    note: str = "",
) -> tuple[
    ParameterProposalAcceptanceResult,
    ProposalReviewRecord | None,
    ConfigRegistryRegistrationJob,
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    workspace_path = Path(workspace)
    proposal = load_parameter_proposal(
        run_id=run_id,
        selector=selector,
        workspace=workspace_path,
    )
    if proposal.state == "rejected":
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_not_acceptable",
                    f"proposal {proposal.id} is rejected",
                    "proposal.state",
                )
            ]
        )
    if proposal.state not in {"proposed", "approved"}:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_not_acceptable",
                    f"proposal {proposal.id} cannot be accepted from state "
                    f"{proposal.state}",
                    "proposal.state",
                )
            ]
        )

    preflight_parameter_proposal_acceptance(
        run_id=run_id,
        selector=selector,
        workspace=workspace_path,
    )
    review: ProposalReviewRecord | None = None
    if proposal.state == "proposed":
        _reviewed, review = review_parameter_proposal(
            run_id=run_id,
            selector=selector,
            workspace=workspace_path,
            state="approved",
            reviewer=reviewer,
            note=note,
        )

    candidate = write_accepted_parameter_proposal_candidate(
        run_id=run_id,
        selector=selector,
        workspace=workspace_path,
    )
    selected_entry_id = entry_id or f"{candidate.proposal.id}-{run_id}"
    registration_job, entry = register_accepted_parameter_proposal(
        config=candidate.candidate_config,
        workspace=workspace_path,
        entry_id=selected_entry_id,
        registered_by=operator,
        run_id=run_id,
        proposal_id=candidate.proposal.id,
        proposal_artifact_id=candidate.proposal_artifact_id,
        candidate_artifact_id=candidate.candidate_config_artifact_id,
        note=note,
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry.id,
        workspace=workspace_path,
        operator=operator,
        note=note,
    )
    acceptance_ref = _acceptance_ref(candidate.proposal.id)
    review_ref = f"reviews/{candidate.proposal.id}.review.json"
    result = ParameterProposalAcceptanceResult(
        run_id=run_id,
        proposal_id=candidate.proposal.id,
        proposal_artifact_id=candidate.proposal_artifact_id,
        review_ref=review_ref,
        acceptance_ref=acceptance_ref,
        candidate_artifact_id=candidate.candidate_config_artifact_id,
        config_registry_entry_id=entry.id,
        active_entry_id=active_state.active_entry_id,
        active_config_ref=active_state.active_config_ref,
        active_state_ref="config-registry/active.json",
        activation_record_id=activation.id,
        policy=ParameterProposalAcceptancePolicyRecord(
            selector=selector,
            reviewer=reviewer,
            operator=operator,
            entry_id=entry_id,
            note=note,
        ),
        artifact_refs=_acceptance_artifact_refs(
            proposal_id=candidate.proposal.id,
            proposal_record_ref=candidate.proposal_record_ref,
            review_ref=review_ref,
            candidate_artifact_id=candidate.candidate_config_artifact_id,
            candidate_config_record_ref=candidate.candidate_config_record_ref,
            acceptance_ref=acceptance_ref,
            include_review=(
                review is not None
                or (workspace_path / "runs" / run_id / review_ref).is_file()
            ),
        ),
    )
    _write_acceptance_result(
        workspace_path=workspace_path,
        run_id=run_id,
        result=result,
    )
    return (
        result,
        review,
        registration_job,
        entry,
        active_state,
        activation,
    )


def _write_acceptance_result(
    *,
    workspace_path: Path,
    run_id: str,
    result: ParameterProposalAcceptanceResult,
) -> None:
    storage = open_run_store(workspace_path)
    storage.write_model(run_id, result.acceptance_ref, result)
    manifest = storage.read_manifest(run_id)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[result.artifact_refs[-1]],
    )


def _acceptance_ref(proposal_id: str) -> str:
    return f"artifacts/{proposal_id}.acceptance.json"


def _acceptance_artifact_refs(
    *,
    proposal_id: str,
    proposal_record_ref: str,
    review_ref: str,
    candidate_artifact_id: str,
    candidate_config_record_ref: str,
    acceptance_ref: str,
    include_review: bool,
) -> list[Artifact]:
    artifact_refs = [
        Artifact(
            id=proposal_id,
            kind="parameter_change_set",
            path=proposal_record_ref,
            media_type="application/json",
        ),
        Artifact(
            id=candidate_artifact_id,
            kind="candidate_config",
            path=candidate_config_record_ref,
            media_type="application/json",
        ),
        Artifact(
            id=f"{proposal_id}-acceptance",
            kind="proposal_acceptance_result",
            path=acceptance_ref,
            media_type="application/json",
        ),
    ]
    if include_review:
        artifact_refs.insert(
            1,
            Artifact(
                id=f"{proposal_id}-review",
                kind="proposal_review_record",
                path=review_ref,
                media_type="application/json",
            ),
        )
    return artifact_refs


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
