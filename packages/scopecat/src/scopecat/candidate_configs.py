"""Candidate configuration resolution from durable parameter proposals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scopecat._manifest_updates import write_manifest_records_locked
from scopecat._parameter_resolution import validate_parameter_snapshot
from scopecat._parameter_updates import merge_candidate_parameter_snapshots
from scopecat._storage.refs import record_content_ref
from scopecat.errors import CheckFailed, Conflict, DataIntegrityError
from scopecat.ids import artifact_slug
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot, config_content_hash
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.parameter_changes import (
    is_safe_parameter_change_id,
    write_parameter_change_proposal_contents_locked,
)
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
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


def resolve_candidate_config_snapshot(
    candidate: CandidateConfigInput,
    *,
    workspace: str | Path,
) -> ConfigProfileSnapshot:
    """Resolve a candidate into a config snapshot without writing run state."""

    if isinstance(candidate, ResolvedCandidateConfig):
        return candidate.config
    _validate_candidate(candidate)
    source_config = open_run_store(workspace).read_config_profile_snapshot(
        candidate.source_run_id
    )
    return _build_candidate_config_snapshot(
        config=source_config,
        candidate=candidate,
        candidate_id=_candidate_config_id(candidate),
    )


def materialize_candidate_config(
    candidate: CandidateConfigInput,
    *,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    """Resolve a candidate and durably record its proposals and merged config."""

    if isinstance(candidate, ResolvedCandidateConfig):
        return candidate
    candidate_config = resolve_candidate_config_snapshot(
        candidate,
        workspace=workspace,
    )
    return _materialize_candidate_config(
        candidate,
        config=candidate_config,
        workspace=workspace,
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
        parameter_snapshot = merge_candidate_parameter_snapshots(
            base=config.parameter_snapshot,
            candidates=tuple(
                (proposal.candidate_snapshot, proposal.deltas)
                for proposal in candidate.parameter_proposals
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
    return ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python")
        | {
            "id": candidate_id,
            "parameter_snapshot": parameter_snapshot,
        }
    )


def _materialize_candidate_config(
    candidate: CandidateConfig,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
) -> ResolvedCandidateConfig:
    storage = open_run_store(workspace)
    candidate_id = _candidate_config_id(candidate)
    candidate_record_id = f"{candidate_id}-candidate-config"
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
            config,
        ):
            try:
                existing = storage.read_model(
                    candidate.source_run_id,
                    candidate_ref,
                    ConfigProfileSnapshot,
                )
            except DataIntegrityError as error:
                raise DataIntegrityError(
                    [
                        _candidate_problem(
                            "invalid_candidate_config_record",
                            "candidate config record exists but is invalid",
                            category=ProblemCategory.DATA_INTEGRITY,
                            phase=ProblemPhase.PERSISTENCE,
                            location=StorageLocation(
                                run_id=candidate.source_run_id,
                                ref=candidate_ref,
                            ),
                            details={"record_id": candidate_record.id},
                        )
                    ]
                ) from error
            if existing != config:
                raise Conflict(
                    [
                        _candidate_problem(
                            "candidate_config_record_conflict",
                            "candidate config record is immutable and already "
                            "contains different content",
                            category=ProblemCategory.CONFLICT,
                            phase=ProblemPhase.PERSISTENCE,
                            location=StorageLocation(
                                run_id=candidate.source_run_id,
                                ref=candidate_ref,
                            ),
                            details={"record_id": candidate_record.id},
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
        config=config,
        proposal_records=proposal_records,
        candidate_config_record=candidate_record,
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
    return f"candidate-{artifact_slug(candidate.analysis_key)}-{selected}"


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


__all__ = [
    "CandidateConfig",
    "CandidateConfigInput",
    "CandidateSelection",
    "ResolvedCandidateConfig",
    "materialize_candidate_config",
    "resolve_candidate_config_snapshot",
]
