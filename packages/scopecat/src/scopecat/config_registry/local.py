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
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticSerializationError

from scopecat._parameter_updates import merge_candidate_parameter_snapshots
from scopecat._storage.local import LocalRunStore
from scopecat._storage.local.io import (
    ensure_durable_directory,
)
from scopecat._storage.local.io import (
    write_model_atomic as _write_local_model_atomic,
)
from scopecat._storage.refs import CONFIG_REGISTRY_LOCK_REF, record_content_ref
from scopecat.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    ProblemFailure,
    StorageError,
)
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
from scopecat.planning.validation import validate_config
from scopecat.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    has_blocking_problems,
)
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
    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
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
    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(operator, field="operator")
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
    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(run_id, field="run_id")
    _validate_required_text(candidate_record_id, field="candidate_record_id")
    for proposal_id in proposal_ids:
        _validate_required_text(proposal_id, field="proposal_ids")
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
    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(operator, field="operator")
    _validate_required_text(run_id, field="run_id")
    _validate_required_text(candidate_record_id, field="candidate_record_id")
    for proposal_id in proposal_ids:
        _validate_required_text(proposal_id, field="proposal_ids")
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
        raise _registry_failure(
            CheckFailed,
            code="config_registry.candidate_config_missing_proposals",
            category=ProblemCategory.INVALID_INPUT,
            message="candidate config registration requires parameter proposals",
            location=_registry_model_location("proposal_ids"),
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
        raise _registry_failure(
            Conflict,
            code="config_registry.candidate_base_mismatch",
            category=ProblemCategory.CONFLICT,
            message="candidate base config does not match its source run snapshot",
            location=_registry_model_location("base_config_content_hash"),
            related_locations=(
                _registry_storage_location(
                    CONFIG_PROFILE_SNAPSHOT_REF,
                    run_id=run_id,
                ),
            ),
            details={
                "expected_content_hash": base_config_content_hash,
                "actual_content_hash": source_config_hash,
            },
        )
    if len(set(proposal_ids)) != len(proposal_ids):
        raise _registry_failure(
            CheckFailed,
            code="config_registry.candidate_duplicate_proposal",
            category=ProblemCategory.INVALID_INPUT,
            message="candidate config proposal ids must be unique",
            location=_registry_model_location("proposal_ids"),
        )
    proposals: list[ParameterChangeProposal] = []
    proposal_hashes: dict[str, EvidenceContentHash] = {}
    for proposal_id in proposal_ids:
        proposal_record = _require_run_record(
            source_manifest=source_manifest,
            record_id=proposal_id,
            kind="parameter_change_proposal",
        )
        proposal_ref = record_content_ref(
            record_id=proposal_record.id,
            kind=proposal_record.kind,
        )
        proposal = storage.read_model(
            run_id,
            proposal_ref,
            ParameterChangeProposal,
        )
        if (
            proposal.id != proposal_id
            or proposal.source_run_id != run_id
            or proposal.base_config_id != source_config.id
            or proposal.base_config_content_hash != base_config_content_hash
        ):
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.candidate_proposal_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message="candidate proposal does not match its source config",
                location=_registry_storage_location(proposal_ref, run_id=run_id),
                related_locations=(_registry_model_location("proposal_ids"),),
                details={"proposal_id": proposal_id},
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
    candidate_ref = record_content_ref(
        record_id=candidate_record.id,
        kind=candidate_record.kind,
    )
    durable_config = storage.read_model(
        run_id,
        candidate_ref,
        ConfigProfileSnapshot,
    )
    if config_content_hash(durable_config) != config_content_hash(requested_config):
        raise _registry_failure(
            Conflict,
            code="config_registry.candidate_record_mismatch",
            category=ProblemCategory.CONFLICT,
            message="candidate config does not match its durable source record",
            location=_registry_model_location("candidate_record_id"),
            related_locations=(
                _registry_storage_location(candidate_ref, run_id=run_id),
            ),
            details={"candidate_record_id": candidate_record_id},
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
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.candidate_derivation_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="candidate config cannot be derived from its durable proposals",
            location=_registry_model_location("proposal_ids"),
        ) from error
    try:
        expected_config = ConfigProfileSnapshot.model_validate(
            source_config.model_dump(mode="python")
            | {
                "id": durable_config.id,
                "parameter_snapshot": expected_parameters,
            }
        )
    except ValidationError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.candidate_derivation_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="candidate config cannot be derived from its durable proposals",
            location=_registry_model_location("proposal_ids"),
        ) from error
    if config_content_hash(expected_config) != config_content_hash(durable_config):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.candidate_derivation_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="candidate config is not derived from its durable proposals",
            location=_registry_model_location("candidate_record_id"),
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
        decision_ref = record_content_ref(record_id=entry.id, kind=entry.kind)
        decision = storage.read_model(
            run_id,
            decision_ref,
            ParameterChangeDecisionRecord,
        )
        expected_entry_id = f"{decision.proposal_id}-decision-{decision.event_id}"
        if decision.run_id != run_id or entry.id != expected_entry_id:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.candidate_approval_identity_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message="candidate approval identity does not match its run record",
                location=_registry_storage_location(decision_ref, run_id=run_id),
                related_locations=(_registry_model_location("proposal_ids"),),
                details={"record_id": entry.id},
            )
        if decision.proposal_id in histories:
            histories[decision.proposal_id].append((entry, decision))

    evidence: list[CandidateProposalRegistryEvidence] = []
    for proposal_id in proposal_ids:
        history = histories[proposal_id]
        if not history or history[-1][1].decision != "approved":
            latest = "not reviewed" if not history else history[-1][1].decision
            raise _registry_failure(
                Conflict,
                code="config_registry.candidate_proposal_not_approved",
                category=ProblemCategory.CONFLICT,
                message="candidate proposal latest decision is not approved",
                location=_registry_model_location("proposal_ids"),
                details={"proposal_id": proposal_id, "latest_decision": latest},
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
    try:
        content = json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
    except (PydanticSerializationError, TypeError, ValueError) as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.evidence_not_serializable",
            category=ProblemCategory.DATA_INTEGRITY,
            message="candidate evidence cannot be represented durably",
            location=_registry_model_location("source"),
        ) from error
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
    raise _registry_failure(
        DataIntegrityError,
        code="config_registry.candidate_evidence_mismatch",
        category=ProblemCategory.DATA_INTEGRITY,
        message="candidate registry evidence no longer matches its durable source",
        location=_registry_model_location("entries", entry.id, "source"),
        details={"entry_id": entry.id},
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
    _validate_entry_id(entry_id)
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
        if _path_exists(entry_path, ref=refs.entry_ref):
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.uncommitted_entry",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry entry exists without an index commit",
                location=_registry_storage_location(refs.entry_ref),
                related_locations=(_registry_model_location("entry_id"),),
                details={"entry_id": entry_id},
            )
        raise _registry_failure(
            NotFound,
            code="config_registry.not_found",
            category=ProblemCategory.NOT_FOUND,
            message="config registry entry was not found",
            location=_registry_model_location("entry_id"),
            details={"entry_id": entry_id},
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
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.index_entry_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry entry does not match its committed index record",
            location=_registry_storage_location(CONFIG_REGISTRY_INDEX_REF),
            related_locations=(
                _registry_storage_location(_entry_refs(entry.id).entry_ref),
            ),
            details={"entry_id": entry.id},
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
    _validate_durable_entry_id(entry_id, ref=CONFIG_REGISTRY_INDEX_REF)
    refs = _entry_refs(entry_id)
    entry_path = _workspace_relative_path(workspace, refs.entry_ref)
    if not _path_exists(entry_path, ref=refs.entry_ref):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.entry_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="committed config registry entry file is missing",
            location=_registry_storage_location(refs.entry_ref),
            details={"entry_id": entry_id},
        )
    entry = _read_model(entry_path, ConfigRegistryEntry, refs.entry_ref)
    if entry.id != entry_id or entry.config_ref != refs.config_ref:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.entry_ref_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry entry has inconsistent storage coordinates",
            location=_registry_storage_location(refs.entry_ref),
            related_locations=(_registry_model_location("config_ref"),),
            details={"entry_id": entry_id},
        )
    return entry


def load_config_registry_config(
    *, entry_id: str, workspace: str | Path
) -> ConfigProfileSnapshot:
    _validate_entry_id(entry_id)
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
    if selector != ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR:
        _validate_entry_id(selector)
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
    _validate_entry_id(entry_id)
    _validate_required_text(operator, field="operator")
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
    _validate_required_text(operator, field="operator")
    workspace_path = Path(workspace)
    with _registry_lock(workspace_path):
        current_state = _read_active_state_optional(workspace_path)
        _require_expected_generation(current_state, expected_generation)
        if current_state is None:
            raise _registry_failure(
                NotFound,
                code="config_registry.no_active_entry",
                category=ProblemCategory.NOT_FOUND,
                message="config registry has no active entry",
                location=_registry_model_location("active"),
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
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.rollback_content_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message="rollback target no longer matches activation history",
                location=_registry_storage_location(CONFIG_REGISTRY_ACTIVE_REF),
                related_locations=(_registry_storage_location(entry.config_ref),),
                details={"entry_id": entry.id},
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
    if not _path_exists(active_path, ref=CONFIG_REGISTRY_ACTIVE_REF):
        raise _registry_failure(
            NotFound,
            code="config_registry.no_active_entry",
            category=ProblemCategory.NOT_FOUND,
            message="config registry has no active entry",
            location=_registry_model_location("active"),
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
        raise _registry_failure(
            CheckFailed,
            code="config_registry.invalid_entry_id",
            category=ProblemCategory.INVALID_INPUT,
            message="config registry entry id is not safe",
            location=_registry_model_location("entry_id"),
            details={"entry_id": entry_id},
        )


def _validate_durable_entry_id(entry_id: str, *, ref: str) -> None:
    if SAFE_ENTRY_ID_RE.fullmatch(entry_id):
        return
    raise _registry_failure(
        DataIntegrityError,
        code="config_registry.entry_id_invalid",
        category=ProblemCategory.DATA_INTEGRITY,
        message="config registry durable entry id is not safe",
        location=_registry_storage_location(ref),
        details={"entry_id": entry_id},
    )


def _validate_required_text(value: str, *, field: str) -> None:
    if value.strip():
        return
    raise _registry_failure(
        CheckFailed,
        code=f"config_registry.{field}_missing",
        category=ProblemCategory.INVALID_INPUT,
        message=f"config registry {field} must be non-empty",
        location=_registry_model_location(field),
    )


def _require_run_record(
    *, source_manifest: RunManifest, record_id: str, kind: str
) -> RunRecordEntry:
    record = get_record_by_id(source_manifest, record_id)
    if record is None:
        raise _registry_failure(
            NotFound,
            code="config_registry.source_record_not_found",
            category=ProblemCategory.NOT_FOUND,
            message="config registry source record was not found",
            location=StorageLocation(
                run_id=source_manifest.run_id,
                path=("records", record_id),
            ),
            related_locations=(_registry_model_location("record_id"),),
            details={"record_id": record_id},
        )
    if record.kind != kind:
        raise _registry_failure(
            CheckFailed,
            code="config_registry.source_record_kind_mismatch",
            category=ProblemCategory.INVALID_INPUT,
            message="config registry source record has the wrong kind",
            location=StorageLocation(
                run_id=source_manifest.run_id,
                path=("records", record_id, "kind"),
            ),
            related_locations=(_registry_model_location("record_id"),),
            details={
                "record_id": record_id,
                "actual_kind": record.kind,
                "expected_kind": kind,
            },
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
            raise _registry_failure(
                Conflict,
                code="config_registry.duplicate_entry",
                category=ProblemCategory.CONFLICT,
                message="config registry entry id is already committed differently",
                location=_registry_model_location("entry_id"),
                related_locations=(
                    _registry_storage_location(_entry_refs(existing.id).entry_ref),
                ),
                details={"entry_id": requested_entry.id},
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
    if _path_exists(entry_path, ref=refs.entry_ref):
        entry = _read_config_registry_entry_file_locked(
            entry_id=entry_id,
            workspace=workspace,
        )
        if indexed_entry is not None and indexed_entry != entry:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.index_entry_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message=(
                    "config registry entry does not match its committed index record"
                ),
                location=_registry_storage_location(CONFIG_REGISTRY_INDEX_REF),
                related_locations=(_registry_storage_location(refs.entry_ref),),
                details={"entry_id": entry_id},
            )
        return entry
    if indexed_entry is not None:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.incomplete_entry",
            category=ProblemCategory.DATA_INTEGRITY,
            message="committed config registry entry file is missing",
            location=_registry_storage_location(refs.entry_ref),
            related_locations=(_registry_storage_location(CONFIG_REGISTRY_INDEX_REF),),
            details={"entry_id": entry_id},
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
    if not _path_exists(index_path, ref=CONFIG_REGISTRY_INDEX_REF):
        return ConfigRegistryIndex()
    index = _read_model(
        index_path,
        ConfigRegistryIndex,
        CONFIG_REGISTRY_INDEX_REF,
    )
    for entry in index.entries:
        _validate_durable_entry_id(entry.id, ref=CONFIG_REGISTRY_INDEX_REF)
    return index


def _read_active_state_optional(workspace: Path) -> ConfigRegistryActiveState | None:
    active_path = workspace / CONFIG_REGISTRY_ACTIVE_REF
    if not _path_exists(active_path, ref=CONFIG_REGISTRY_ACTIVE_REF):
        return None
    return _read_active_state(active_path)


@contextmanager
def _registry_lock(workspace: Path) -> Generator[None]:
    lock_path = _workspace_relative_path(workspace, CONFIG_REGISTRY_LOCK_REF)
    lock_file = None
    try:
        ensure_durable_directory(lock_path.parent)
        lock_file = lock_path.open("a+b")
        flock(lock_file.fileno(), LOCK_EX)
    except OSError as error:
        if lock_file is not None:
            with suppress(OSError):
                lock_file.close()
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not acquire the config registry lock",
            location=_registry_storage_location(CONFIG_REGISTRY_LOCK_REF),
        ) from error
    assert lock_file is not None
    try:
        yield
    finally:
        try:
            flock(lock_file.fileno(), LOCK_UN)
            lock_file.close()
        except OSError as error:
            raise _registry_failure(
                StorageError,
                code="config_registry.storage_failed",
                category=ProblemCategory.STORAGE,
                message="storage could not release the config registry lock",
                location=_registry_storage_location(CONFIG_REGISTRY_LOCK_REF),
            ) from error


def _require_expected_generation(
    state: ConfigRegistryActiveState | None,
    expected_generation: int,
) -> None:
    current_generation = 0 if state is None else state.generation
    if expected_generation == current_generation:
        return
    raise _registry_failure(
        Conflict,
        code="config_registry.conflict",
        category=ProblemCategory.CONFLICT,
        message="config registry active state changed",
        location=_registry_model_location("expected_generation"),
        related_locations=(_registry_storage_location(CONFIG_REGISTRY_ACTIVE_REF),),
        details={
            "expected_generation": expected_generation,
            "actual_generation": current_generation,
        },
    )


def _state_generation(state: ConfigRegistryActiveState | None) -> int:
    return 0 if state is None else state.generation


def _read_active_state(path: Path) -> ConfigRegistryActiveState:
    content = _read_registry_text(path, ref=CONFIG_REGISTRY_ACTIVE_REF)
    try:
        state = ConfigRegistryActiveState.model_validate_json(content)
    except ValidationError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.active_state_invalid",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry active state does not match its durable schema",
            location=_registry_storage_location(CONFIG_REGISTRY_ACTIVE_REF),
        ) from error
    _validate_durable_entry_id(
        state.active_entry_id,
        ref=CONFIG_REGISTRY_ACTIVE_REF,
    )
    for record in state.history:
        _validate_durable_entry_id(record.entry_id, ref=CONFIG_REGISTRY_ACTIVE_REF)
        if record.previous_entry_id is not None:
            _validate_durable_entry_id(
                record.previous_entry_id,
                ref=CONFIG_REGISTRY_ACTIVE_REF,
            )
    return state


def _read_config(path: Path, ref: str) -> ConfigProfileSnapshot:
    content = _read_registry_text(path, ref=ref)
    try:
        return ConfigProfileSnapshot.model_validate_json(content)
    except ValidationError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.config_invalid",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry snapshot does not match its durable schema",
            location=_registry_storage_location(ref),
        ) from error


def _read_entry_config(
    workspace: Path,
    entry: ConfigRegistryEntry,
) -> ConfigProfileSnapshot:
    config_path = _config_registry_config_path(workspace, entry.config_ref)
    config = _read_config(config_path, entry.config_ref)
    actual_hash = config_content_hash(config)
    if actual_hash != entry.content_hash:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.content_hash_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry snapshot does not match its registered hash",
            location=_registry_storage_location(entry.config_ref),
            related_locations=(
                _registry_storage_location(_entry_refs(entry.id).entry_ref),
            ),
            details={
                "entry_id": entry.id,
                "expected_content_hash": entry.content_hash,
                "actual_content_hash": actual_hash,
            },
        )
    return config


def _validate_active_entry_identity(
    state: ConfigRegistryActiveState,
    entry: ConfigRegistryEntry,
) -> None:
    if state.active_entry_content_hash == entry.content_hash:
        return
    raise _registry_failure(
        DataIntegrityError,
        code="config_registry.active_content_mismatch",
        category=ProblemCategory.DATA_INTEGRITY,
        message="active config registry state does not match its entry",
        location=_registry_storage_location(CONFIG_REGISTRY_ACTIVE_REF),
        related_locations=(
            _registry_storage_location(_entry_refs(entry.id).entry_ref),
        ),
        details={"entry_id": entry.id},
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
    raise _registry_failure(
        Conflict,
        code="config_registry.stale_candidate",
        category=ProblemCategory.CONFLICT,
        message="candidate config was based on a different active config",
        location=_registry_model_location(
            "entries",
            entry.id,
            "source",
            "base_config_content_hash",
        ),
        related_locations=(_registry_storage_location(CONFIG_REGISTRY_ACTIVE_REF),),
        details={
            "entry_id": entry.id,
            "candidate_base_content_hash": entry.source.base_config_content_hash,
            "active_content_hash": active_entry.content_hash,
        },
    )


def _validate_entry_config(workspace: Path, entry: ConfigRegistryEntry) -> None:
    config = _read_entry_config(workspace, entry)
    problems = validate_config(config)
    if has_blocking_problems(problems):
        raise CheckFailed(problems)


def _previous_distinct_activation(
    state: ConfigRegistryActiveState,
) -> ConfigRegistryActivationRecord:
    for record in reversed(state.history[:-1]):
        if record.entry_id != state.active_entry_id:
            return record
    raise _registry_failure(
        Conflict,
        code="config_registry.no_rollback_target",
        category=ProblemCategory.CONFLICT,
        message="config registry has no previous active entry",
        location=_registry_model_location("active"),
    )


def _next_record_id(history: list[ConfigRegistryActivationRecord], action: str) -> str:
    index = len(history) + 1
    return f"{action}-{index:06d}"


def _read_model[TModel: BaseModel](
    path: Path, model_type: type[TModel], ref: str
) -> TModel:
    content = _read_registry_text(path, ref=ref)
    try:
        return model_type.model_validate_json(content)
    except ValidationError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_invalid",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record does not match its durable schema",
            location=_registry_storage_location(ref),
            details={"model": model_type.__name__},
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
    ref = _workspace_ref(path)
    try:
        _write_local_model_atomic(path, model)
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not persist a config registry record",
            location=_registry_storage_location(ref),
        ) from error
    except (PydanticSerializationError, TypeError, ValueError) as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_not_serializable",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record cannot be represented durably",
            location=_registry_storage_location(ref),
            details={"model": type(model).__name__},
        ) from error


def _workspace_relative_path(workspace: Path, ref: str) -> Path:
    relative = PurePosixPath(ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.path_escape",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry ref escapes the workspace",
            location=_registry_model_location("ref"),
            details={"ref": ref},
        )
    candidate = workspace / relative.as_posix()
    try:
        workspace_root = workspace.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not resolve a config registry path",
            location=_registry_storage_location(ref),
        ) from error
    try:
        resolved.relative_to(workspace_root)
    except ValueError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.path_escape",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry ref escapes the workspace",
            location=_registry_model_location("ref"),
            details={"ref": ref},
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
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.config_ref_invalid",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry config ref is outside the config store",
            location=_registry_model_location("config_ref"),
            details={"ref": ref},
        )
    return _workspace_relative_path(workspace, ref)


def _path_exists(path: Path, *, ref: str) -> bool:
    try:
        path.stat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not inspect a config registry record",
            location=_registry_storage_location(ref),
        ) from error
    return True


def _read_registry_text(path: Path, *, ref: str) -> str:
    try:
        path_stat = path.stat()
    except FileNotFoundError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry is missing a referenced durable record",
            location=_registry_storage_location(ref),
        ) from error
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not inspect a config registry record",
            location=_registry_storage_location(ref),
        ) from error
    if not S_ISREG(path_stat.st_mode):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_not_file",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record is not a regular file",
            location=_registry_storage_location(ref),
        )
    try:
        return path.read_text()
    except FileNotFoundError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry is missing a referenced durable record",
            location=_registry_storage_location(ref),
        ) from error
    except UnicodeError as error:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.record_invalid_encoding",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry record is not valid text",
            location=_registry_storage_location(ref),
        ) from error
    except OSError as error:
        raise _registry_failure(
            StorageError,
            code="config_registry.storage_failed",
            category=ProblemCategory.STORAGE,
            message="storage could not read a config registry record",
            location=_registry_storage_location(ref),
        ) from error


def _workspace_ref(path: Path) -> str:
    try:
        root_index = path.parts.index(CONFIG_REGISTRY_ROOT)
    except ValueError:
        return path.name
    return PurePosixPath(*path.parts[root_index:]).as_posix()


def _registry_failure(
    failure_type: type[ProblemFailure],
    *,
    code: str,
    category: ProblemCategory,
    message: str,
    location: ProblemLocation | None = None,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
) -> ProblemFailure:
    return failure_type(
        [
            Problem(
                code=code,
                impact=ProblemImpact.BLOCKING,
                category=category,
                phase=ProblemPhase.CONFIGURATION,
                message=message,
                location=location,
                related_locations=tuple(related_locations),
                details={} if details is None else details,
            )
        ]
    )


def _registry_model_location(*path: str | int) -> ModelLocation:
    return ModelLocation(root="config_registry", path=path)


def _registry_storage_location(
    ref: str,
    *,
    run_id: str | None = None,
) -> StorageLocation:
    return StorageLocation(run_id=run_id, ref=ref)
