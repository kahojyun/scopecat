"""Workspace-local config registry registration.

The registry stores named configuration snapshots under the workspace-local
``config-registry`` tree and maintains an ``active`` selector for later runs.
Entries can be registered directly from a ``ConfigProfileSnapshot`` or from a
candidate configuration. Activating an entry records the previous active
entry so rollback can restore it without depending on external state.

Runs started from a registry entry carry source coordinates on the run
manifest. Reporting code can then show which registry selector and entry were
used without mixing run lifecycle data into the config snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scopecat._parameter_updates import merge_candidate_parameter_snapshots
from scopecat._storage.local import LocalRunStore
from scopecat._storage.local.io import (
    ensure_durable_directory,
)
from scopecat._storage.local.io import (
    write_model_atomic as _write_local_model_atomic,
)
from scopecat._storage.refs import CONFIG_REGISTRY_LOCK_REF, record_content_ref
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_equal,
    config_content_hash,
)
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.models.run import RunConfigSource, RunManifest, utc_now
from scopecat.parameter_changes import ParameterChangeDecisionRecord
from scopecat.planning.validation import has_blocking_diagnostics, validate_config
from scopecat.runs import get_record_by_id, list_records, open_run_store

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_INDEX_REF = f"{CONFIG_REGISTRY_ROOT}/index.json"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"
CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION = "scopecat.config_registry_entry.v5"
CONFIG_REGISTRY_INDEX_SCHEMA_VERSION = "scopecat.config_registry_index.v2"
CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION = "scopecat.config_registry_active_state.v2"
CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION = (
    "scopecat.config_registry_activation_record.v2"
)
ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR = "active"
SAFE_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"
type EvidenceContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]


class _FrozenValidatedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        _ = deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return type(self).model_validate(data)


class DirectConfigRegistrySource(_FrozenValidatedModel):
    kind: Literal["direct_config_profile"] = "direct_config_profile"


class CandidateProposalRegistryEvidence(_FrozenValidatedModel):
    proposal_id: str
    proposal_record_content_hash: EvidenceContentHash
    approval_event_id: str
    approval_record_content_hash: EvidenceContentHash

    @model_validator(mode="after")
    def validate_identity(self) -> CandidateProposalRegistryEvidence:
        if not self.proposal_id or not self.approval_event_id:
            msg = "candidate proposal evidence identity fields must be non-empty"
            raise ValueError(msg)
        return self


class CandidateConfigRegistrySource(_FrozenValidatedModel):
    kind: Literal["candidate_config"] = "candidate_config"
    run_id: str
    proposal_evidence: tuple[CandidateProposalRegistryEvidence, ...] = Field(
        min_length=1
    )
    candidate_record_id: str
    candidate_record_content_hash: EvidenceContentHash
    base_config_content_hash: ConfigContentHash

    @model_validator(mode="after")
    def validate_evidence(self) -> CandidateConfigRegistrySource:
        proposal_ids = [evidence.proposal_id for evidence in self.proposal_evidence]
        if len(set(proposal_ids)) != len(proposal_ids):
            msg = "candidate registry source proposal evidence must be unique"
            raise ValueError(msg)
        if not self.run_id or not self.candidate_record_id:
            msg = "candidate registry source identity fields must be non-empty"
            raise ValueError(msg)
        return self

    @property
    def proposal_ids(self) -> list[str]:
        return [evidence.proposal_id for evidence in self.proposal_evidence]


@dataclass(frozen=True, slots=True)
class _ValidatedCandidateSource:
    config: ConfigProfileSnapshot
    source: CandidateConfigRegistrySource


ConfigRegistryEntrySource = Annotated[
    DirectConfigRegistrySource | CandidateConfigRegistrySource,
    Field(discriminator="kind"),
]


class ConfigRegistryEntry(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config_registry_entry.v5"] = (
        CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION
    )
    id: str
    config_ref: str
    content_hash: ConfigContentHash
    status: Literal["registered"] = "registered"
    source: ConfigRegistryEntrySource
    registered_by: str
    note: str = ""
    registered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryEntry:
        if not self.id or not self.config_ref or not self.registered_by.strip():
            msg = "config registry entry identity fields must be non-empty"
            raise ValueError(msg)
        return self


class ConfigRegistryIndex(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config_registry_index.v2"] = (
        CONFIG_REGISTRY_INDEX_SCHEMA_VERSION
    )
    entries: tuple[ConfigRegistryEntry, ...] = Field(default_factory=tuple)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_entries(self) -> ConfigRegistryIndex:
        entry_ids = [entry.id for entry in self.entries]
        if len(set(entry_ids)) != len(entry_ids):
            msg = "config registry index entry ids must be unique"
            raise ValueError(msg)
        return self


class ConfigRegistryActivationRecord(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config_registry_activation_record.v2"] = (
        CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION
    )
    id: str
    generation: int = Field(ge=1)
    action: Literal["activation", "rollback"]
    entry_id: str
    entry_content_hash: ConfigContentHash
    previous_entry_id: str | None = None
    previous_entry_content_hash: ConfigContentHash | None = None
    operator: str
    note: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> ConfigRegistryActivationRecord:
        if not self.id or not self.entry_id or not self.operator.strip():
            msg = "config registry activation identity fields must be non-empty"
            raise ValueError(msg)
        if (self.previous_entry_id is None) != (
            self.previous_entry_content_hash is None
        ):
            msg = "previous registry entry id and content hash must be paired"
            raise ValueError(msg)
        return self


class ConfigRegistryActiveState(_FrozenValidatedModel):
    schema_version: Literal["scopecat.config_registry_active_state.v2"] = (
        CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION
    )
    generation: int = Field(ge=1)
    active_entry_id: str
    active_entry_content_hash: ConfigContentHash
    history: tuple[ConfigRegistryActivationRecord, ...] = Field(default_factory=tuple)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_history_head(self) -> ConfigRegistryActiveState:
        if not self.active_entry_id:
            msg = "config registry active entry id must be non-empty"
            raise ValueError(msg)
        if not self.history:
            msg = "config registry active state requires activation history"
            raise ValueError(msg)
        latest = self.history[-1]
        if latest.generation != self.generation:
            msg = "active generation does not match activation history"
            raise ValueError(msg)
        if latest.entry_id != self.active_entry_id:
            msg = "active entry does not match activation history"
            raise ValueError(msg)
        if latest.entry_content_hash != self.active_entry_content_hash:
            msg = "active content hash does not match activation history"
            raise ValueError(msg)
        if len(self.history) != self.generation or any(
            record.generation != index
            for index, record in enumerate(self.history, start=1)
        ):
            msg = "activation history generations must be contiguous"
            raise ValueError(msg)
        record_ids = [record.id for record in self.history]
        if len(set(record_ids)) != len(record_ids):
            msg = "activation history record ids must be unique"
            raise ValueError(msg)
        first = self.history[0]
        if (
            first.previous_entry_id is not None
            or first.previous_entry_content_hash is not None
        ):
            msg = "initial activation must not have a previous entry"
            raise ValueError(msg)
        for previous, current in zip(self.history, self.history[1:], strict=False):
            if (
                current.previous_entry_id != previous.entry_id
                or current.previous_entry_content_hash != previous.entry_content_hash
            ):
                msg = "activation history entry chain is inconsistent"
                raise ValueError(msg)
        return self


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _register_config_profile_locked(
            config=config,
            workspace=workspace_path,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )


def register_and_activate_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    expected_generation: int | None = None,
) -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    workspace_path = Path(workspace)
    selected_generation = (
        current_config_registry_generation(workspace=workspace_path)
        if expected_generation is None
        else expected_generation
    )
    with _registry_lock(workspace_path):
        current_state = _read_active_state_optional(workspace_path)
        _require_expected_generation(current_state, selected_generation)
        entry = _register_config_profile_locked(
            config=config,
            workspace=workspace_path,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )
        active_state, activation = _activate_config_registry_entry_locked(
            entry_id=entry.id,
            workspace=workspace_path,
            operator=operator,
            note=note if activation_note is None else activation_note,
            expected_generation=selected_generation,
        )
        return entry, active_state, activation


def _register_config_profile_locked(
    *,
    config: ConfigProfileSnapshot,
    workspace: Path,
    entry_id: str,
    registered_by: str,
    note: str,
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    refs = _entry_refs(entry_id)
    entry = ConfigRegistryEntry(
        id=entry_id,
        config_ref=refs.config_ref,
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        registered_by=registered_by,
        note=note,
    )
    return _commit_registration_locked(
        workspace=workspace,
        requested_entry=entry,
        config=config,
    )


def register_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    note: str = "",
) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _register_candidate_config_locked(
            config=config,
            workspace=workspace_path,
            entry_id=entry_id,
            registered_by=registered_by,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            note=note,
        )


def register_and_activate_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    operator: str,
    expected_generation: int,
    note: str = "",
    activation_note: str | None = None,
) -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        current_state = _read_active_state_optional(workspace_path)
        _require_expected_generation(current_state, expected_generation)
        entry = _register_candidate_config_locked(
            config=config,
            workspace=workspace_path,
            entry_id=entry_id,
            registered_by=registered_by,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            note=note,
        )
        active_state, activation = _activate_config_registry_entry_locked(
            entry_id=entry.id,
            workspace=workspace_path,
            operator=operator,
            note=note if activation_note is None else activation_note,
            expected_generation=expected_generation,
        )
        return entry, active_state, activation


def _register_candidate_config_locked(
    *,
    config: ConfigProfileSnapshot,
    workspace: Path,
    entry_id: str,
    registered_by: str,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    note: str,
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    if not proposal_ids:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_config_missing_proposals",
                    "candidate config registration requires parameter proposals",
                    "proposal_ids",
                )
            ]
        )
    storage = open_run_store(workspace)
    with storage.run_lock(run_id):
        validated = _validate_candidate_source_records_locked(
            storage=storage,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            requested_config=config,
        )
        durable_config = validated.config
        refs = _entry_refs(entry_id)
        entry = ConfigRegistryEntry(
            id=entry_id,
            config_ref=refs.config_ref,
            content_hash=config_content_hash(durable_config),
            source=validated.source,
            registered_by=registered_by,
            note=note,
        )
        return _commit_registration_locked(
            workspace=workspace,
            requested_entry=entry,
            config=durable_config,
        )


def _validate_candidate_source_records(
    *,
    workspace: Path,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    requested_config: ConfigProfileSnapshot,
) -> _ValidatedCandidateSource:
    storage = open_run_store(workspace)
    with storage.run_lock(run_id):
        return _validate_candidate_source_records_locked(
            storage=storage,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            requested_config=requested_config,
        )


def _validate_candidate_source_records_locked(
    *,
    storage: LocalRunStore,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    requested_config: ConfigProfileSnapshot,
) -> _ValidatedCandidateSource:
    source_manifest = storage.read_manifest(run_id)
    source_config = storage.read_config_profile_snapshot(run_id)
    source_config_hash = config_content_hash(source_config)
    if source_config_hash != base_config_content_hash:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_base_mismatch",
                    (
                        "candidate base config hash does not match its source run "
                        f"snapshot: {run_id}"
                    ),
                    "base_config_content_hash",
                )
            ]
        )
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_duplicate_proposal",
                    "candidate config proposal ids must be unique",
                    "proposal_ids",
                )
            ]
        )
    proposals: list[ParameterChangeProposal] = []
    proposal_hashes: dict[str, EvidenceContentHash] = {}
    for proposal_id in proposal_ids:
        proposal_record = _require_run_record(
            source_manifest=source_manifest,
            record_id=proposal_id,
            kind="parameter_change_proposal",
        )
        try:
            proposal = storage.read_model(
                run_id,
                record_content_ref(
                    record_id=proposal_record.id,
                    kind=proposal_record.kind,
                ),
                ParameterChangeProposal,
            )
        except (OSError, ValidationError) as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_invalid_candidate_proposal",
                        f"candidate proposal record is not readable: {proposal_id}",
                        "proposal_ids",
                    )
                ]
            ) from error
        if (
            proposal.id != proposal_id
            or proposal.source_run_id != run_id
            or proposal.base_config_id != source_config.id
            or proposal.base_config_content_hash != base_config_content_hash
        ):
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_candidate_proposal_mismatch",
                        (
                            "candidate proposal record does not match its source "
                            f"config: {proposal_id}"
                        ),
                        "proposal_ids",
                    )
                ]
            )
        proposals.append(proposal)
        proposal_hashes[proposal_id] = _record_content_hash(proposal)
    approval_evidence = _candidate_approval_evidence(
        storage=storage,
        source_manifest=source_manifest,
        run_id=run_id,
        proposal_ids=proposal_ids,
        proposal_hashes=proposal_hashes,
    )
    candidate_record = _require_run_record(
        source_manifest=source_manifest,
        record_id=candidate_record_id,
        kind="candidate_config",
    )
    try:
        durable_config = storage.read_model(
            run_id,
            record_content_ref(
                record_id=candidate_record.id,
                kind=candidate_record.kind,
            ),
            ConfigProfileSnapshot,
        )
    except (OSError, ValidationError) as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_invalid_candidate_record",
                    (f"candidate config record is not readable: {candidate_record_id}"),
                    "candidate_record_id",
                )
            ]
        ) from error
    if config_content_hash(durable_config) != config_content_hash(requested_config):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_record_mismatch",
                    (
                        "candidate config does not match its durable source record: "
                        f"{candidate_record_id}"
                    ),
                    "candidate_record_id",
                )
            ]
        )
    try:
        expected_parameters = merge_candidate_parameter_snapshots(
            base=source_config.parameter_snapshot,
            candidates=tuple(
                (proposal.candidate_snapshot, proposal.deltas) for proposal in proposals
            ),
            candidate_id=durable_config.parameter_snapshot.id,
        )
    except ValueError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_derivation_mismatch",
                    f"candidate config cannot be derived from its proposals: {error}",
                    "proposal_ids",
                )
            ]
        ) from error
    expected_config = ConfigProfileSnapshot.model_validate(
        source_config.model_dump(mode="python")
        | {
            "id": durable_config.id,
            "parameter_snapshot": expected_parameters,
        }
    )
    if config_content_hash(expected_config) != config_content_hash(durable_config):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_derivation_mismatch",
                    "candidate config is not derived from its durable proposals",
                    "candidate_record_id",
                )
            ]
        )
    source = CandidateConfigRegistrySource(
        run_id=run_id,
        proposal_evidence=approval_evidence,
        candidate_record_id=candidate_record_id,
        candidate_record_content_hash=_record_content_hash(durable_config),
        base_config_content_hash=base_config_content_hash,
    )
    return _ValidatedCandidateSource(config=durable_config, source=source)


def _candidate_approval_evidence(
    *,
    storage: LocalRunStore,
    source_manifest: RunManifest,
    run_id: str,
    proposal_ids: Sequence[str],
    proposal_hashes: Mapping[str, EvidenceContentHash],
) -> tuple[CandidateProposalRegistryEvidence, ...]:
    histories: dict[
        str,
        list[tuple[RunRecordEntry, ParameterChangeDecisionRecord]],
    ] = {proposal_id: [] for proposal_id in proposal_ids}
    for entry in list_records(
        source_manifest,
        kind="parameter_change_decision_record",
    ):
        try:
            decision = storage.read_model(
                run_id,
                record_content_ref(record_id=entry.id, kind=entry.kind),
                ParameterChangeDecisionRecord,
            )
        except (OSError, ValidationError) as error:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_invalid_candidate_approval",
                        f"candidate approval record is not readable: {entry.id}",
                        "proposal_ids",
                    )
                ]
            ) from error
        expected_entry_id = f"{decision.proposal_id}-decision-{decision.event_id}"
        if decision.run_id != run_id or entry.id != expected_entry_id:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_invalid_candidate_approval_identity",
                        (
                            "candidate approval identity does not match its run "
                            f"record: {entry.id}"
                        ),
                        "proposal_ids",
                    )
                ]
            )
        if decision.proposal_id in histories:
            histories[decision.proposal_id].append((entry, decision))

    evidence: list[CandidateProposalRegistryEvidence] = []
    for proposal_id in proposal_ids:
        history = histories[proposal_id]
        if not history or history[-1][1].decision != "approved":
            latest = "not reviewed" if not history else history[-1][1].decision
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_candidate_proposal_not_approved",
                        (
                            f"candidate proposal {proposal_id} latest decision must "
                            f"be approved; found {latest}"
                        ),
                        "proposal_ids",
                    )
                ]
            )
        _entry, approval = history[-1]
        evidence.append(
            CandidateProposalRegistryEvidence(
                proposal_id=proposal_id,
                proposal_record_content_hash=proposal_hashes[proposal_id],
                approval_event_id=approval.event_id,
                approval_record_content_hash=_record_content_hash(approval),
            )
        )
    return tuple(evidence)


def _record_content_hash(model: BaseModel) -> EvidenceContentHash:
    content = json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_candidate_entry_evidence_locked(
    *,
    workspace: Path,
    entry: ConfigRegistryEntry,
    config: ConfigProfileSnapshot,
) -> None:
    if not isinstance(entry.source, CandidateConfigRegistrySource):
        return
    validated = _validate_candidate_source_records(
        workspace=workspace,
        run_id=entry.source.run_id,
        proposal_ids=entry.source.proposal_ids,
        candidate_record_id=entry.source.candidate_record_id,
        base_config_content_hash=entry.source.base_config_content_hash,
        requested_config=config,
    )
    if validated.source == entry.source:
        return
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "config_registry_candidate_evidence_mismatch",
                f"candidate registry evidence no longer matches: {entry.id}",
                "source",
            )
        ]
    )


def list_config_registry_entries(*, workspace: str | Path) -> list[ConfigRegistryEntry]:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        index = _read_index(workspace_path)
        entries = [
            _validate_indexed_entry_locked(
                workspace=workspace_path,
                indexed_entry=indexed_entry,
            )
            for indexed_entry in index.entries
        ]
        return sorted(entries, key=lambda entry: entry.registered_at)


def load_config_registry_entry(
    *, entry_id: str, workspace: str | Path
) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _load_config_registry_entry_locked(
            entry_id=entry_id,
            workspace=workspace_path,
        )


def _load_config_registry_entry_locked(
    *, entry_id: str, workspace: Path
) -> ConfigRegistryEntry:
    index = _read_index(workspace)
    indexed_entry = next(
        (entry for entry in index.entries if entry.id == entry_id),
        None,
    )
    if indexed_entry is None:
        refs = _entry_refs(entry_id)
        entry_path = _workspace_relative_path(workspace, refs.entry_ref)
        code = (
            "config_registry_uncommitted_entry"
            if entry_path.exists()
            else "config_registry_not_found"
        )
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    code,
                    f"config registry entry is not committed: {entry_id}",
                    "entry_id",
                )
            ]
        )
    return _validate_indexed_entry_locked(
        workspace=workspace,
        indexed_entry=indexed_entry,
    )


def _validate_indexed_entry_locked(
    *,
    workspace: Path,
    indexed_entry: ConfigRegistryEntry,
) -> ConfigRegistryEntry:
    entry = _read_config_registry_entry_file_locked(
        entry_id=indexed_entry.id,
        workspace=workspace,
    )
    if entry != indexed_entry:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_index_entry_mismatch",
                    (
                        "config registry entry file does not match its committed "
                        f"index record: {entry.id}"
                    ),
                    "config_registry",
                )
            ]
        )
    config = _read_entry_config(workspace, entry)
    _validate_candidate_entry_evidence_locked(
        workspace=workspace,
        entry=entry,
        config=config,
    )
    return entry


def _read_config_registry_entry_file_locked(
    *, entry_id: str, workspace: Path
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    refs = _entry_refs(entry_id)
    entry_path = _workspace_relative_path(workspace, refs.entry_ref)
    if not entry_path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_not_found",
                    f"config registry entry not found: {entry_id}",
                    "entry_id",
                )
            ]
        )
    entry = _read_model(entry_path, ConfigRegistryEntry, refs.entry_ref)
    if entry.id != entry_id or entry.config_ref != refs.config_ref:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_entry_ref_mismatch",
                    f"config registry entry has an invalid config ref: {entry.id}",
                    "config_ref",
                )
            ]
        )
    return entry


def load_config_registry_config(
    *, entry_id: str, workspace: str | Path
) -> ConfigProfileSnapshot:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        entry = _load_config_registry_entry_locked(
            entry_id=entry_id,
            workspace=workspace_path,
        )
        return _read_entry_config(workspace_path, entry)


def load_active_config_registry_config(
    *, workspace: str | Path
) -> ConfigProfileSnapshot:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        state = _load_active_config_registry_state_locked(workspace_path)
        entry = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            workspace=workspace_path,
        )
        _validate_active_entry_identity(state, entry)
        return _read_entry_config(workspace_path, entry)


def resolve_config_registry_config_source(
    *, selector: str, workspace: str | Path
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        if selector == ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR:
            return _resolve_active_config_registry_config_source_locked(
                workspace=workspace_path
            )
        return _resolve_entry_config_registry_config_source_locked(
            selector=selector,
            workspace=workspace_path,
        )


def activate_config_registry_entry(
    *,
    entry_id: str,
    workspace: str | Path,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _activate_config_registry_entry_locked(
            entry_id=entry_id,
            workspace=workspace_path,
            operator=operator,
            expected_generation=expected_generation,
            note=note,
        )


def _activate_config_registry_entry_locked(
    *,
    entry_id: str,
    workspace: Path,
    operator: str,
    expected_generation: int,
    note: str,
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    current_state = _read_active_state_optional(workspace)
    _require_expected_generation(current_state, expected_generation)
    entry = _load_config_registry_entry_locked(
        entry_id=entry_id,
        workspace=workspace,
    )
    _validate_candidate_base(current_state, entry, workspace)
    _validate_entry_config(workspace, entry)
    previous_entry_id = (
        current_state.active_entry_id if current_state is not None else None
    )
    previous_content_hash = (
        current_state.active_entry_content_hash if current_state is not None else None
    )
    history = [] if current_state is None else [*current_state.history]
    generation = expected_generation + 1
    record = ConfigRegistryActivationRecord(
        id=_next_record_id(history, "activation"),
        generation=generation,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        previous_entry_id=previous_entry_id,
        previous_entry_content_hash=previous_content_hash,
        operator=operator,
        note=note,
    )
    state = ConfigRegistryActiveState(
        generation=generation,
        active_entry_id=entry.id,
        active_entry_content_hash=entry.content_hash,
        history=(*history, record),
    )
    _write_model_atomic(workspace / CONFIG_REGISTRY_ACTIVE_REF, state)
    return state, record


def rollback_config_registry(
    *,
    workspace: str | Path,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        current_state = _read_active_state_optional(workspace_path)
        _require_expected_generation(current_state, expected_generation)
        if current_state is None:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_no_active_entry",
                        "config registry has no active entry",
                        "active",
                    )
                ]
            )
        current_entry = _load_config_registry_entry_locked(
            entry_id=current_state.active_entry_id,
            workspace=workspace_path,
        )
        _validate_active_entry_identity(current_state, current_entry)
        _read_entry_config(workspace_path, current_entry)
        rollback_target = _previous_distinct_activation(current_state)
        entry = _load_config_registry_entry_locked(
            entry_id=rollback_target.entry_id,
            workspace=workspace_path,
        )
        _validate_entry_config(workspace_path, entry)
        if entry.content_hash != rollback_target.entry_content_hash:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_rollback_content_mismatch",
                        (
                            "rollback target content no longer matches activation "
                            f"history: {entry.id}"
                        ),
                        "active.history",
                    )
                ]
            )
        history = [*current_state.history]
        generation = expected_generation + 1
        record = ConfigRegistryActivationRecord(
            id=_next_record_id(history, "rollback"),
            generation=generation,
            action="rollback",
            entry_id=entry.id,
            entry_content_hash=entry.content_hash,
            previous_entry_id=current_state.active_entry_id,
            previous_entry_content_hash=current_state.active_entry_content_hash,
            operator=operator,
            note=note,
        )
        state = ConfigRegistryActiveState(
            generation=generation,
            active_entry_id=entry.id,
            active_entry_content_hash=entry.content_hash,
            history=(*history, record),
        )
        _write_model_atomic(workspace_path / CONFIG_REGISTRY_ACTIVE_REF, state)
        return state, record


def current_config_registry_generation(*, workspace: str | Path) -> int:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _state_generation(_read_active_state_optional(workspace_path))


def load_active_config_registry_state(
    *, workspace: str | Path
) -> ConfigRegistryActiveState:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        return _load_active_config_registry_state_locked(workspace_path)


def _load_active_config_registry_state_locked(
    workspace: Path,
) -> ConfigRegistryActiveState:
    active_path = workspace / CONFIG_REGISTRY_ACTIVE_REF
    if not active_path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_no_active_entry",
                    "config registry has no active entry",
                    "active",
                )
            ]
        )
    return _read_active_state(active_path)


def load_active_config_registry_entry(*, workspace: str | Path) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        state = _load_active_config_registry_state_locked(workspace_path)
        entry = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            workspace=workspace_path,
        )
        _validate_active_entry_identity(state, entry)
        _read_entry_config(workspace_path, entry)
        return entry


def _resolve_entry_config_registry_config_source_locked(
    *, selector: str, workspace: Path
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    entry = _load_config_registry_entry_locked(
        entry_id=selector,
        workspace=workspace,
    )
    config = _read_entry_config(workspace, entry)
    source = RunConfigSource(
        selector=selector,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
    )
    return config, source


def _resolve_active_config_registry_config_source_locked(
    *, workspace: Path
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    state = _load_active_config_registry_state_locked(workspace)
    entry = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        workspace=workspace,
    )
    _validate_active_entry_identity(state, entry)
    config = _read_entry_config(workspace, entry)
    source = RunConfigSource(
        selector=ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
        registry_generation=state.generation,
    )
    return config, source


class _EntryRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_ref: str
    config_ref: str


def _entry_refs(entry_id: str) -> _EntryRefs:
    return _EntryRefs(
        entry_ref=f"{CONFIG_REGISTRY_ROOT}/entries/{entry_id}.json",
        config_ref=(
            f"{CONFIG_REGISTRY_ROOT}/configs/{entry_id}.config-profile-snapshot.json"
        ),
    )


def _validate_entry_id(entry_id: str) -> None:
    if not SAFE_ENTRY_ID_RE.fullmatch(entry_id):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_invalid_entry_id",
                    f"config registry entry id is not safe: {entry_id}",
                    "entry_id",
                )
            ]
        )


def _require_run_record(
    *, source_manifest: RunManifest, record_id: str, kind: str
) -> RunRecordEntry:
    record = get_record_by_id(source_manifest, record_id)
    if record is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_missing_source_record",
                    f"config registry source record not found: {record_id}",
                    "record_id",
                )
            ]
        )
    if record.kind != kind:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_invalid_source_record_kind",
                    (
                        "config registry source record has kind "
                        f"{record.kind}, expected {kind}: {record_id}"
                    ),
                    "record_id",
                )
            ]
        )
    return record


def _commit_registration_locked(
    *,
    workspace: Path,
    requested_entry: ConfigRegistryEntry,
    config: ConfigProfileSnapshot,
) -> ConfigRegistryEntry:
    index = _read_index(workspace)
    existing = _find_existing_entry_locked(
        workspace=workspace,
        index=index,
        entry_id=requested_entry.id,
    )
    if existing is not None:
        existing_config = _read_entry_config(workspace, existing)
        if not (
            _same_registration(existing, requested_entry)
            and _same_config_profile(existing_config, config)
        ):
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_duplicate_entry",
                        (f"config registry entry already exists: {requested_entry.id}"),
                        "entry_id",
                    )
                ]
            )
        _write_registry_index_if_needed(
            workspace=workspace,
            index=index,
            entry=existing,
        )
        return existing
    _write_config_registry_registration(
        workspace=workspace,
        index=index,
        entry=requested_entry,
        config=config,
    )
    return requested_entry


def _find_existing_entry_locked(
    *,
    workspace: Path,
    index: ConfigRegistryIndex,
    entry_id: str,
) -> ConfigRegistryEntry | None:
    refs = _entry_refs(entry_id)
    entry_path = _workspace_relative_path(workspace, refs.entry_ref)
    indexed_entry = next(
        (entry for entry in index.entries if entry.id == entry_id),
        None,
    )
    if entry_path.exists():
        entry = _read_config_registry_entry_file_locked(
            entry_id=entry_id,
            workspace=workspace,
        )
        if indexed_entry is not None and indexed_entry != entry:
            raise ValidationFailed(
                [
                    _diagnostic(
                        "error",
                        "config_registry_index_entry_mismatch",
                        (
                            "config registry entry file does not match its committed "
                            f"index record: {entry_id}"
                        ),
                        "config_registry",
                    )
                ]
            )
        return entry
    if indexed_entry is not None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_incomplete_entry",
                    f"config registry entry file is missing: {entry_id}",
                    refs.entry_ref,
                )
            ]
        )
    return None


def _same_registration(
    existing: ConfigRegistryEntry, requested: ConfigRegistryEntry
) -> bool:
    if (
        existing.config_ref != requested.config_ref
        or existing.content_hash != requested.content_hash
    ):
        return False
    if isinstance(existing.source, DirectConfigRegistrySource) and isinstance(
        requested.source, DirectConfigRegistrySource
    ):
        return (
            existing.registered_by == requested.registered_by
            and existing.note == requested.note
        )
    if isinstance(existing.source, CandidateConfigRegistrySource) and isinstance(
        requested.source, CandidateConfigRegistrySource
    ):
        return (
            existing.source == requested.source
            and existing.registered_by == requested.registered_by
            and existing.note == requested.note
        )
    return False


def _same_config_profile(
    left: ConfigProfileSnapshot, right: ConfigProfileSnapshot
) -> bool:
    return config_content_equal(left, right)


def _read_index(workspace: Path) -> ConfigRegistryIndex:
    index_path = workspace / CONFIG_REGISTRY_INDEX_REF
    if not index_path.exists():
        return ConfigRegistryIndex()
    return _read_model(index_path, ConfigRegistryIndex, CONFIG_REGISTRY_INDEX_REF)


def _read_active_state_optional(workspace: Path) -> ConfigRegistryActiveState | None:
    active_path = workspace / CONFIG_REGISTRY_ACTIVE_REF
    if not active_path.exists():
        return None
    return _read_active_state(active_path)


@contextmanager
def _registry_lock(workspace: Path) -> Generator[None]:
    lock_path = workspace / CONFIG_REGISTRY_LOCK_REF
    ensure_durable_directory(lock_path.parent)
    with lock_path.open("a+b") as lock_file:
        flock(lock_file.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(lock_file.fileno(), LOCK_UN)


def _require_expected_generation(
    state: ConfigRegistryActiveState | None,
    expected_generation: int,
) -> None:
    current_generation = 0 if state is None else state.generation
    if expected_generation == current_generation:
        return
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "config_registry_conflict",
                (
                    "config registry active state changed: expected generation "
                    f"{expected_generation}, found {current_generation}"
                ),
                "expected_generation",
            )
        ]
    )


def _state_generation(state: ConfigRegistryActiveState | None) -> int:
    return 0 if state is None else state.generation


def _read_active_state(path: Path) -> ConfigRegistryActiveState:
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_is_directory",
                    "config registry input is a directory: "
                    f"{CONFIG_REGISTRY_ACTIVE_REF}",
                    CONFIG_REGISTRY_ACTIVE_REF,
                )
            ]
        )
    try:
        return ConfigRegistryActiveState.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_config_registry_active_state",
                    "config registry active state is not valid JSON",
                    CONFIG_REGISTRY_ACTIVE_REF,
                )
            ]
        ) from error


def _read_config(path: Path, ref: str) -> ConfigProfileSnapshot:
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_config_registry_input",
                    f"config registry input is missing: {ref}",
                    ref,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_is_directory",
                    f"config registry input is a directory: {ref}",
                    ref,
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
                    "invalid_config_registry_input",
                    f"config registry input is not a valid config: {ref}",
                    ref,
                )
            ]
        ) from error


def _read_entry_config(
    workspace: Path,
    entry: ConfigRegistryEntry,
) -> ConfigProfileSnapshot:
    config_path = _config_registry_config_path(workspace, entry.config_ref)
    config = _read_config(config_path, entry.config_ref)
    actual_hash = config_content_hash(config)
    if actual_hash != entry.content_hash:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_content_hash_mismatch",
                    (
                        f"config registry entry {entry.id} content does not match "
                        "its registered hash"
                    ),
                    entry.config_ref,
                )
            ]
        )
    return config


def _validate_active_entry_identity(
    state: ConfigRegistryActiveState,
    entry: ConfigRegistryEntry,
) -> None:
    if state.active_entry_content_hash == entry.content_hash:
        return
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "config_registry_active_content_mismatch",
                "active config registry state does not match its entry",
                CONFIG_REGISTRY_ACTIVE_REF,
            )
        ]
    )


def _validate_candidate_base(
    state: ConfigRegistryActiveState | None,
    entry: ConfigRegistryEntry,
    workspace: Path,
) -> None:
    if state is None:
        return
    active_entry = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        workspace=workspace,
    )
    _validate_active_entry_identity(state, active_entry)
    _read_entry_config(workspace, active_entry)
    if state.active_entry_id == entry.id:
        return
    if not isinstance(entry.source, CandidateConfigRegistrySource):
        return
    if entry.source.base_config_content_hash == active_entry.content_hash:
        return
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "config_registry_stale_candidate",
                (
                    f"candidate config {entry.id} was based on "
                    f"{entry.source.base_config_content_hash}, but the active config "
                    f"is {active_entry.content_hash}"
                ),
                "source.base_config_content_hash",
            )
        ]
    )


def _validate_entry_config(workspace: Path, entry: ConfigRegistryEntry) -> None:
    config = _read_entry_config(workspace, entry)
    diagnostics = validate_config(config)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)


def _previous_distinct_activation(
    state: ConfigRegistryActiveState,
) -> ConfigRegistryActivationRecord:
    for record in reversed(state.history[:-1]):
        if record.entry_id != state.active_entry_id:
            return record
    raise ValidationFailed(
        [
            _diagnostic(
                "error",
                "config_registry_no_rollback_target",
                "config registry has no previous active entry",
                "active",
            )
        ]
    )


def _next_record_id(history: list[ConfigRegistryActivationRecord], action: str) -> str:
    index = len(history) + 1
    return f"{action}-{index:06d}"


def _read_model[TModel: BaseModel](
    path: Path, model_type: type[TModel], ref: str
) -> TModel:
    if not path.exists():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_config_registry_input",
                    f"config registry input is missing: {ref}",
                    ref,
                )
            ]
        )
    if path.is_dir():
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_is_directory",
                    f"config registry input is a directory: {ref}",
                    ref,
                )
            ]
        )
    try:
        return model_type.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_config_registry_input",
                    f"config registry input is not valid JSON for {ref}",
                    ref,
                )
            ]
        ) from error


def _write_config_registry_registration(
    *,
    workspace: Path,
    index: ConfigRegistryIndex,
    entry: ConfigRegistryEntry,
    config: ConfigProfileSnapshot,
) -> None:
    refs = _entry_refs(entry.id)
    updated_entries = [
        existing for existing in index.entries if existing.id != entry.id
    ]
    updated_entries.append(entry)
    updated_index = ConfigRegistryIndex(
        entries=tuple(sorted(updated_entries, key=lambda item: item.registered_at))
    )

    # The index is the commit marker. A crash before its replacement leaves either
    # an orphan config or a complete entry/config pair that an idempotent retry
    # repairs into the index.
    _write_model_atomic(_workspace_relative_path(workspace, refs.config_ref), config)
    _write_model_atomic(_workspace_relative_path(workspace, refs.entry_ref), entry)
    _write_model_atomic(workspace / CONFIG_REGISTRY_INDEX_REF, updated_index)


def _write_registry_index_if_needed(
    *,
    workspace: Path,
    index: ConfigRegistryIndex,
    entry: ConfigRegistryEntry,
) -> None:
    indexed = next((item for item in index.entries if item.id == entry.id), None)
    if indexed == entry:
        return
    updated_entries = [item for item in index.entries if item.id != entry.id]
    updated_entries.append(entry)
    _write_model_atomic(
        workspace / CONFIG_REGISTRY_INDEX_REF,
        ConfigRegistryIndex(
            entries=tuple(sorted(updated_entries, key=lambda item: item.registered_at))
        ),
    )


def _write_model_atomic(path: Path, model: BaseModel) -> None:
    _write_local_model_atomic(path, model)


def _workspace_relative_path(workspace: Path, ref: str) -> Path:
    relative = PurePosixPath(ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_path_escape",
                    f"config registry path escapes workspace: {ref}",
                    "config_registry",
                )
            ]
        )
    candidate = workspace / relative.as_posix()
    workspace_root = workspace.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(workspace_root)
    except ValueError as error:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_path_escape",
                    f"config registry path escapes workspace: {ref}",
                    "config_registry",
                )
            ]
        ) from error
    return candidate


def _config_registry_config_path(workspace: Path, ref: str) -> Path:
    relative = PurePosixPath(ref)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] != CONFIG_REGISTRY_ROOT
        or relative.parts[1] != "configs"
    ):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_path_escape",
                    f"config registry config path is outside config store: {ref}",
                    "config_ref",
                )
            ]
        )
    return _workspace_relative_path(workspace, ref)


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
