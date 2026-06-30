"""Local parameter proposal review workflow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.parameter import ParameterChangeSet, Quantity
from scopecat.models.run import RunManifest, utc_now
from scopecat.runs import RunStore, list_artifacts, open_run_store

ProposalReviewState = Literal["approved", "rejected"]


class ParameterProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    state: str
    parameter_id: str
    proposed_value: Quantity | None = None
    source_run_id: str
    path: str


class ProposalReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.proposal_review_record.v1"
    run_id: str
    proposal_id: str
    proposal_artifact_id: str
    decision: ProposalReviewState
    reviewer: str
    note: str = ""
    reviewed_at: datetime = Field(default_factory=utc_now)


class ProposalFinalizationRecord(BaseModel):
    """Durable record for the final state selected during proposal review."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.proposal_finalization_record.v1"
    run_id: str
    proposal_id: str
    proposal_artifact_id: str
    review_ref: str
    final_state: ProposalReviewState
    finalized_by: str
    note: str = ""
    artifact_refs: list[Artifact] = Field(default_factory=list)
    finalized_at: datetime = Field(default_factory=utc_now)


class ProposalInvalidationRecord(BaseModel):
    """Durable record for a proposal made stale outside review."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.proposal_invalidation_record.v1"
    run_id: str
    proposal_id: str
    proposal_artifact_id: str
    reason: str
    invalidated_by: str
    invalidated_by_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[Artifact] = Field(default_factory=list)
    invalidated_at: datetime = Field(default_factory=utc_now)


def list_parameter_proposals(
    *, run_id: str, workspace: str | Path
) -> list[ParameterProposalView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    proposals: list[ParameterProposalView] = []
    for proposal_artifact in _proposal_artifacts(manifest):
        proposal, resolved_ref = _load_ref(
            storage=storage,
            run_id=run_id,
            proposal_record_ref=proposal_artifact.path,
        )
        parameter_id, proposed_value = _view_scalar_update(proposal)
        proposals.append(
            ParameterProposalView(
                id=proposal.id,
                state=proposal.state,
                parameter_id=parameter_id,
                proposed_value=proposed_value,
                source_run_id=proposal.source_run_id,
                path=resolved_ref,
            )
        )
    return proposals


def load_parameter_proposal(
    *, run_id: str, selector: str, workspace: str | Path
) -> ParameterChangeSet:
    storage = open_run_store(workspace)
    _proposal, proposal_artifact = _resolve_proposal_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    proposal, _resolved_ref = _load_ref(
        storage=storage,
        run_id=run_id,
        proposal_record_ref=proposal_artifact.path,
    )
    return proposal


def review_parameter_proposal(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    state: ProposalReviewState,
    reviewer: str,
    note: str = "",
) -> tuple[ParameterChangeSet, ProposalReviewRecord]:
    storage = open_run_store(workspace)
    proposal, proposal_artifact = _resolve_proposal_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    if proposal.state != "proposed":
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_already_reviewed",
                    f"proposal {proposal.id} is already {proposal.state}",
                    "proposal.state",
                )
            ]
        )

    reviewed = proposal.model_copy(update={"state": state})
    record = ProposalReviewRecord(
        run_id=run_id,
        proposal_id=proposal.id,
        proposal_artifact_id=proposal_artifact.id,
        decision=state,
        reviewer=reviewer,
        note=note,
    )
    finalization = ProposalFinalizationRecord(
        run_id=run_id,
        proposal_id=proposal.id,
        proposal_artifact_id=proposal_artifact.id,
        review_ref=_review_ref(proposal.id),
        final_state=state,
        finalized_by=reviewer,
        note=note,
        artifact_refs=_finalization_artifact_refs(
            proposal_id=proposal.id,
            proposal_record_ref=proposal_artifact.path,
        ),
    )
    storage.write_model(run_id, proposal_artifact.path, reviewed)
    storage.write_model(run_id, _review_ref(proposal.id), record)
    storage.write_model(run_id, _finalization_ref(proposal.id), finalization)

    manifest = storage.read_manifest(run_id)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[
            Artifact(
                id=f"{proposal.id}-review",
                kind="proposal_review_record",
                path=_review_ref(proposal.id),
                media_type="application/json",
            ),
            finalization.artifact_refs[-1],
        ],
    )
    return reviewed, record


def invalidate_parameter_proposal(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    reason: str,
    invalidated_by: str,
    invalidated_by_refs: list[str] | None = None,
) -> tuple[ParameterChangeSet, ProposalInvalidationRecord]:
    storage = open_run_store(workspace)
    proposal, proposal_artifact = _resolve_proposal_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    if proposal.state not in {"proposed", "under_review"}:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_not_invalidatable",
                    f"proposal {proposal.id} is {proposal.state}, not invalidatable",
                    "proposal.state",
                )
            ]
        )

    invalidation_refs = list(invalidated_by_refs or [])
    for invalidation_ref in invalidation_refs:
        _validate_selector_path(invalidation_ref)

    invalidated = proposal.model_copy(update={"state": "invalidated"})
    record = ProposalInvalidationRecord(
        run_id=run_id,
        proposal_id=proposal.id,
        proposal_artifact_id=proposal_artifact.id,
        reason=reason,
        invalidated_by=invalidated_by,
        invalidated_by_refs=invalidation_refs,
        artifact_refs=_invalidation_artifact_refs(
            proposal_id=proposal.id,
            proposal_record_ref=proposal_artifact.path,
        ),
    )
    storage.write_model(run_id, proposal_artifact.path, invalidated)
    storage.write_model(run_id, _invalidation_ref(proposal.id), record)

    manifest = storage.read_manifest(run_id)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[record.artifact_refs[-1]],
    )
    return invalidated, record


def unsupported_proposal_state_diagnostic(state: str) -> Diagnostic:
    return _diagnostic(
        "error",
        "unsupported_proposal_state",
        f"unsupported proposal review state {state}",
        "state",
    )


def _resolve_proposal_ref(
    *, storage: RunStore, run_id: str, selector: str
) -> tuple[ParameterChangeSet, Artifact]:
    manifest = storage.read_manifest(run_id)
    _validate_selector_path(selector)
    for proposal_artifact in _proposal_artifacts(manifest):
        proposal, _resolved_ref = _load_ref(
            storage=storage,
            run_id=run_id,
            proposal_record_ref=proposal_artifact.path,
        )
        if proposal.id == selector or proposal_artifact.id == selector:
            return proposal, proposal_artifact
    for proposal_artifact in _proposal_artifacts(manifest):
        if proposal_artifact.path == selector:
            proposal, _resolved_ref = _load_ref(
                storage=storage,
                run_id=run_id,
                proposal_record_ref=proposal_artifact.path,
            )
            return proposal, proposal_artifact
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "proposal_not_found",
                f"proposal not found: {selector}",
                "proposal",
            )
        ]
    )


def _load_ref(
    *, storage: RunStore, run_id: str, proposal_record_ref: str
) -> tuple[ParameterChangeSet, str]:
    path = _proposal_path(
        storage=storage,
        run_id=run_id,
        proposal_record_ref=proposal_record_ref,
    )
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_not_found",
                    f"proposal not found: {proposal_record_ref}",
                    "proposal",
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_is_directory",
                    f"proposal is a directory: {proposal_record_ref}",
                    "proposal",
                )
            ]
        )
    try:
        proposal = ParameterChangeSet.model_validate_json(path.read_text())
        return proposal, proposal_record_ref
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal",
                    "proposal is not a valid parameter change proposal: "
                    f"{proposal_record_ref}",
                    "proposal",
                )
            ]
        ) from error


def _view_scalar_update(proposal: ParameterChangeSet) -> tuple[str, Quantity | None]:
    if len(proposal.patches) != 1:
        return "(multiple)", None
    patch = proposal.patches[0]
    if (
        patch.kind == "set_scalar"
        and patch.parameter_id is not None
        and isinstance(patch.value, Quantity)
    ):
        return patch.parameter_id, patch.value
    return "(table)", None


def _proposal_artifacts(manifest: RunManifest) -> tuple[Artifact, ...]:
    return list_artifacts(manifest, kind="parameter_change_set")


def _proposal_path(*, storage: RunStore, run_id: str, proposal_record_ref: str) -> Path:
    _validate_selector_path(proposal_record_ref)
    return storage.ref_path(run_id, proposal_record_ref)


def _validate_selector_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_path_escape",
                    f"proposal path escapes run directory: {value}",
                    "proposal",
                )
            ]
        )


def _review_ref(proposal_id: str) -> str:
    return f"reviews/{proposal_id}.review.json"


def _finalization_ref(proposal_id: str) -> str:
    return f"reviews/{proposal_id}.finalization.json"


def _invalidation_ref(proposal_id: str) -> str:
    return f"reviews/{proposal_id}.invalidation.json"


def _finalization_artifact_refs(
    *, proposal_id: str, proposal_record_ref: str
) -> list[Artifact]:
    review_ref = _review_ref(proposal_id)
    finalization_ref = _finalization_ref(proposal_id)
    return [
        Artifact(
            id=proposal_id,
            kind="parameter_change_set",
            path=proposal_record_ref,
            media_type="application/json",
        ),
        Artifact(
            id=f"{proposal_id}-review",
            kind="proposal_review_record",
            path=review_ref,
            media_type="application/json",
        ),
        Artifact(
            id=f"{proposal_id}-finalization",
            kind="proposal_finalization_record",
            path=finalization_ref,
            media_type="application/json",
        ),
    ]


def _invalidation_artifact_refs(
    *, proposal_id: str, proposal_record_ref: str
) -> list[Artifact]:
    invalidation_ref = _invalidation_ref(proposal_id)
    return [
        Artifact(
            id=proposal_id,
            kind="parameter_change_set",
            path=proposal_record_ref,
            media_type="application/json",
        ),
        Artifact(
            id=f"{proposal_id}-invalidation",
            kind="proposal_invalidation_record",
            path=invalidation_ref,
            media_type="application/json",
        ),
    ]


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
