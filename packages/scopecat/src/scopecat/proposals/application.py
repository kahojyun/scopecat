"""Accepted parameter proposal candidate generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import (
    ConfigProfileSnapshot,
    ConfigProfileSnapshotSource,
)
from scopecat.models.parameter import ParameterChangeSet
from scopecat.parameters import apply_parameter_patches, build_parameter_snapshot
from scopecat.runs import RunStore, list_artifacts, open_run_store

CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"
SAFE_PROPOSAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class PreparedAcceptedParameterProposal:
    candidate_config: ConfigProfileSnapshot
    proposal: ParameterChangeSet
    proposal_artifact_id: str
    proposal_record_ref: str
    candidate_config_artifact_id: str
    candidate_config_record_ref: str


def write_accepted_parameter_proposal_candidate(
    *, run_id: str, selector: str, workspace: str | Path
) -> PreparedAcceptedParameterProposal:
    prepared = _prepare_accepted_parameter_candidate(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        allow_proposed=False,
    )
    storage = open_run_store(workspace)
    _write_prepared_candidate_config(
        storage=storage,
        run_id=run_id,
        prepared=prepared,
    )
    return prepared


def preflight_parameter_proposal_acceptance(
    *, run_id: str, selector: str, workspace: str | Path
) -> None:
    _prepare_accepted_parameter_candidate(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        allow_proposed=True,
    )


def _prepare_accepted_parameter_candidate(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    allow_proposed: bool,
) -> PreparedAcceptedParameterProposal:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    proposal, proposal_artifact = _resolve_candidate_proposal(
        storage=storage,
        run_id=run_id,
        proposal_artifacts=list_artifacts(manifest, kind="parameter_change_set"),
        selector=selector,
    )
    _validate_proposal_for_application(proposal, allow_proposed=allow_proposed)

    config = _read_config(storage=storage, run_id=run_id)
    if config.parameter_build is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_acceptance_parameter_build_not_found",
                    "proposal acceptance config has no parameter build snapshot",
                    "config.parameter_build",
                )
            ]
        )
    candidate_snapshot = _candidate_snapshot(
        config=config,
        proposal=proposal,
        source=ConfigProfileSnapshotSource(
            kind="accepted_parameter_proposal",
            source_run_id=run_id,
            proposal_id=proposal.id,
            proposal_artifact_id=proposal_artifact.id,
        ),
    )
    candidate_config_artifact_id = _candidate_config_artifact_id(proposal.id)
    return PreparedAcceptedParameterProposal(
        candidate_config=candidate_snapshot,
        proposal=proposal,
        proposal_artifact_id=proposal_artifact.id,
        proposal_record_ref=proposal_artifact.path,
        candidate_config_artifact_id=candidate_config_artifact_id,
        candidate_config_record_ref=_candidate_config_record_ref(proposal.id),
    )


def _write_prepared_candidate_config(
    *, storage: RunStore, run_id: str, prepared: PreparedAcceptedParameterProposal
) -> None:
    storage.write_model(
        run_id,
        prepared.candidate_config_record_ref,
        prepared.candidate_config,
    )

    manifest = storage.read_manifest(run_id)
    write_manifest_artifacts(
        storage=storage,
        manifest=manifest,
        artifacts=[
            Artifact(
                id=prepared.candidate_config_artifact_id,
                kind="candidate_config",
                path=prepared.candidate_config_record_ref,
                media_type="application/json",
            ),
        ],
    )


def _candidate_config_record_ref(proposal_id: str) -> str:
    return f"artifacts/{proposal_id}.candidate-config.json"


def _candidate_config_artifact_id(proposal_id: str) -> str:
    return f"{proposal_id}-candidate-config"


def _resolve_candidate_proposal(
    *,
    storage: RunStore,
    run_id: str,
    proposal_artifacts: tuple[Artifact, ...],
    selector: str,
) -> tuple[ParameterChangeSet, Artifact]:
    _validate_selector_path(selector)
    for proposal_artifact in proposal_artifacts:
        proposal = _read_proposal(
            storage=storage,
            run_id=run_id,
            proposal_record_ref=proposal_artifact.path,
        )
        if proposal.id == selector or proposal_artifact.id == selector:
            return proposal, proposal_artifact
    for proposal_artifact in proposal_artifacts:
        if proposal_artifact.path == selector:
            proposal = _read_proposal(
                storage=storage,
                run_id=run_id,
                proposal_record_ref=proposal_artifact.path,
            )
            return proposal, proposal_artifact
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "missing_proposal_acceptance_input",
                f"proposal acceptance input not found: {selector}",
                "proposal",
            )
        ]
    )


def _read_proposal(
    *, storage: RunStore, run_id: str, proposal_record_ref: str
) -> ParameterChangeSet:
    path = storage.ref_path(run_id, proposal_record_ref)
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_proposal_acceptance_input",
                    f"proposal acceptance input is missing: {proposal_record_ref}",
                    proposal_record_ref,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal_acceptance_input",
                    f"proposal acceptance input is a directory: {proposal_record_ref}",
                    proposal_record_ref,
                )
            ]
        )
    try:
        return ParameterChangeSet.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal_acceptance_input",
                    (
                        "proposal acceptance input is not a valid proposal: "
                        f"{proposal_record_ref}"
                    ),
                    proposal_record_ref,
                )
            ]
        ) from error


def _validate_proposal_for_application(
    proposal: ParameterChangeSet, *, allow_proposed: bool
) -> None:
    if not SAFE_PROPOSAL_ID_RE.fullmatch(proposal.id):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_acceptance_invalid_proposal_id",
                    "proposal id is not safe for candidate artifact paths: "
                    f"{proposal.id}",
                    "proposal.id",
                )
            ]
        )
    allowed_states = {"approved", "proposed"} if allow_proposed else {"approved"}
    if proposal.state not in allowed_states:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_not_approved",
                    f"proposal {proposal.id} is {proposal.state}, not approved",
                    "proposal.state",
                )
            ]
        )


def _read_config(*, storage: RunStore, run_id: str) -> ConfigProfileSnapshot:
    path = storage.ref_path(run_id, CONFIG_PROFILE_SNAPSHOT_REF)
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_proposal_acceptance_input",
                    (
                        "proposal acceptance input is missing: "
                        f"{CONFIG_PROFILE_SNAPSHOT_REF}"
                    ),
                    CONFIG_PROFILE_SNAPSHOT_REF,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal_acceptance_input",
                    (
                        "proposal acceptance input is a directory: "
                        f"{CONFIG_PROFILE_SNAPSHOT_REF}"
                    ),
                    CONFIG_PROFILE_SNAPSHOT_REF,
                )
            ]
        )
    try:
        return ConfigProfileSnapshot.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal_acceptance_input",
                    "proposal acceptance input is not a valid config: "
                    f"{CONFIG_PROFILE_SNAPSHOT_REF}",
                    CONFIG_PROFILE_SNAPSHOT_REF,
                )
            ]
        ) from error


def _candidate_snapshot(
    *,
    config: ConfigProfileSnapshot,
    proposal: ParameterChangeSet,
    source: ConfigProfileSnapshotSource,
) -> ConfigProfileSnapshot:
    try:
        parameter_state = apply_parameter_patches(
            catalog=config.parameter_catalog,
            parameter_state=config.parameter_state,
            patches=proposal.patches,
            allow_table_row_changes=True,
        )
    except ValueError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "proposal_acceptance_patch_invalid",
                    f"proposal acceptance patch is invalid: {error}",
                    "proposal.patches",
                )
            ]
        ) from error
    parameter_build = build_parameter_snapshot(
        catalog=config.parameter_catalog,
        parameter_state=parameter_state,
    )
    return ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python")
        | {
            "parameter_state": parameter_state,
            "parameter_build": parameter_build,
            "source": source,
        }
    )


def _validate_selector_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_proposal_acceptance_input",
                    (f"proposal acceptance selector escapes run directory: {value}"),
                    "proposal",
                )
            ]
        )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
