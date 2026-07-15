"""Configuration-registry use cases and persistence ports.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.config.changes import ParameterChangeDecisionRecord
from scopecat.config.parameter_updates import merge_candidate_parameter_snapshots
from scopecat.config.registry.ports import (
    ConfigRegistryRepository,
    WorkspaceUnitOfWork,
    WorkspaceUnitOfWorkFactory,
)
from scopecat.config.registry.records import (
    CandidateConfigRegistrySource,
    CandidateProposalRegistryEvidence,
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    ConfigRegistryIndex,
    DirectConfigRegistrySource,
    EvidenceContentHash,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    ProblemFailure,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    has_blocking_problems,
)
from scopecat.planning.validation import validate_config
from scopecat.records.artifact import RunRecordEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_equal,
    config_content_hash,
)
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF, record_content_ref
from scopecat.runs.repository import RunRepository

ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR = "active"
SAFE_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class _ValidatedCandidateSource:
    config: ConfigProfileSnapshot
    source: CandidateConfigRegistrySource


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: WorkspaceUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    with unit_of_work() as work:
        return _register_config_profile_locked(
            config=config,
            work=work,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )


def register_and_activate_config_profile(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: WorkspaceUnitOfWorkFactory,
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
    selected_generation = (
        current_config_registry_generation(unit_of_work=unit_of_work)
        if expected_generation is None
        else expected_generation
    )
    selected_activation_note = note if activation_note is None else activation_note
    with unit_of_work() as work:
        current_state = _read_active_state_optional(work.registry)
        if (
            _matching_active_state_retry(
                current_state,
                action="activation",
                entry_id=entry_id,
                operator=operator,
                note=selected_activation_note,
                expected_generation=selected_generation,
                allow_current_generation=True,
            )
            is None
        ):
            _require_expected_generation(
                current_state,
                selected_generation,
                active_ref=work.registry.active_ref,
            )
        entry = _register_config_profile_locked(
            config=config,
            work=work,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )
        active_state, activation = _activate_config_registry_entry_locked(
            entry_id=entry.id,
            work=work,
            operator=operator,
            note=selected_activation_note,
            expected_generation=selected_generation,
        )
        return entry, active_state, activation


def _register_config_profile_locked(
    *,
    config: ConfigProfileSnapshot,
    work: WorkspaceUnitOfWork,
    entry_id: str,
    registered_by: str,
    note: str,
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    entry = ConfigRegistryEntry(
        id=entry_id,
        config_ref=work.registry.config_ref(entry_id),
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        registered_by=registered_by,
        note=note,
    )
    return _commit_registration_locked(
        repository=work.registry,
        requested_entry=entry,
        config=config,
    )


def register_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: WorkspaceUnitOfWorkFactory,
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
    with unit_of_work() as work:
        return _register_candidate_config_locked(
            config=config,
            work=work,
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
    unit_of_work: WorkspaceUnitOfWorkFactory,
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
    selected_activation_note = note if activation_note is None else activation_note
    with unit_of_work() as work:
        current_state = _read_active_state_optional(work.registry)
        if (
            _matching_active_state_retry(
                current_state,
                action="activation",
                entry_id=entry_id,
                operator=operator,
                note=selected_activation_note,
                expected_generation=expected_generation,
                allow_current_generation=True,
            )
            is None
        ):
            _require_expected_generation(
                current_state,
                expected_generation,
                active_ref=work.registry.active_ref,
            )
        entry = _register_candidate_config_locked(
            config=config,
            work=work,
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
            work=work,
            operator=operator,
            note=selected_activation_note,
            expected_generation=expected_generation,
        )
        return entry, active_state, activation


def _register_candidate_config_locked(
    *,
    config: ConfigProfileSnapshot,
    work: WorkspaceUnitOfWork,
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
    with work.runs.run_lock(run_id):
        validated = _validate_candidate_source_records_locked(
            storage=work.runs,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            requested_config=config,
        )
        durable_config = validated.config
        entry = ConfigRegistryEntry(
            id=entry_id,
            config_ref=work.registry.config_ref(entry_id),
            content_hash=config_content_hash(durable_config),
            source=validated.source,
            registered_by=registered_by,
            note=note,
        )
        return _commit_registration_locked(
            repository=work.registry,
            requested_entry=entry,
            config=durable_config,
        )


def _validate_candidate_source_records(
    *,
    work: WorkspaceUnitOfWork,
    run_id: str,
    proposal_ids: Sequence[str],
    candidate_record_id: str,
    base_config_content_hash: ConfigContentHash,
    requested_config: ConfigProfileSnapshot,
) -> _ValidatedCandidateSource:
    with work.runs.run_lock(run_id):
        return _validate_candidate_source_records_locked(
            storage=work.runs,
            run_id=run_id,
            proposal_ids=proposal_ids,
            candidate_record_id=candidate_record_id,
            base_config_content_hash=base_config_content_hash,
            requested_config=requested_config,
        )


def _validate_candidate_source_records_locked(
    *,
    storage: RunRepository,
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
    storage: RunRepository,
    source_manifest: RunManifest,
    run_id: str,
    proposal_ids: Sequence[str],
    proposal_hashes: Mapping[str, EvidenceContentHash],
) -> tuple[CandidateProposalRegistryEvidence, ...]:
    histories: dict[
        str,
        list[tuple[RunRecordEntry, ParameterChangeDecisionRecord]],
    ] = {proposal_id: [] for proposal_id in proposal_ids}
    for entry in source_manifest.records:
        if entry.kind != "parameter_change_decision_record":
            continue
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
    work: WorkspaceUnitOfWork,
    entry: ConfigRegistryEntry,
    config: ConfigProfileSnapshot,
) -> None:
    if not isinstance(entry.source, CandidateConfigRegistrySource):
        return
    validated = _validate_candidate_source_records(
        work=work,
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


def list_config_registry_entries(
    *, unit_of_work: WorkspaceUnitOfWorkFactory
) -> list[ConfigRegistryEntry]:
    with unit_of_work() as work:
        index = _read_index(work.registry)
        entries = [
            _validate_indexed_entry_locked(
                work=work,
                indexed_entry=indexed_entry,
            )
            for indexed_entry in index.entries
        ]
        return sorted(entries, key=lambda entry: entry.registered_at)


def load_config_registry_entry(
    *, entry_id: str, unit_of_work: WorkspaceUnitOfWorkFactory
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    with unit_of_work() as work:
        return _load_config_registry_entry_locked(
            entry_id=entry_id,
            work=work,
        )


def _load_config_registry_entry_locked(
    *, entry_id: str, work: WorkspaceUnitOfWork
) -> ConfigRegistryEntry:
    entry = _load_committed_config_registry_entry_locked(
        entry_id=entry_id,
        work=work,
    )
    config = _read_entry_config(work.registry, entry)
    _validate_candidate_entry_evidence_locked(
        work=work,
        entry=entry,
        config=config,
    )
    return entry


def _load_committed_config_registry_entry_locked(
    *, entry_id: str, work: WorkspaceUnitOfWork
) -> ConfigRegistryEntry:
    """Load committed registry identity without re-evaluating source evidence."""

    index = _read_index(work.registry)
    indexed_entry = next(
        (entry for entry in index.entries if entry.id == entry_id),
        None,
    )
    if indexed_entry is None:
        entry_ref = work.registry.entry_ref(entry_id)
        if work.registry.entry_exists(entry_id):
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.uncommitted_entry",
                category=ProblemCategory.DATA_INTEGRITY,
                message="config registry entry exists without an index commit",
                location=_registry_storage_location(entry_ref),
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
    return _validate_indexed_entry_identity_locked(
        repository=work.registry,
        indexed_entry=indexed_entry,
    )


def _validate_indexed_entry_locked(
    *,
    work: WorkspaceUnitOfWork,
    indexed_entry: ConfigRegistryEntry,
) -> ConfigRegistryEntry:
    entry = _validate_indexed_entry_identity_locked(
        repository=work.registry,
        indexed_entry=indexed_entry,
    )
    config = _read_entry_config(work.registry, entry)
    _validate_candidate_entry_evidence_locked(
        work=work,
        entry=entry,
        config=config,
    )
    return entry


def _validate_indexed_entry_identity_locked(
    *,
    repository: ConfigRegistryRepository,
    indexed_entry: ConfigRegistryEntry,
) -> ConfigRegistryEntry:
    entry = _read_config_registry_entry_file_locked(
        entry_id=indexed_entry.id,
        repository=repository,
    )
    if entry != indexed_entry:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.index_entry_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry entry does not match its committed index record",
            location=_registry_storage_location(repository.index_ref),
            related_locations=(
                _registry_storage_location(repository.entry_ref(entry.id)),
            ),
            details={"entry_id": entry.id},
        )
    return entry


def _read_config_registry_entry_file_locked(
    *, entry_id: str, repository: ConfigRegistryRepository
) -> ConfigRegistryEntry:
    _validate_durable_entry_id(entry_id, ref=repository.index_ref)
    entry_ref = repository.entry_ref(entry_id)
    if not repository.entry_exists(entry_id):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.entry_missing",
            category=ProblemCategory.DATA_INTEGRITY,
            message="committed config registry entry file is missing",
            location=_registry_storage_location(entry_ref),
            details={"entry_id": entry_id},
        )
    entry = repository.read_entry(entry_id)
    if entry.id != entry_id or entry.config_ref != repository.config_ref(entry_id):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.entry_ref_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry entry has inconsistent storage coordinates",
            location=_registry_storage_location(entry_ref),
            related_locations=(_registry_model_location("config_ref"),),
            details={"entry_id": entry_id},
        )
    return entry


def load_config_registry_config(
    *, entry_id: str, unit_of_work: WorkspaceUnitOfWorkFactory
) -> ConfigProfileSnapshot:
    _validate_entry_id(entry_id)
    with unit_of_work() as work:
        entry = _load_config_registry_entry_locked(
            entry_id=entry_id,
            work=work,
        )
        return _read_entry_config(work.registry, entry)


def load_active_config_registry_config(
    *, unit_of_work: WorkspaceUnitOfWorkFactory
) -> ConfigProfileSnapshot:
    with unit_of_work() as work:
        state = _load_active_config_registry_state_locked(work.registry)
        entry = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, state, entry)
        return _read_entry_config(work.registry, entry)


def resolve_config_registry_config_source(
    *, selector: str, unit_of_work: WorkspaceUnitOfWorkFactory
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    if selector != ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR:
        _validate_entry_id(selector)
    with unit_of_work() as work:
        if selector == ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR:
            return _resolve_active_config_registry_config_source_locked(work=work)
        return _resolve_entry_config_registry_config_source_locked(
            selector=selector,
            work=work,
        )


def activate_config_registry_entry(
    *,
    entry_id: str,
    unit_of_work: WorkspaceUnitOfWorkFactory,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    _validate_entry_id(entry_id)
    _validate_required_text(operator, field="operator")
    with unit_of_work() as work:
        return _activate_config_registry_entry_locked(
            entry_id=entry_id,
            work=work,
            operator=operator,
            expected_generation=expected_generation,
            note=note,
        )


def _activate_config_registry_entry_locked(
    *,
    entry_id: str,
    work: WorkspaceUnitOfWork,
    operator: str,
    expected_generation: int,
    note: str,
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    current_state = _read_active_state_optional(work.registry)
    repeated = _matching_active_state_retry(
        current_state,
        action="activation",
        entry_id=entry_id,
        operator=operator,
        note=note,
        expected_generation=expected_generation,
        allow_current_generation=True,
    )
    if repeated is not None:
        assert current_state is not None
        entry = _load_config_registry_entry_locked(
            entry_id=entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, current_state, entry)
        _validate_entry_config(work.registry, entry)
        work.registry.commit_active_state(current_state)
        return current_state, repeated
    _require_expected_generation(
        current_state,
        expected_generation,
        active_ref=work.registry.active_ref,
    )
    entry = _load_config_registry_entry_locked(
        entry_id=entry_id,
        work=work,
    )
    _validate_candidate_base(current_state, entry, work)
    _validate_entry_config(work.registry, entry)
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
    work.registry.commit_active_state(state)
    return state, record


def rollback_config_registry(
    *,
    unit_of_work: WorkspaceUnitOfWorkFactory,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    _validate_required_text(operator, field="operator")
    with unit_of_work() as work:
        current_state = _read_active_state_optional(work.registry)
        repeated = _matching_active_state_retry(
            current_state,
            action="rollback",
            entry_id=None,
            operator=operator,
            note=note,
            expected_generation=expected_generation,
        )
        if repeated is not None:
            assert current_state is not None
            _load_current_active_entry_for_rollback_locked(
                state=current_state,
                work=work,
            )
            work.registry.commit_active_state(current_state)
            return current_state, repeated
        _require_expected_generation(
            current_state,
            expected_generation,
            active_ref=work.registry.active_ref,
        )
        if current_state is None:
            raise _registry_failure(
                NotFound,
                code="config_registry.no_active_entry",
                category=ProblemCategory.NOT_FOUND,
                message="config registry has no active entry",
                location=_registry_model_location("active"),
            )
        _load_current_active_entry_for_rollback_locked(
            state=current_state,
            work=work,
        )
        rollback_target = _previous_distinct_activation(current_state)
        entry = _load_config_registry_entry_locked(
            entry_id=rollback_target.entry_id,
            work=work,
        )
        _validate_entry_config(work.registry, entry)
        if entry.content_hash != rollback_target.entry_content_hash:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.rollback_content_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message="rollback target no longer matches activation history",
                location=_registry_storage_location(work.registry.active_ref),
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
        work.registry.commit_active_state(state)
        return state, record


def _load_current_active_entry_for_rollback_locked(
    *,
    state: ConfigRegistryActiveState,
    work: WorkspaceUnitOfWork,
) -> ConfigRegistryEntry:
    """Validate the entry being left without blocking emergency rollback.

    A candidate may be rejected or invalidated after it became active. That
    later review state must prevent future selection, but it must not trap the
    active selector on the now-disallowed candidate. The committed index,
    entry coordinates, active-state identity, and config content hash remain
    mandatory here. The rollback target still goes through the complete
    candidate-evidence validation in ``_load_config_registry_entry_locked``.
    """

    entry = _load_committed_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        work=work,
    )
    _validate_active_entry_identity(work.registry, state, entry)
    _read_entry_config(work.registry, entry)
    return entry


def current_config_registry_generation(
    *, unit_of_work: WorkspaceUnitOfWorkFactory
) -> int:
    with unit_of_work() as work:
        return _state_generation(_read_active_state_optional(work.registry))


def load_active_config_registry_state(
    *, unit_of_work: WorkspaceUnitOfWorkFactory
) -> ConfigRegistryActiveState:
    with unit_of_work() as work:
        return _load_active_config_registry_state_locked(work.registry)


def _load_active_config_registry_state_locked(
    repository: ConfigRegistryRepository,
) -> ConfigRegistryActiveState:
    state = repository.read_active_state()
    if state is None:
        raise _registry_failure(
            NotFound,
            code="config_registry.no_active_entry",
            category=ProblemCategory.NOT_FOUND,
            message="config registry has no active entry",
            location=_registry_model_location("active"),
        )
    _validate_active_state_entry_ids(state, ref=repository.active_ref)
    return state


def load_active_config_registry_entry(
    *, unit_of_work: WorkspaceUnitOfWorkFactory
) -> ConfigRegistryEntry:
    with unit_of_work() as work:
        state = _load_active_config_registry_state_locked(work.registry)
        entry = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, state, entry)
        _read_entry_config(work.registry, entry)
        return entry


def _resolve_entry_config_registry_config_source_locked(
    *, selector: str, work: WorkspaceUnitOfWork
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    entry = _load_config_registry_entry_locked(
        entry_id=selector,
        work=work,
    )
    config = _read_entry_config(work.registry, entry)
    source = RunConfigSource(
        selector=selector,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
    )
    return config, source


def _resolve_active_config_registry_config_source_locked(
    *, work: WorkspaceUnitOfWork
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    state = _load_active_config_registry_state_locked(work.registry)
    entry = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        work=work,
    )
    _validate_active_entry_identity(work.registry, state, entry)
    config = _read_entry_config(work.registry, entry)
    source = RunConfigSource(
        selector=ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
        registry_generation=state.generation,
    )
    return config, source


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
    record = next(
        (entry for entry in source_manifest.records if entry.id == record_id),
        None,
    )
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
    repository: ConfigRegistryRepository,
    requested_entry: ConfigRegistryEntry,
    config: ConfigProfileSnapshot,
) -> ConfigRegistryEntry:
    index = _read_index(repository)
    existing = _find_existing_entry_locked(
        repository=repository,
        index=index,
        entry_id=requested_entry.id,
    )
    if existing is not None:
        existing_config = _read_entry_config(repository, existing)
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
                    _registry_storage_location(repository.entry_ref(existing.id)),
                ),
                details={"entry_id": requested_entry.id},
            )
        repository.commit_registration(
            index=index,
            entry=existing,
            config=existing_config,
        )
        return existing
    repository.commit_registration(
        index=index,
        entry=requested_entry,
        config=config,
    )
    return requested_entry


def _find_existing_entry_locked(
    *,
    repository: ConfigRegistryRepository,
    index: ConfigRegistryIndex,
    entry_id: str,
) -> ConfigRegistryEntry | None:
    entry_ref = repository.entry_ref(entry_id)
    indexed_entry = next(
        (entry for entry in index.entries if entry.id == entry_id),
        None,
    )
    if repository.entry_exists(entry_id):
        entry = _read_config_registry_entry_file_locked(
            entry_id=entry_id,
            repository=repository,
        )
        if indexed_entry is not None and indexed_entry != entry:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.index_entry_mismatch",
                category=ProblemCategory.DATA_INTEGRITY,
                message=(
                    "config registry entry does not match its committed index record"
                ),
                location=_registry_storage_location(repository.index_ref),
                related_locations=(_registry_storage_location(entry_ref),),
                details={"entry_id": entry_id},
            )
        return entry
    if indexed_entry is not None:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.incomplete_entry",
            category=ProblemCategory.DATA_INTEGRITY,
            message="committed config registry entry file is missing",
            location=_registry_storage_location(entry_ref),
            related_locations=(_registry_storage_location(repository.index_ref),),
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


def _read_index(repository: ConfigRegistryRepository) -> ConfigRegistryIndex:
    index = repository.read_index()
    for entry in index.entries:
        _validate_durable_entry_id(entry.id, ref=repository.index_ref)
    return index


def _read_active_state_optional(
    repository: ConfigRegistryRepository,
) -> ConfigRegistryActiveState | None:
    state = repository.read_active_state()
    if state is None:
        return None
    _validate_active_state_entry_ids(state, ref=repository.active_ref)
    return state


def _require_expected_generation(
    state: ConfigRegistryActiveState | None,
    expected_generation: int,
    *,
    active_ref: str,
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
        related_locations=(_registry_storage_location(active_ref),),
        details={
            "expected_generation": expected_generation,
            "actual_generation": current_generation,
        },
    )


def _matching_active_state_retry(
    state: ConfigRegistryActiveState | None,
    *,
    action: str,
    entry_id: str | None,
    operator: str,
    note: str,
    expected_generation: int,
    allow_current_generation: bool = False,
) -> ConfigRegistryActivationRecord | None:
    """Recognize a matching request at one recoverable visible generation."""

    if state is None:
        return None
    post_replace_retry = state.generation == expected_generation + 1
    reread_generation_retry = (
        allow_current_generation and state.generation == expected_generation
    )
    if not (post_replace_retry or reread_generation_retry):
        return None
    return _matching_latest_active_request(
        state,
        action=action,
        entry_id=entry_id,
        operator=operator,
        note=note,
    )


def _matching_latest_active_request(
    state: ConfigRegistryActiveState | None,
    *,
    action: str,
    entry_id: str | None,
    operator: str,
    note: str,
) -> ConfigRegistryActivationRecord | None:
    if state is None:
        return None
    latest = state.history[-1]
    if (
        latest.action != action
        or latest.operator != operator
        or latest.note != note
        or (entry_id is not None and latest.entry_id != entry_id)
    ):
        return None
    return latest


def _state_generation(state: ConfigRegistryActiveState | None) -> int:
    return 0 if state is None else state.generation


def _validate_active_state_entry_ids(
    state: ConfigRegistryActiveState,
    *,
    ref: str,
) -> None:
    _validate_durable_entry_id(
        state.active_entry_id,
        ref=ref,
    )
    for record in state.history:
        _validate_durable_entry_id(record.entry_id, ref=ref)
        if record.previous_entry_id is not None:
            _validate_durable_entry_id(
                record.previous_entry_id,
                ref=ref,
            )


def _read_entry_config(
    repository: ConfigRegistryRepository,
    entry: ConfigRegistryEntry,
) -> ConfigProfileSnapshot:
    config = repository.read_config(entry.config_ref)
    actual_hash = config_content_hash(config)
    if actual_hash != entry.content_hash:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.content_hash_mismatch",
            category=ProblemCategory.DATA_INTEGRITY,
            message="config registry snapshot does not match its registered hash",
            location=_registry_storage_location(entry.config_ref),
            related_locations=(
                _registry_storage_location(repository.entry_ref(entry.id)),
            ),
            details={
                "entry_id": entry.id,
                "expected_content_hash": entry.content_hash,
                "actual_content_hash": actual_hash,
            },
        )
    return config


def _validate_active_entry_identity(
    repository: ConfigRegistryRepository,
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
        location=_registry_storage_location(repository.active_ref),
        related_locations=(_registry_storage_location(repository.entry_ref(entry.id)),),
        details={"entry_id": entry.id},
    )


def _validate_candidate_base(
    state: ConfigRegistryActiveState | None,
    entry: ConfigRegistryEntry,
    work: WorkspaceUnitOfWork,
) -> None:
    if state is None:
        return
    active_entry = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        work=work,
    )
    _validate_active_entry_identity(work.registry, state, active_entry)
    _read_entry_config(work.registry, active_entry)
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
        related_locations=(_registry_storage_location(work.registry.active_ref),),
        details={
            "entry_id": entry.id,
            "candidate_base_content_hash": entry.source.base_config_content_hash,
            "active_content_hash": active_entry.content_hash,
        },
    )


def _validate_entry_config(
    repository: ConfigRegistryRepository,
    entry: ConfigRegistryEntry,
) -> None:
    config = _read_entry_config(repository, entry)
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


__all__ = [
    "ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR",
    "ConfigRegistryRepository",
    "WorkspaceUnitOfWork",
    "WorkspaceUnitOfWorkFactory",
    "activate_config_registry_entry",
    "current_config_registry_generation",
    "list_config_registry_entries",
    "load_active_config_registry_config",
    "load_active_config_registry_entry",
    "load_active_config_registry_state",
    "load_config_registry_config",
    "load_config_registry_entry",
    "register_and_activate_candidate_config",
    "register_and_activate_config_profile",
    "register_candidate_config",
    "register_config_profile",
    "resolve_config_registry_config_source",
    "rollback_config_registry",
]
