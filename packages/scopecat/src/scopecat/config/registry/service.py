"""Configuration-registry use cases and persistence ports.

The registry stores named configuration snapshots under the project-local
``config-registry`` tree. Its append-only activation log projects the active
entry for later runs and supplies an independent history view for rollback.
Entries can be registered directly from a
``ConfigProfileSnapshot`` or from a candidate configuration.

Runs started from a registry entry carry source coordinates on the run
manifest. Reporting code can then show which registry selector and entry were
used without mixing run lifecycle data into the config snapshot. Candidate
evidence is verified and frozen at registration; later review events do not
retroactively revoke committed entries.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_from_snapshot,
)
from scopecat.config.drafts import ConfigDraft, ConfigDraftCheckResult
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.profile_validation import validate_config_profile
from scopecat.config.registry.ports import (
    ConfigRegistryRepository,
    ConfigRegistryUnitOfWork,
    ConfigRegistryUnitOfWorkFactory,
)
from scopecat.config.registry.records import (
    CandidateConfigRegistrySource,
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
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
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_equal,
    config_content_hash,
)
from scopecat.records.parameter_change import (
    ParameterChangeApprovalRecord,
    ParameterChangeProposal,
)
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunConfigSource,
    RunManifest,
)
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import RunRepository

ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR = "active"
SAFE_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class _ValidatedCandidateSource:
    config: ConfigProfileSnapshot
    source: CandidateConfigRegistrySource


@dataclass(frozen=True, slots=True)
class ConfigRegistryEntrySnapshot:
    entry: ConfigRegistryEntry
    config: ConfigProfileSnapshot


@dataclass(frozen=True, slots=True)
class ConfigRegistrySnapshot:
    entries: tuple[ConfigRegistryEntry, ...]
    active_state: ConfigRegistryActiveState | None


@dataclass(frozen=True, slots=True)
class ActiveConfigRegistrySnapshot:
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    config: ConfigProfileSnapshot


@dataclass(frozen=True, slots=True)
class ManualConfigDraftResult:
    """One daemon-authoritative check against an observed active entry."""

    base_entry: ConfigRegistryEntry
    base_generation: int
    check: ConfigDraftCheckResult


def preview_manual_config_draft(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: Sequence[ParameterUpdate],
) -> ManualConfigDraftResult:
    """Check transient typed edits without committing registry state."""

    with unit_of_work() as work:
        return _check_manual_config_draft_locked(
            work=work,
            base_entry_id=base_entry_id,
            base_config_content_hash=base_config_content_hash,
            base_generation=base_generation,
            candidate_id=candidate_id,
            updates=updates,
        )


def register_manual_config_draft(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: Sequence[ParameterUpdate],
    expected_result_content_hash: ConfigContentHash,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> tuple[ConfigRegistryEntry, ManualConfigDraftResult]:
    """Recheck and atomically register typed edits without activating them."""

    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    with unit_of_work() as work:
        return _register_manual_config_draft_locked(
            work=work,
            base_entry_id=base_entry_id,
            base_config_content_hash=base_config_content_hash,
            base_generation=base_generation,
            candidate_id=candidate_id,
            updates=updates,
            expected_result_content_hash=expected_result_content_hash,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )


def register_and_activate_manual_config_draft(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: Sequence[ParameterUpdate],
    expected_result_content_hash: ConfigContentHash,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
) -> tuple[
    ConfigRegistryEntry,
    ManualConfigDraftResult,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    """Recheck typed edits, save one revision, and select it as the default."""

    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(operator, field="operator")
    selected_activation_note = note if activation_note is None else activation_note
    with unit_of_work() as work:
        entry, result = _register_manual_config_draft_locked(
            work=work,
            base_entry_id=base_entry_id,
            base_config_content_hash=base_config_content_hash,
            base_generation=base_generation,
            candidate_id=candidate_id,
            updates=updates,
            expected_result_content_hash=expected_result_content_hash,
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        )
        state, activation = _activate_config_registry_entry_locked(
            entry_id=entry.id,
            work=work,
            operator=operator,
            expected_generation=base_generation,
            note=selected_activation_note,
        )
        return entry, result, state, activation


def _register_manual_config_draft_locked(
    *,
    work: ConfigRegistryUnitOfWork,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: Sequence[ParameterUpdate],
    expected_result_content_hash: ConfigContentHash,
    entry_id: str,
    registered_by: str,
    note: str,
) -> tuple[ConfigRegistryEntry, ManualConfigDraftResult]:
    result = _check_manual_config_draft_locked(
        work=work,
        base_entry_id=base_entry_id,
        base_config_content_hash=base_config_content_hash,
        base_generation=base_generation,
        candidate_id=candidate_id,
        updates=updates,
    )
    if not result.check.ok:
        raise CheckFailed(result.check.problems)
    candidate = result.check.candidate
    assert candidate is not None
    result_content_hash = config_content_hash(candidate)
    if result_content_hash != expected_result_content_hash:
        raise _registry_failure(
            Conflict,
            code="config_registry.config_draft_result_changed",
            message="config draft result changed since it was previewed",
            location=_registry_model_location("expected_result_content_hash"),
            details={
                "expected_content_hash": expected_result_content_hash,
                "actual_content_hash": result_content_hash,
            },
        )
    entry = ConfigRegistryEntry(
        id=entry_id,
        config_ref=work.registry.config_ref(entry_id),
        content_hash=result_content_hash,
        source=ManualConfigDraftRegistrySource(
            base_entry_id=result.base_entry.id,
            base_config_content_hash=result.base_entry.content_hash,
            base_registry_generation=result.base_generation,
        ),
        registered_by=registered_by,
        note=note,
    )
    return (
        _commit_registration_locked(
            repository=work.registry,
            requested_entry=entry,
            config=candidate,
        ),
        result,
    )


def _check_manual_config_draft_locked(
    *,
    work: ConfigRegistryUnitOfWork,
    base_entry_id: str,
    base_config_content_hash: ConfigContentHash,
    base_generation: int,
    candidate_id: str,
    updates: Sequence[ParameterUpdate],
) -> ManualConfigDraftResult:
    state = _load_active_config_registry_state_locked(work.registry)
    _require_expected_generation(
        state,
        base_generation,
        active_ref=work.registry.active_ref,
    )
    if (
        state.active_entry_id != base_entry_id
        or state.active_entry_content_hash != base_config_content_hash
    ):
        raise _registry_failure(
            Conflict,
            code="config_registry.config_draft_base_changed",
            message="config draft base is no longer the active entry",
            location=_registry_model_location("base_entry_id"),
            related_locations=(_registry_storage_location(work.registry.active_ref),),
            details={
                "expected_entry_id": base_entry_id,
                "actual_entry_id": state.active_entry_id,
                "expected_content_hash": base_config_content_hash,
                "actual_content_hash": state.active_entry_content_hash,
            },
        )
    loaded = _load_config_registry_entry_locked(entry_id=base_entry_id, work=work)
    _validate_active_entry_identity(work.registry, state, loaded.entry)
    check = ConfigDraft(loaded.config).apply(*updates).check(candidate_id=candidate_id)
    return ManualConfigDraftResult(
        base_entry=loaded.entry,
        base_generation=state.generation,
        check=check,
    )


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
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
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
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
    work: ConfigRegistryUnitOfWork,
    entry_id: str,
    registered_by: str,
    note: str,
) -> ConfigRegistryEntry:
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


def register_and_activate_candidate_config(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str | None,
    registered_by: str,
    run_id: str,
    proposal_id: str,
    operator: str,
    expected_generation: int,
    note: str = "",
    activation_note: str | None = None,
) -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    if entry_id is not None:
        _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(operator, field="operator")
    _validate_required_text(run_id, field="run_id")
    _validate_required_text(proposal_id, field="proposal_id")
    selected_activation_note = note if activation_note is None else activation_note
    with unit_of_work() as work:
        current_state = _read_active_state_optional(work.registry)
        _require_expected_generation(
            current_state,
            expected_generation,
            active_ref=work.registry.active_ref,
        )
        entry = _register_candidate_config_locked(
            work=work,
            entry_id=entry_id,
            registered_by=registered_by,
            run_id=run_id,
            proposal_id=proposal_id,
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
    work: ConfigRegistryUnitOfWork,
    entry_id: str | None,
    registered_by: str,
    run_id: str,
    proposal_id: str,
    note: str,
) -> ConfigRegistryEntry:
    validated = _validate_candidate_source_records(
        storage=work.runs,
        run_id=run_id,
        proposal_id=proposal_id,
    )
    durable_config = validated.config
    selected_entry_id = entry_id or f"{durable_config.id}-{run_id}"
    _validate_entry_id(selected_entry_id)
    entry = ConfigRegistryEntry(
        id=selected_entry_id,
        config_ref=work.registry.config_ref(selected_entry_id),
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
    storage: RunRepository,
    run_id: str,
    proposal_id: str,
) -> _ValidatedCandidateSource:
    """Validate a candidate and capture its registration-time evidence."""

    source_manifest = storage.read_manifest(run_id)
    source_config = storage.read_config_profile_snapshot(run_id)
    source_config_hash = config_content_hash(source_config)
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
        or proposal.base_config_content_hash != source_config_hash
    ):
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.candidate_proposal_mismatch",
            message="candidate proposal does not match its source config",
            location=_registry_storage_location(proposal_ref, run_id=run_id),
            related_locations=(_registry_model_location("proposal_id"),),
            details={"proposal_id": proposal_id},
        )
    approval_record_id = _require_candidate_approval(
        storage=storage,
        source_manifest=source_manifest,
        run_id=run_id,
        proposal_id=proposal_id,
    )
    durable_config = resolve_candidate_config_from_snapshot(
        CandidateConfig(parameter_proposal=proposal),
        source_config=source_config,
    )
    source = CandidateConfigRegistrySource(
        run_id=run_id,
        proposal_id=proposal_id,
        approval_record_id=approval_record_id,
        base_config_content_hash=source_config_hash,
    )
    return _ValidatedCandidateSource(config=durable_config, source=source)


def _require_candidate_approval(
    *,
    storage: RunRepository,
    source_manifest: RunManifest,
    run_id: str,
    proposal_id: str,
) -> str:
    approval_record_id = f"{proposal_id}-approval"
    approval_entry = next(
        (
            entry
            for entry in source_manifest.records
            if entry.id == approval_record_id
            and entry.kind == "parameter_change_approval_record"
        ),
        None,
    )
    if approval_entry is None:
        raise _registry_failure(
            Conflict,
            code="config_registry.candidate_proposal_not_approved",
            message="candidate proposal has not been approved",
            location=_registry_model_location("proposal_id"),
            details={"proposal_id": proposal_id},
        )
    approval_ref = record_content_ref(
        record_id=approval_entry.id,
        kind=approval_entry.kind,
    )
    approval = storage.read_model(
        run_id,
        approval_ref,
        ParameterChangeApprovalRecord,
    )
    if approval.run_id != run_id or approval.proposal_id != proposal_id:
        raise _registry_failure(
            DataIntegrityError,
            code="config_registry.candidate_approval_identity_mismatch",
            message="candidate approval identity does not match its run record",
            location=_registry_storage_location(approval_ref, run_id=run_id),
            related_locations=(_registry_model_location("proposal_id"),),
            details={"record_id": approval_entry.id},
        )
    return approval_record_id


def list_config_registry_entries(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
) -> list[ConfigRegistryEntry]:
    with unit_of_work() as work:
        return list(_list_config_registry_entries_locked(work.registry))


def load_config_registry_snapshot(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
) -> ConfigRegistrySnapshot:
    """Read the registry list and active projection in one transaction."""

    with unit_of_work() as work:
        entries = _list_config_registry_entries_locked(work.registry)
        active_state = _read_active_state_optional(work.registry)
        if active_state is not None:
            loaded = _load_config_registry_entry_locked(
                entry_id=active_state.active_entry_id,
                work=work,
            )
            _validate_active_entry_identity(
                work.registry,
                active_state,
                loaded.entry,
            )
        return ConfigRegistrySnapshot(
            entries=entries,
            active_state=active_state,
        )


def _list_config_registry_entries_locked(
    repository: ConfigRegistryRepository,
) -> tuple[ConfigRegistryEntry, ...]:
    return tuple(
        sorted(repository.list_entries(), key=lambda entry: entry.registered_at)
    )


def load_config_registry_entry_snapshot(
    *,
    entry_id: str,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
) -> ConfigRegistryEntrySnapshot:
    _validate_entry_id(entry_id)
    with unit_of_work() as work:
        return _load_config_registry_entry_locked(
            entry_id=entry_id,
            work=work,
        )


def _load_config_registry_entry_locked(
    *, entry_id: str, work: ConfigRegistryUnitOfWork
) -> ConfigRegistryEntrySnapshot:
    """Read one entry and verify its content-addressed config."""

    if not work.registry.entry_exists(entry_id):
        raise _registry_failure(
            NotFound,
            code="config_registry.not_found",
            message="config registry entry was not found",
            location=_registry_model_location("entry_id"),
            details={"entry_id": entry_id},
        )
    entry = work.registry.read_entry(entry_id)
    return ConfigRegistryEntrySnapshot(
        entry=entry,
        config=_read_entry_config(work.registry, entry),
    )


def load_active_config_registry_config(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
) -> ConfigProfileSnapshot:
    with unit_of_work() as work:
        state = _load_active_config_registry_state_locked(work.registry)
        loaded = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, state, loaded.entry)
        return loaded.config


def load_active_config_registry_snapshot(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
) -> ActiveConfigRegistrySnapshot:
    """Read the active head and its immutable config in one transaction."""

    with unit_of_work() as work:
        state = _load_active_config_registry_state_locked(work.registry)
        loaded = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, state, loaded.entry)
        return ActiveConfigRegistrySnapshot(
            entry=loaded.entry,
            active_state=state,
            config=loaded.config,
        )


def resolve_config_registry_config_source(
    *, selector: str, unit_of_work: ConfigRegistryUnitOfWorkFactory
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
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
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
    work: ConfigRegistryUnitOfWork,
    operator: str,
    expected_generation: int,
    note: str,
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    current_state = _read_active_state_optional(work.registry)
    _require_expected_generation(
        current_state,
        expected_generation,
        active_ref=work.registry.active_ref,
    )
    loaded = _load_config_registry_entry_locked(
        entry_id=entry_id,
        work=work,
    )
    entry = loaded.entry
    _validate_derived_entry_base(current_state, entry, work)
    _validate_loaded_config(loaded.config)
    previous_entry_id = (
        current_state.active_entry_id if current_state is not None else None
    )
    previous_content_hash = (
        current_state.active_entry_content_hash if current_state is not None else None
    )
    generation = expected_generation + 1
    record = ConfigRegistryActivationRecord(
        id=_activation_record_id(generation, "activation"),
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
        updated_at=record.recorded_at,
    )
    work.registry.commit_activation(
        expected_generation=expected_generation,
        record=record,
    )
    return state, record


def rollback_config_registry(
    *,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    _validate_required_text(operator, field="operator")
    with unit_of_work() as work:
        current_state = _read_active_state_optional(work.registry)
        _require_expected_generation(
            current_state,
            expected_generation,
            active_ref=work.registry.active_ref,
        )
        if current_state is None:
            raise _registry_failure(
                NotFound,
                code="config_registry.no_active_entry",
                message="config registry has no active entry",
                location=_registry_model_location("active"),
            )
        current = _load_config_registry_entry_locked(
            entry_id=current_state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, current_state, current.entry)
        history = work.registry.list_activation_history()
        rollback_target = _previous_distinct_activation(
            history,
            active_entry_id=current_state.active_entry_id,
        )
        loaded = _load_config_registry_entry_locked(
            entry_id=rollback_target.entry_id,
            work=work,
        )
        entry = loaded.entry
        _validate_loaded_config(loaded.config)
        if entry.content_hash != rollback_target.entry_content_hash:
            raise _registry_failure(
                DataIntegrityError,
                code="config_registry.rollback_content_mismatch",
                message="rollback target no longer matches activation history",
                location=_registry_storage_location(work.registry.active_ref),
                related_locations=(_registry_storage_location(entry.config_ref),),
                details={"entry_id": entry.id},
            )
        generation = expected_generation + 1
        record = ConfigRegistryActivationRecord(
            id=_activation_record_id(generation, "rollback"),
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
            updated_at=record.recorded_at,
        )
        work.registry.commit_activation(
            expected_generation=expected_generation,
            record=record,
        )
        return state, record


def current_config_registry_generation(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
) -> int:
    with unit_of_work() as work:
        return work.registry.current_generation()


def load_config_registry_activation_history(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
) -> tuple[ConfigRegistryActivationRecord, ...]:
    with unit_of_work() as work:
        return work.registry.list_activation_history()


def load_active_config_registry_state(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
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
            message="config registry has no active entry",
            location=_registry_model_location("active"),
        )
    return state


def load_active_config_registry_entry(
    *, unit_of_work: ConfigRegistryUnitOfWorkFactory
) -> ConfigRegistryEntry:
    with unit_of_work() as work:
        state = _load_active_config_registry_state_locked(work.registry)
        loaded = _load_config_registry_entry_locked(
            entry_id=state.active_entry_id,
            work=work,
        )
        _validate_active_entry_identity(work.registry, state, loaded.entry)
        return loaded.entry


def _resolve_entry_config_registry_config_source_locked(
    *, selector: str, work: ConfigRegistryUnitOfWork
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    loaded = _load_config_registry_entry_locked(
        entry_id=selector,
        work=work,
    )
    entry = loaded.entry
    source = ConfigRegistryRunConfigSource(
        selector=selector,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
    )
    return loaded.config, source


def _resolve_active_config_registry_config_source_locked(
    *, work: ConfigRegistryUnitOfWork
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    state = _load_active_config_registry_state_locked(work.registry)
    loaded = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        work=work,
    )
    entry = loaded.entry
    _validate_active_entry_identity(work.registry, state, entry)
    source = ConfigRegistryRunConfigSource(
        selector=ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        entry_id=entry.id,
        config_ref=entry.config_ref,
        content_hash=entry.content_hash,
        registry_generation=state.generation,
    )
    return loaded.config, source


def _validate_entry_id(entry_id: str) -> None:
    if not SAFE_ENTRY_ID_RE.fullmatch(entry_id):
        raise _registry_failure(
            CheckFailed,
            code="config_registry.invalid_entry_id",
            message="config registry entry id is not safe",
            location=_registry_model_location("entry_id"),
            details={"entry_id": entry_id},
        )


def _validate_required_text(value: str, *, field: str) -> None:
    if value.strip():
        return
    raise _registry_failure(
        CheckFailed,
        code=f"config_registry.{field}_missing",
        message=f"config registry {field} must be non-empty",
        location=_registry_model_location(field),
    )


def _require_run_record(
    *, source_manifest: RunManifest, record_id: str, kind: str
) -> RunContentEntry:
    record = next(
        (entry for entry in source_manifest.records if entry.id == record_id),
        None,
    )
    if record is None:
        raise _registry_failure(
            NotFound,
            code="config_registry.source_record_not_found",
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
    existing = _find_existing_entry_locked(
        repository=repository,
        entry_id=requested_entry.id,
    )
    if existing is not None:
        existing_config = _read_entry_config(repository, existing)
        if not (
            _same_registration(existing, requested_entry)
            and config_content_equal(existing_config, config)
        ):
            raise _registry_failure(
                Conflict,
                code="config_registry.duplicate_entry",
                message="config registry entry id is already committed differently",
                location=_registry_model_location("entry_id"),
                related_locations=(
                    _registry_storage_location(repository.entry_ref(existing.id)),
                ),
                details={"entry_id": requested_entry.id},
            )
        return existing
    repository.commit_registration(
        entry=requested_entry,
        config=config,
    )
    return requested_entry


def _find_existing_entry_locked(
    *,
    repository: ConfigRegistryRepository,
    entry_id: str,
) -> ConfigRegistryEntry | None:
    if repository.entry_exists(entry_id):
        return repository.read_entry(entry_id)
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
    if isinstance(existing.source, ManualConfigDraftRegistrySource) and isinstance(
        requested.source, ManualConfigDraftRegistrySource
    ):
        return (
            existing.source == requested.source
            and existing.registered_by == requested.registered_by
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


def _read_active_state_optional(
    repository: ConfigRegistryRepository,
) -> ConfigRegistryActiveState | None:
    return repository.read_active_state()


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
        message="config registry active state changed",
        location=_registry_model_location("expected_generation"),
        related_locations=(_registry_storage_location(active_ref),),
        details={
            "expected_generation": expected_generation,
            "actual_generation": current_generation,
        },
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
        message="active config registry state does not match its entry",
        location=_registry_storage_location(repository.active_ref),
        related_locations=(_registry_storage_location(repository.entry_ref(entry.id)),),
        details={"entry_id": entry.id},
    )


def _validate_derived_entry_base(
    state: ConfigRegistryActiveState | None,
    entry: ConfigRegistryEntry,
    work: ConfigRegistryUnitOfWork,
) -> None:
    if state is None:
        return
    if state.active_entry_id == entry.id:
        _validate_active_entry_identity(work.registry, state, entry)
        return
    active = _load_config_registry_entry_locked(
        entry_id=state.active_entry_id,
        work=work,
    )
    active_entry = active.entry
    _validate_active_entry_identity(work.registry, state, active_entry)
    if isinstance(
        entry.source,
        (CandidateConfigRegistrySource, ManualConfigDraftRegistrySource),
    ):
        base_content_hash = entry.source.base_config_content_hash
    else:
        return
    if base_content_hash == active_entry.content_hash:
        return
    raise _registry_failure(
        Conflict,
        code="config_registry.stale_candidate",
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
            "candidate_base_content_hash": base_content_hash,
            "active_content_hash": active_entry.content_hash,
        },
    )


def _validate_loaded_config(config: ConfigProfileSnapshot) -> None:
    problems = validate_config_profile(config)
    if bool(problems):
        raise CheckFailed(problems)


def _previous_distinct_activation(
    history: Sequence[ConfigRegistryActivationRecord],
    *,
    active_entry_id: str,
) -> ConfigRegistryActivationRecord:
    for record in reversed(history[:-1]):
        if record.entry_id != active_entry_id:
            return record
    raise _registry_failure(
        Conflict,
        code="config_registry.no_rollback_target",
        message="config registry has no previous active entry",
        location=_registry_model_location("active"),
    )


def _activation_record_id(generation: int, action: str) -> str:
    return f"{action}-{generation:06d}"


def _registry_failure(
    failure_type: type[ProblemFailure],
    *,
    code: str,
    message: str,
    location: ProblemLocation | None = None,
    related_locations: Sequence[ProblemLocation] = (),
    details: Mapping[str, object] | None = None,
) -> ProblemFailure:
    return failure_type(
        [
            Problem(
                code=code,
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
    "ActiveConfigRegistrySnapshot",
    "ConfigRegistryEntrySnapshot",
    "ConfigRegistryRepository",
    "ConfigRegistrySnapshot",
    "ConfigRegistryUnitOfWork",
    "ConfigRegistryUnitOfWorkFactory",
    "ManualConfigDraftResult",
    "activate_config_registry_entry",
    "current_config_registry_generation",
    "list_config_registry_entries",
    "load_active_config_registry_config",
    "load_active_config_registry_entry",
    "load_active_config_registry_snapshot",
    "load_active_config_registry_state",
    "load_config_registry_activation_history",
    "load_config_registry_entry_snapshot",
    "load_config_registry_snapshot",
    "preview_manual_config_draft",
    "register_and_activate_candidate_config",
    "register_and_activate_config_profile",
    "register_and_activate_manual_config_draft",
    "register_config_profile",
    "register_manual_config_draft",
    "resolve_config_registry_config_source",
    "rollback_config_registry",
]
