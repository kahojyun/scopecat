"""Candidate configuration resolution from parameter proposals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.application.services import WorkspaceServices
from scopecat.config.changes import is_safe_parameter_change_id
from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.config.parameter_updates import merge_parameter_change_deltas
from scopecat.kernel.errors import CheckFailed, Conflict
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter_change import ParameterChangeProposal

type CandidateSelection = str | Sequence[str] | None


@dataclass(frozen=True)
class CandidateConfig:
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


def resolve_candidate_config_snapshot(
    candidate: CandidateConfig,
    *,
    services: WorkspaceServices,
) -> ConfigProfileSnapshot:
    """Resolve a candidate into a config snapshot without writing run state."""

    _validate_candidate(candidate)
    source_config = services.runs.read_config_profile_snapshot(candidate.source_run_id)
    return resolve_candidate_config_from_snapshot(
        candidate,
        source_config=source_config,
    )


def resolve_candidate_config_from_snapshot(
    candidate: CandidateConfig,
    *,
    source_config: ConfigProfileSnapshot,
) -> ConfigProfileSnapshot:
    """Resolve a candidate against its known source snapshot."""

    _validate_candidate(candidate)
    return _build_candidate_config_snapshot(
        config=source_config,
        candidate=candidate,
        candidate_id=_candidate_config_id(candidate),
    )


def _build_candidate_config_snapshot(
    *,
    config: ConfigProfileSnapshot,
    candidate: CandidateConfig,
    candidate_id: str,
) -> ConfigProfileSnapshot:
    actual_hash = config_content_hash(config)
    if actual_hash != candidate.base_config_content_hash:
        raise Conflict(
            [
                _candidate_problem(
                    "parameter_change_proposal_base_mismatch",
                    "parameter change proposal was derived from a different "
                    "source config snapshot",
                    category=ProblemCategory.CONFLICT,
                    location=model_location("candidate_config", "parameter_proposals"),
                    details={
                        "expected_content_hash": candidate.base_config_content_hash,
                        "actual_content_hash": actual_hash,
                    },
                )
            ]
        )
    base_ids = {proposal.base_config_id for proposal in candidate.parameter_proposals}
    if base_ids != {config.id}:
        raise Conflict(
            [
                _candidate_problem(
                    "parameter_change_proposal_base_id_mismatch",
                    "parameter change proposal base config id is stale",
                    category=ProblemCategory.CONFLICT,
                    location=model_location("candidate_config", "parameter_proposals"),
                    details={
                        "expected_config_id": config.id,
                        "proposal_config_ids": sorted(base_ids),
                    },
                )
            ]
        )
    try:
        parameter_snapshot = merge_parameter_change_deltas(
            base=config.parameter_snapshot,
            proposals=tuple(
                proposal.deltas for proposal in candidate.parameter_proposals
            ),
            candidate_id=f"{candidate_id}.parameters",
        )
    except ValueError as error:
        raise CheckFailed(
            [
                _candidate_problem(
                    "parameter_change_proposal_merge_invalid",
                    f"parameter change proposals cannot be merged: {error}",
                    category=ProblemCategory.INVALID_INPUT,
                    location=model_location("candidate_config", "parameter_proposals"),
                )
            ]
        ) from error
    problems = validate_parameter_snapshot(
        config.parameter_catalog,
        parameter_snapshot,
    )
    if problems:
        raise CheckFailed(problems)
    return config.model_copy(
        update={
            "id": candidate_id,
            "parameter_snapshot": parameter_snapshot,
        },
        deep=True,
    )


def _validate_candidate(candidate: CandidateConfig) -> None:
    if not candidate.parameter_proposals:
        raise CheckFailed(
            [
                _candidate_problem(
                    "candidate_config_empty",
                    "candidate config requires at least one proposal",
                    category=ProblemCategory.INVALID_INPUT,
                    location=model_location("candidate_config"),
                )
            ]
        )
    run_ids = {proposal.source_run_id for proposal in candidate.parameter_proposals}
    if len(run_ids) != 1:
        raise CheckFailed(
            [
                _candidate_problem(
                    "candidate_config_source_run_mismatch",
                    "candidate config proposals must come from one source run",
                    category=ProblemCategory.INVALID_INPUT,
                    location=model_location("candidate_config", "parameter_proposals"),
                    details={"source_run_ids": sorted(run_ids)},
                )
            ]
        )
    hashes = {
        proposal.base_config_content_hash for proposal in candidate.parameter_proposals
    }
    if len(hashes) != 1:
        raise CheckFailed(
            [
                _candidate_problem(
                    "candidate_config_base_mismatch",
                    "candidate config proposals must share one base config",
                    category=ProblemCategory.INVALID_INPUT,
                    location=model_location("candidate_config", "parameter_proposals"),
                    details={"base_content_hashes": sorted(hashes)},
                )
            ]
        )
    seen: set[str] = set()
    for proposal in candidate.parameter_proposals:
        if not is_safe_parameter_change_id(proposal.id):
            raise CheckFailed(
                [
                    _candidate_problem(
                        "parameter_change_invalid_id",
                        "parameter change proposal id is not safe for record paths",
                        category=ProblemCategory.INVALID_INPUT,
                        location=model_location("parameter_change_proposal", "id"),
                        details={"proposal_id": proposal.id},
                    )
                ]
            )
        if proposal.id in seen:
            raise CheckFailed(
                [
                    _candidate_problem(
                        "candidate_config_duplicate_proposal",
                        "candidate config contains a duplicate parameter proposal",
                        category=ProblemCategory.INVALID_INPUT,
                        location=model_location(
                            "candidate_config", "parameter_proposals"
                        ),
                        details={"proposal_id": proposal.id},
                    )
                ]
            )
        seen.add(proposal.id)


def _candidate_config_id(candidate: CandidateConfig) -> str:
    selected = "-".join(
        artifact_slug(proposal.id) for proposal in candidate.parameter_proposals
    )
    return f"candidate-{selected}"


def _candidate_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory,
    location: ProblemLocation,
    phase: ProblemPhase = ProblemPhase.CONFIGURATION,
    details: dict[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=phase,
        location=location,
        details=details,
    )
