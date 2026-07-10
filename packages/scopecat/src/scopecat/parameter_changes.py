"""Parameter change proposal inspection and append-only decisions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from scopecat._manifest_updates import write_manifest_records_locked
from scopecat._parameter_resolution import validate_parameter_snapshot
from scopecat._parameter_updates import ParameterUpdate, materialize_parameter_updates
from scopecat._storage.refs import record_content_ref
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.ids import artifact_slug
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.models.run import RunManifest, utc_now
from scopecat.runs import RunStore, list_records, open_run_store

ParameterChangeReviewState = Literal["approved", "rejected"]
ParameterChangeDecision = Literal["approved", "rejected", "invalidated"]
SAFE_PARAMETER_CHANGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ParameterChangeProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_run_id: str
    base_config_id: str
    base_config_content_hash: ConfigContentHash
    reason: str
    confidence: float | None = None
    affected_parameter_ids: list[str] = Field(default_factory=list)
    record_id: str


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

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy through validation so durable decision invariants cannot drift."""

        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


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
        msg = f"parameter change proposal id is not safe: {selected_id}"
        raise ValueError(msg)
    selected_reason = reason or (
        f"Parameter change {selected_id!r} from analysis {analysis_title!r}."
    )
    candidate, deltas = materialize_parameter_updates(
        catalog=source_config.parameter_catalog,
        base=source_config.parameter_snapshot,
        updates=updates,
        candidate_id=f"{source_config.parameter_snapshot.id}.candidate.{selected_id}",
    )
    diagnostics = validate_parameter_snapshot(
        source_config.parameter_catalog,
        candidate,
    )
    if diagnostics:
        raise ValidationFailed(list(diagnostics))
    return ParameterChangeProposal(
        id=selected_id,
        source_run_id=source_run_id,
        base_config_id=source_config.id,
        base_config_content_hash=config_content_hash(source_config),
        reason=selected_reason,
        confidence=confidence,
        candidate_snapshot=candidate,
        deltas=deltas,
    )


def list_parameter_change_proposals(
    *, run_id: str, workspace: str | Path
) -> list[ParameterChangeProposalView]:
    storage = open_run_store(workspace)
    manifest = storage.read_manifest(run_id)
    proposals: list[ParameterChangeProposalView] = []
    for proposal_record in _proposal_records(manifest):
        proposal = _load_proposal_record(
            storage=storage,
            run_id=run_id,
            proposal_record=proposal_record,
        )
        proposals.append(
            ParameterChangeProposalView(
                id=proposal.id,
                source_run_id=proposal.source_run_id,
                base_config_id=proposal.base_config_id,
                base_config_content_hash=proposal.base_config_content_hash,
                reason=proposal.reason,
                confidence=proposal.confidence,
                affected_parameter_ids=[
                    delta.parameter_id for delta in proposal.deltas
                ],
                record_id=proposal_record.id,
            )
        )
    return proposals


def load_parameter_change_proposal(
    *, run_id: str, selector: str, workspace: str | Path
) -> ParameterChangeProposal:
    storage = open_run_store(workspace)
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
    workspace: str | Path,
    state: ParameterChangeReviewState,
    reviewer: str,
    note: str = "",
) -> ParameterChangeDecisionRecord:
    return record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        decision=state,
        actor=reviewer,
        note=note,
    )


def invalidate_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    reason: str,
    invalidated_by: str,
    invalidated_by_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    related_refs = list(invalidated_by_refs or [])
    for ref in related_refs:
        _validate_selector_path(ref)
    return record_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        decision="invalidated",
        actor=invalidated_by,
        note=reason,
        related_refs=related_refs,
    )


def record_parameter_change_decision(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    decision: ParameterChangeDecision,
    actor: str,
    note: str = "",
    related_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    storage = open_run_store(workspace)
    with storage.config_registry_lock(), storage.run_lock(run_id):
        proposal, _proposal_record = _resolve_proposal_ref(
            storage=storage,
            run_id=run_id,
            selector=selector,
        )
        if not actor.strip():
            msg = "parameter change decision actor must be non-empty"
            raise ValueError(msg)
        for ref in related_refs or ():
            _validate_selector_path(ref)
        event_id = uuid4().hex
        decision_entry = parameter_change_decision_record_entry(
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
            msg = f"parameter change decision event already exists: {event_id}"
            raise RuntimeError(msg)
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
    workspace: str | Path,
) -> list[ParameterChangeDecisionRecord]:
    storage = open_run_store(workspace)
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
        except (FileNotFoundError, ValidationError) as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_parameter_change_decision",
                        f"invalid parameter change decision record: {entry.id}",
                        "parameter_change_decision",
                    )
                ]
            ) from error
        expected_entry_id = f"{decision.proposal_id}-decision-{decision.event_id}"
        if decision.run_id != run_id or entry.id != expected_entry_id:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "invalid_parameter_change_decision_identity",
                        (
                            "parameter change decision identity does not match its "
                            f"run record: {entry.id}"
                        ),
                        "parameter_change_decision",
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


def parameter_change_proposal_record(
    *, proposal: ParameterChangeProposal
) -> RunRecordEntry:
    return RunRecordEntry(
        id=proposal.id,
        kind="parameter_change_proposal",
        media_type="application/json",
    )


def parameter_change_decision_record_entry(
    *, proposal_id: str, event_id: str
) -> RunRecordEntry:
    return RunRecordEntry(
        id=f"{proposal_id}-decision-{event_id}",
        kind="parameter_change_decision_record",
        media_type="application/json",
    )


def write_parameter_change_proposals(
    *,
    storage: RunStore,
    run_id: str,
    proposals: Sequence[ParameterChangeProposal],
) -> tuple[RunRecordEntry, ...]:
    with storage.run_lock(run_id):
        entries = write_parameter_change_proposal_contents_locked(
            storage=storage,
            run_id=run_id,
            proposals=proposals,
        )
        if entries:
            write_manifest_records_locked(
                storage=storage,
                run_id=run_id,
                records=entries,
            )
        return entries


def write_parameter_change_proposal_contents_locked(
    *,
    storage: RunStore,
    run_id: str,
    proposals: Sequence[ParameterChangeProposal],
) -> tuple[RunRecordEntry, ...]:
    """Publish immutable proposal content while the caller holds the run lock."""

    entries = tuple(
        parameter_change_proposal_record(proposal=proposal) for proposal in proposals
    )
    for proposal, entry in zip(proposals, entries, strict=True):
        if proposal.source_run_id != run_id:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "parameter_change_proposal_source_run_mismatch",
                        (
                            f"parameter change proposal {proposal.id} belongs to "
                            f"run {proposal.source_run_id}, not {run_id}"
                        ),
                        "parameter_change_proposal.source_run_id",
                    )
                ]
            )
        proposal_ref = record_content_ref(record_id=entry.id, kind=entry.kind)
        if storage.exists(run_id, proposal_ref):
            existing = _load_proposal_record(
                storage=storage,
                run_id=run_id,
                proposal_record=entry,
            )
            if existing != proposal:
                raise ValidationFailed(
                    [
                        _diagnostic(
                            "error",
                            "parameter_change_proposal_conflict",
                            (
                                "parameter change proposal record is immutable and "
                                f"already contains different content: {proposal.id}"
                            ),
                            "parameter_change_proposal",
                        )
                    ]
                )
            continue
        if not storage.write_model_if_absent(run_id, proposal_ref, proposal):
            existing = _load_proposal_record(
                storage=storage,
                run_id=run_id,
                proposal_record=entry,
            )
            if existing != proposal:
                raise ValidationFailed(
                    [
                        _diagnostic(
                            "error",
                            "parameter_change_proposal_conflict",
                            (
                                "parameter change proposal record is immutable and "
                                f"already contains different content: {proposal.id}"
                            ),
                            "parameter_change_proposal",
                        )
                    ]
                )
    return entries


def _resolve_proposal_ref(
    *, storage: RunStore, run_id: str, selector: str
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
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "parameter_change_proposal_not_found",
                f"parameter change proposal not found: {selector}",
                "parameter_change_proposal",
            )
        ]
    )


def _load_proposal_record(
    *, storage: RunStore, run_id: str, proposal_record: RunRecordEntry
) -> ParameterChangeProposal:
    proposal_ref = record_content_ref(
        record_id=proposal_record.id,
        kind=proposal_record.kind,
    )
    path = storage.ref_path(run_id, proposal_ref)
    if not path.exists() or path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_proposal_not_found",
                    f"parameter change proposal not found: {proposal_ref}",
                    "parameter_change_proposal",
                )
            ]
        )
    try:
        proposal = ParameterChangeProposal.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_parameter_change_proposal",
                    f"invalid parameter change proposal: {proposal_ref}",
                    "parameter_change_proposal",
                )
            ]
        ) from error
    if proposal.id != proposal_record.id or proposal.source_run_id != run_id:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_parameter_change_proposal_identity",
                    (
                        "parameter change proposal identity does not match its run "
                        f"record: {proposal_record.id}"
                    ),
                    "parameter_change_proposal",
                )
            ]
        )
    return proposal


def _proposal_records(manifest: RunManifest) -> tuple[RunRecordEntry, ...]:
    return list_records(manifest, kind="parameter_change_proposal")


def _validate_selector_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "parameter_change_path_escape",
                    f"parameter change path escapes run directory: {value}",
                    "parameter_change_proposal",
                )
            ]
        )


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "ParameterChangeDecision",
    "ParameterChangeDecisionRecord",
    "ParameterChangeProposalView",
    "ParameterChangeReviewState",
    "invalidate_parameter_change_proposal",
    "is_safe_parameter_change_id",
    "list_parameter_change_decisions",
    "list_parameter_change_proposals",
    "load_parameter_change_proposal",
    "parameter_change_decision_record_entry",
    "parameter_change_proposal_from_updates",
    "parameter_change_proposal_record",
    "parameter_change_proposal_record_ref",
    "record_parameter_change_decision",
    "review_parameter_change_proposal",
    "write_parameter_change_proposals",
]
