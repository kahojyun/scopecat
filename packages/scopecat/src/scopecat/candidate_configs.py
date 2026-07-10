"""Candidate configuration resolution from durable parameter proposals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scopecat._manifest_updates import write_manifest_records_locked
from scopecat._parameter_resolution import validate_parameter_snapshot
from scopecat._parameter_updates import merge_candidate_parameter_snapshots
from scopecat._storage.refs import record_content_ref
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.ids import artifact_slug
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot, config_content_hash
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.parameter_changes import (
    is_safe_parameter_change_id,
    write_parameter_change_proposal_contents_locked,
)
from scopecat.runs.access import open_run_store

type CandidateConfigInput = CandidateConfig | ResolvedCandidateConfig
type CandidateSelection = str | Sequence[str] | None


@dataclass(frozen=True)
class CandidateConfig:
    analysis_title: str
    analysis_key: str
    parameter_proposals: tuple[ParameterChangeProposal, ...]

    @property
    def source_run_id(self) -> str:
        run_ids = {proposal.source_run_id for proposal in self.parameter_proposals}
        if len(run_ids) != 1:
            msg = "candidate config proposals must all come from one source run"
            raise ValueError(msg)
        return next(iter(run_ids))

    @property
    def base_config_content_hash(self) -> str:
        hashes = {
            proposal.base_config_content_hash for proposal in self.parameter_proposals
        }
        if len(hashes) != 1:
            msg = "candidate config proposals must share one base config"
            raise ValueError(msg)
        return next(iter(hashes))

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        return tuple(proposal.id for proposal in self.parameter_proposals)


@dataclass(frozen=True)
class ResolvedCandidateConfig:
    candidate: CandidateConfig
    config: ConfigProfileSnapshot
    proposal_records: tuple[RunRecordEntry, ...]
    candidate_config_record: RunRecordEntry

    @property
    def candidate_config_record_id(self) -> str:
        return self.candidate_config_record.id


def resolve_candidate_config(
    candidate: CandidateConfigInput,
    *,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    if isinstance(candidate, CandidateConfig):
        return _resolve_candidate_config(candidate, workspace=workspace)
    return candidate


def _build_candidate_config_snapshot(
    *,
    config: ConfigProfileSnapshot,
    candidate: CandidateConfig,
    candidate_id: str,
) -> ConfigProfileSnapshot:
    actual_hash = config_content_hash(config)
    if actual_hash != candidate.base_config_content_hash:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="parameter_change_proposal_base_mismatch",
                    message=(
                        "parameter change proposal was derived from a different "
                        "source config snapshot"
                    ),
                    path="candidate.parameter_proposals",
                )
            ]
        )
    base_ids = {proposal.base_config_id for proposal in candidate.parameter_proposals}
    if base_ids != {config.id}:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="parameter_change_proposal_base_id_mismatch",
                    message="parameter change proposal base config id is stale",
                    path="candidate.parameter_proposals",
                )
            ]
        )
    try:
        parameter_snapshot = merge_candidate_parameter_snapshots(
            base=config.parameter_snapshot,
            candidates=tuple(
                (proposal.candidate_snapshot, proposal.deltas)
                for proposal in candidate.parameter_proposals
            ),
            candidate_id=f"{candidate_id}.parameters",
        )
    except ValueError as error:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="parameter_change_proposal_merge_invalid",
                    message=f"parameter change proposals cannot be merged: {error}",
                    path="candidate.parameter_proposals",
                )
            ]
        ) from error
    diagnostics = validate_parameter_snapshot(
        config.parameter_catalog,
        parameter_snapshot,
    )
    if diagnostics:
        raise ValidationFailed(list(diagnostics))
    return ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python")
        | {
            "id": candidate_id,
            "parameter_snapshot": parameter_snapshot,
        }
    )


def _resolve_candidate_config(
    candidate: CandidateConfig,
    *,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    _validate_candidate(candidate)
    storage = open_run_store(workspace)
    source_config = storage.read_config_profile_snapshot(candidate.source_run_id)
    candidate_id = _candidate_config_id(candidate)
    candidate_record_id = f"{candidate_id}-candidate-config"
    candidate_config = _build_candidate_config_snapshot(
        config=source_config,
        candidate=candidate,
        candidate_id=candidate_id,
    )
    candidate_record = RunRecordEntry(
        id=candidate_record_id,
        kind="candidate_config",
        media_type="application/json",
    )
    candidate_ref = record_content_ref(
        record_id=candidate_record.id,
        kind=candidate_record.kind,
    )
    candidate_path = storage.ref_path(candidate.source_run_id, candidate_ref)
    with storage.run_lock(candidate.source_run_id):
        proposal_records = write_parameter_change_proposal_contents_locked(
            storage=storage,
            run_id=candidate.source_run_id,
            proposals=candidate.parameter_proposals,
        )
        if candidate_path.exists() or not storage.write_model_if_absent(
            candidate.source_run_id,
            candidate_ref,
            candidate_config,
        ):
            try:
                existing = storage.read_model(
                    candidate.source_run_id,
                    candidate_ref,
                    ConfigProfileSnapshot,
                )
            except (OSError, ValueError) as error:
                raise ValidationFailed(
                    [
                        Diagnostic(
                            severity="error",
                            code="invalid_candidate_config_record",
                            message=(
                                "candidate config record exists but is invalid: "
                                f"{candidate_record.id}"
                            ),
                            path="candidate_config",
                        )
                    ]
                ) from error
            if existing != candidate_config:
                raise ValidationFailed(
                    [
                        Diagnostic(
                            severity="error",
                            code="candidate_config_record_conflict",
                            message=(
                                "candidate config record is immutable and already "
                                f"contains different content: {candidate_record.id}"
                            ),
                            path="candidate_config",
                        )
                    ]
                )
        write_manifest_records_locked(
            storage=storage,
            run_id=candidate.source_run_id,
            records=[*proposal_records, candidate_record],
        )
    return ResolvedCandidateConfig(
        candidate=candidate,
        config=candidate_config,
        proposal_records=proposal_records,
        candidate_config_record=candidate_record,
    )


def _validate_candidate(candidate: CandidateConfig) -> None:
    if not candidate.parameter_proposals:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="candidate_config_empty",
                    message="candidate config requires at least one proposal",
                    path="candidate",
                )
            ]
        )
    run_ids = {proposal.source_run_id for proposal in candidate.parameter_proposals}
    if len(run_ids) != 1:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="candidate_config_source_run_mismatch",
                    message="candidate config proposals must come from one source run",
                    path="candidate.parameter_proposals",
                )
            ]
        )
    hashes = {
        proposal.base_config_content_hash for proposal in candidate.parameter_proposals
    }
    if len(hashes) != 1:
        raise ValidationFailed(
            [
                Diagnostic(
                    severity="error",
                    code="candidate_config_base_mismatch",
                    message="candidate config proposals must share one base config",
                    path="candidate.parameter_proposals",
                )
            ]
        )
    seen: set[str] = set()
    for proposal in candidate.parameter_proposals:
        if not is_safe_parameter_change_id(proposal.id):
            raise ValidationFailed(
                [
                    Diagnostic(
                        severity="error",
                        code="parameter_change_invalid_id",
                        message=(
                            "parameter change proposal id is not safe for record "
                            f"paths: {proposal.id}"
                        ),
                        path="parameter_change_proposal.id",
                    )
                ]
            )
        if proposal.id in seen:
            raise ValidationFailed(
                [
                    Diagnostic(
                        severity="error",
                        code="candidate_config_duplicate_proposal",
                        message=f"duplicate parameter proposal id: {proposal.id}",
                        path="candidate.parameter_proposals",
                    )
                ]
            )
        seen.add(proposal.id)


def _candidate_config_id(candidate: CandidateConfig) -> str:
    selected = "-".join(
        artifact_slug(proposal.id) for proposal in candidate.parameter_proposals
    )
    return f"candidate-{artifact_slug(candidate.analysis_key)}-{selected}"


__all__ = [
    "CandidateConfig",
    "CandidateConfigInput",
    "CandidateSelection",
    "ResolvedCandidateConfig",
    "resolve_candidate_config",
]
