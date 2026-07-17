"""Parameter change proposal inspection and append-only decisions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scopecat.application.services import WorkspaceServices
from scopecat.config.parameter_resolution import validate_parameter_snapshot
from scopecat.config.parameter_updates import (
    ParameterUpdate,
    materialize_parameter_updates,
)
from scopecat.kernel.errors import CheckFailed, Conflict, DataIntegrityError, NotFound
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)
from scopecat.records.artifact import RunRecordEntry
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest, utc_now
from scopecat.runs.access import list_records
from scopecat.runs.manifest import write_manifest_records_locked
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import RunRepository

ParameterChangeReviewState = Literal["approved", "rejected"]
ParameterChangeDecision = Literal["approved", "rejected", "invalidated"]
SAFE_PARAMETER_CHANGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ParameterChangeDecisionRecord(BaseModel):
    """One immutable event in a parameter proposal's review history."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.parameter_change_decision_record.v3"] = (
        "scopecat.parameter_change_decision_record.v3"
    )
    event_id: str
    run_id: str
    proposal_id: str
    decision: ParameterChangeDecision
    actor: str
    note: str = ""
    related_refs: tuple[str, ...] = Field(default_factory=tuple)
    decided_at: datetime = Field(default_factory=utc_now)

    @field_validator("event_id", "run_id", "proposal_id", "actor")
    @classmethod
    def validate_non_empty_identity(cls, value: str) -> str:
        if not value.strip():
            msg = "parameter change decision identity fields must be non-empty"
            raise ValueError(msg)
        return value

    @field_validator("related_refs")
    @classmethod
    def validate_related_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not ref:
                msg = "parameter change decision refs must be non-empty"
                raise ValueError(msg)
            path = PurePosixPath(ref)
            if path.is_absolute() or ".." in path.parts:
                msg = f"parameter change decision ref escapes run directory: {ref}"
                raise ValueError(msg)
        return value


def is_safe_parameter_change_id(value: str) -> bool:
    return SAFE_PARAMETER_CHANGE_ID_RE.fullmatch(value) is not None


def parameter_change_proposal_from_updates(
    *,
    source_run_id: str,
    source_config: ConfigProfileSnapshot,
    analysis_title: str,
    proposal_id: str,
    updates: Sequence[ParameterUpdate],
    reason: str,
    confidence: float | None,
) -> ParameterChangeProposal:
    selected_id = artifact_slug(proposal_id, fallback="analysis")
    if not is_safe_parameter_change_id(selected_id):
        raise CheckFailed(
            [
                _parameter_problem(
                    "parameter_change_invalid_id",
                    "parameter change proposal id is not safe for record paths",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("parameter_change_proposal", "id"),
                    details={"proposal_id": selected_id},
                )
            ]
        )
    selected_reason = reason or (
        f"Parameter change {selected_id!r} from analysis {analysis_title!r}."
    )
    candidate, deltas = materialize_parameter_updates(
        catalog=source_config.parameter_catalog,
        base=source_config.parameter_snapshot,
        updates=updates,
        candidate_id=f"{source_config.parameter_snapshot.id}.candidate.{selected_id}",
    )
    problems = validate_parameter_snapshot(
        source_config.parameter_catalog,
        candidate,
    )
    if problems:
        raise CheckFailed(problems)
    return ParameterChangeProposal(
        id=selected_id,
        source_run_id=source_run_id,
        base_config_id=source_config.id,
        base_config_content_hash=config_content_hash(source_config),
        reason=selected_reason,
        confidence=confidence,
        deltas=deltas,
    )


def load_parameter_change_proposal(
    *, run_id: str, selector: str, services: WorkspaceServices
) -> ParameterChangeProposal:
    storage = services.runs
    proposal, _record = _resolve_proposal_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    return proposal


def review_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: WorkspaceServices,
    state: ParameterChangeReviewState,
    reviewer: str,
    note: str = "",
) -> ParameterChangeDecisionRecord:
    return _record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        services=services,
        decision=state,
        actor=reviewer,
        note=note,
    )


def invalidate_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: WorkspaceServices,
    reason: str,
    invalidated_by: str,
    invalidated_by_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    related_refs = list(invalidated_by_refs or [])
    return _record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        services=services,
        decision="invalidated",
        actor=invalidated_by,
        note=reason,
        related_refs=related_refs,
    )


def _record_parameter_change_decision(
    *,
    run_id: str,
    selector: str,
    services: WorkspaceServices,
    decision: ParameterChangeDecision,
    actor: str,
    note: str = "",
    related_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    with services.config_registry() as work, work.runs.run_lock(run_id):
        storage = work.runs
        proposal, _proposal_record = _resolve_proposal_ref(
            storage=storage,
            run_id=run_id,
            selector=selector,
        )
        if not actor.strip():
            raise CheckFailed(
                [
                    _parameter_problem(
                        "parameter_change_decision_actor_invalid",
                        "parameter change decision actor must be non-empty",
                        category=ProblemCategory.INVALID_INPUT,
                        phase=ProblemPhase.ANALYSIS,
                        location=model_location("parameter_change_decision", "actor"),
                    )
                ]
            )
        for ref in related_refs or ():
            _validate_selector_path(ref)
        event_id = uuid4().hex
        decision_entry = _parameter_change_decision_record_entry(
            proposal_id=proposal.id,
            event_id=event_id,
        )
        record = ParameterChangeDecisionRecord(
            event_id=event_id,
            run_id=run_id,
            proposal_id=proposal.id,
            decision=decision,
            actor=actor,
            note=note,
            related_refs=tuple(related_refs or ()),
        )
        decision_ref = record_content_ref(
            record_id=decision_entry.id,
            kind=decision_entry.kind,
        )
        if not storage.write_model_if_absent(run_id, decision_ref, record):
            raise Conflict(
                [
                    _parameter_problem(
                        "parameter_change_decision_conflict",
                        "parameter change decision event already exists",
                        category=ProblemCategory.CONFLICT,
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(run_id=run_id, ref=decision_ref),
                        details={"event_id": event_id},
                    )
                ]
            )
        write_manifest_records_locked(
            storage=storage,
            run_id=run_id,
            records=[decision_entry],
        )
        return record


def list_parameter_change_decisions(
    *,
    run_id: str,
    selector: str,
    storage: RunRepository,
) -> list[ParameterChangeDecisionRecord]:
    proposal, _record = _resolve_proposal_ref(
        storage=storage,
        run_id=run_id,
        selector=selector,
    )
    selected: list[ParameterChangeDecisionRecord] = []
    for entry in list_records(
        storage.read_manifest(run_id),
        kind="parameter_change_decision_record",
    ):
        try:
            decision = storage.read_model(
                run_id,
                record_content_ref(record_id=entry.id, kind=entry.kind),
                ParameterChangeDecisionRecord,
            )
        except DataIntegrityError as error:
            raise DataIntegrityError(
                [
                    _parameter_problem(
                        "invalid_parameter_change_decision",
                        "parameter change decision record is invalid",
                        category=ProblemCategory.DATA_INTEGRITY,
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(
                            run_id=run_id,
                            ref=record_content_ref(
                                record_id=entry.id,
                                kind=entry.kind,
                            ),
                        ),
                        details={"record_id": entry.id},
                    )
                ]
            ) from error
        expected_entry_id = f"{decision.proposal_id}-decision-{decision.event_id}"
        if decision.run_id != run_id or entry.id != expected_entry_id:
            raise DataIntegrityError(
                [
                    _parameter_problem(
                        "invalid_parameter_change_decision_identity",
                        "parameter change decision identity does not match its "
                        "run record",
                        category=ProblemCategory.DATA_INTEGRITY,
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(
                            run_id=run_id,
                            ref=record_content_ref(
                                record_id=entry.id,
                                kind=entry.kind,
                            ),
                        ),
                        details={
                            "record_id": entry.id,
                            "decision_run_id": decision.run_id,
                            "expected_record_id": expected_entry_id,
                        },
                    )
                ]
            )
        if decision.proposal_id == proposal.id:
            selected.append(decision)
    return selected


def parameter_change_proposal_record_ref(proposal_id: str) -> str:
    return record_content_ref(
        record_id=proposal_id,
        kind="parameter_change_proposal",
    )


def _parameter_change_proposal_record(
    *, proposal: ParameterChangeProposal
) -> RunRecordEntry:
    return RunRecordEntry(
        id=proposal.id,
        kind="parameter_change_proposal",
        media_type="application/json",
    )


def _parameter_change_decision_record_entry(
    *, proposal_id: str, event_id: str
) -> RunRecordEntry:
    return RunRecordEntry(
        id=f"{proposal_id}-decision-{event_id}",
        kind="parameter_change_decision_record",
        media_type="application/json",
    )


def write_parameter_change_proposal_contents_locked(
    *,
    storage: RunRepository,
    run_id: str,
    proposals: Sequence[ParameterChangeProposal],
) -> tuple[RunRecordEntry, ...]:
    """Publish immutable proposal content while the caller holds the run lock."""

    entries = tuple(
        _parameter_change_proposal_record(proposal=proposal) for proposal in proposals
    )
    for proposal, entry in zip(proposals, entries, strict=True):
        if proposal.source_run_id != run_id:
            raise CheckFailed(
                [
                    _parameter_problem(
                        "parameter_change_proposal_source_run_mismatch",
                        "parameter change proposal belongs to a different source run",
                        category=ProblemCategory.INVALID_INPUT,
                        phase=ProblemPhase.PERSISTENCE,
                        location=model_location(
                            "parameter_change_proposal", "source_run_id"
                        ),
                        details={
                            "proposal_id": proposal.id,
                            "proposal_run_id": proposal.source_run_id,
                            "target_run_id": run_id,
                        },
                    )
                ]
            )
        proposal_ref = record_content_ref(record_id=entry.id, kind=entry.kind)
        if not storage.write_model_if_absent(run_id, proposal_ref, proposal):
            existing = _load_proposal_record(
                storage=storage,
                run_id=run_id,
                proposal_record=entry,
            )
            if not _same_parameter_change_proposal(existing, proposal):
                raise Conflict(
                    [
                        _parameter_problem(
                            "parameter_change_proposal_conflict",
                            "parameter change proposal record is immutable and "
                            "already contains different content",
                            category=ProblemCategory.CONFLICT,
                            phase=ProblemPhase.PERSISTENCE,
                            location=StorageLocation(run_id=run_id, ref=proposal_ref),
                            details={"proposal_id": proposal.id},
                        )
                    ]
                )
    return entries


def _same_parameter_change_proposal(
    existing: ParameterChangeProposal,
    candidate: ParameterChangeProposal,
) -> bool:
    """Compare one idempotent proposal intent, preserving its first timestamp.

    A stable proposal ID is the idempotency key for repeatable analysis cells.
    ``proposed_at`` records the first successful publication and therefore does
    not make an otherwise identical retry new content. Every scientific and
    provenance-bearing field remains part of the immutable comparison.
    """

    return existing.model_dump(
        mode="python",
        exclude={"proposed_at"},
    ) == candidate.model_dump(
        mode="python",
        exclude={"proposed_at"},
    )


def _resolve_proposal_ref(
    *, storage: RunRepository, run_id: str, selector: str
) -> tuple[ParameterChangeProposal, RunRecordEntry]:
    manifest = storage.read_manifest(run_id)
    _validate_selector_path(selector)
    for proposal_record in _proposal_records(manifest):
        proposal = _load_proposal_record(
            storage=storage,
            run_id=run_id,
            proposal_record=proposal_record,
        )
        record_ref = record_content_ref(
            record_id=proposal_record.id,
            kind=proposal_record.kind,
        )
        if (
            proposal.id == selector
            or proposal_record.id == selector
            or record_ref == selector
        ):
            return proposal, proposal_record
    raise NotFound(
        [
            _parameter_problem(
                "parameter_change_proposal_not_found",
                "parameter change proposal was not found",
                category=ProblemCategory.NOT_FOUND,
                phase=ProblemPhase.ANALYSIS,
                location=model_location("parameter_change_selector"),
                details={"selector": selector, "run_id": run_id},
            )
        ]
    )


def _load_proposal_record(
    *, storage: RunRepository, run_id: str, proposal_record: RunRecordEntry
) -> ParameterChangeProposal:
    proposal_ref = record_content_ref(
        record_id=proposal_record.id,
        kind=proposal_record.kind,
    )
    if not storage.exists(run_id, proposal_ref):
        raise DataIntegrityError(
            [
                _parameter_problem(
                    "parameter_change_proposal_record_missing",
                    "run manifest references a missing parameter change proposal",
                    category=ProblemCategory.DATA_INTEGRITY,
                    phase=ProblemPhase.PERSISTENCE,
                    location=StorageLocation(run_id=run_id, ref=proposal_ref),
                    details={"record_id": proposal_record.id},
                )
            ]
        )
    try:
        proposal = storage.read_model(
            run_id,
            proposal_ref,
            ParameterChangeProposal,
        )
    except DataIntegrityError as error:
        raise DataIntegrityError(
            [
                _parameter_problem(
                    "invalid_parameter_change_proposal",
                    "parameter change proposal record is invalid",
                    category=ProblemCategory.DATA_INTEGRITY,
                    phase=ProblemPhase.PERSISTENCE,
                    location=StorageLocation(run_id=run_id, ref=proposal_ref),
                    details={"record_id": proposal_record.id},
                )
            ]
        ) from error
    if proposal.id != proposal_record.id or proposal.source_run_id != run_id:
        raise DataIntegrityError(
            [
                _parameter_problem(
                    "invalid_parameter_change_proposal_identity",
                    "parameter change proposal identity does not match its run record",
                    category=ProblemCategory.DATA_INTEGRITY,
                    phase=ProblemPhase.PERSISTENCE,
                    location=StorageLocation(run_id=run_id, ref=proposal_ref),
                    details={
                        "record_id": proposal_record.id,
                        "proposal_id": proposal.id,
                        "proposal_run_id": proposal.source_run_id,
                    },
                )
            ]
        )
    return proposal


def _proposal_records(manifest: RunManifest) -> tuple[RunRecordEntry, ...]:
    return list_records(manifest, kind="parameter_change_proposal")


def _validate_selector_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise CheckFailed(
            [
                _parameter_problem(
                    "parameter_change_path_escape",
                    "parameter change selector escapes the run directory",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("parameter_change_selector"),
                    details={"selector": value},
                )
            ]
        )


def _parameter_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory,
    phase: ProblemPhase,
    location: ProblemLocation,
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
