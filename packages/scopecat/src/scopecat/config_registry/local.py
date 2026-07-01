"""Workspace-local config registry registration.

The registry stores named configuration snapshots under the workspace-local
``config-registry`` tree and maintains an ``active`` selector for later runs.
Entries can be registered directly from a ``ConfigProfileSnapshot`` or from a
candidate configuration. Activating an entry records the previous active
entry so rollback can restore it without depending on external state.

Runs started from a registry entry copy source provenance into
``config-profile.snapshot.json``. Reporting code can then show whether a run
used a direct profile, a specific registry entry, or the active selector at the
time the run was created.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import (
    ConfigProfileSnapshot,
    ConfigProfileSnapshotSource,
    config_content_equal,
)
from scopecat.models.run import RunManifest, utc_now
from scopecat.runs import get_artifact_by_id, open_run_store

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_INDEX_REF = f"{CONFIG_REGISTRY_ROOT}/index.json"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"
CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION = "scopecat.config_registry_entry.v0"
CONFIG_REGISTRY_INDEX_SCHEMA_VERSION = "scopecat.config_registry_index.v0"
CONFIG_REGISTRY_REGISTRATION_JOB_SCHEMA_VERSION = (
    "scopecat.config_registry_registration_job.v0"
)
CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION = "scopecat.config_registry_active_state.v0"
CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION = (
    "scopecat.config_registry_activation_record.v0"
)
CONFIG_REGISTRY_CONFIG_SOURCE_PROVENANCE_SCHEMA_VERSION = (
    "scopecat.config_registry_config_source_provenance.v0"
)
ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR = "active"
SAFE_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"
ConfigRegistryEntrySourceKind = Literal["direct_config_profile", "candidate_config"]


class ConfigRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION
    id: str
    status: str = "registered"
    source_kind: ConfigRegistryEntrySourceKind
    config_ref: str
    registration_job_ref: str
    registered_by: str
    note: str = ""
    source_run_id: str | None = None
    change_set_ids: list[str] = Field(default_factory=list)
    change_set_artifact_ids: list[str] = Field(default_factory=list)
    candidate_artifact_id: str | None = None
    source_candidate_artifact_id: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    registered_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_INDEX_SCHEMA_VERSION
    entries: list[ConfigRegistryEntry] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryRegistrationJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_REGISTRATION_JOB_SCHEMA_VERSION
    id: str
    entry_id: str
    source_kind: ConfigRegistryEntrySourceKind
    input_refs: list[str]
    output_refs: list[str]
    source_run_id: str | None = None
    change_set_ids: list[str] = Field(default_factory=list)
    status: str = "completed"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    registered_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryActivationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION
    id: str
    action: str
    entry_id: str
    previous_entry_id: str | None = None
    operator: str
    note: str = ""
    config_ref: str
    recorded_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryActiveState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION
    active_entry_id: str
    active_config_ref: str
    history: list[ConfigRegistryActivationRecord] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryConfigSourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_CONFIG_SOURCE_PROVENANCE_SCHEMA_VERSION
    source_kind: Literal["config_registry"] = "config_registry"
    selector: str
    entry_id: str
    config_ref: str
    active_state_ref: str | None = None
    active_record_id: str | None = None


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    note: str = "",
    source_ref: str | None = None,
) -> tuple[ConfigRegistryRegistrationJob, ConfigRegistryEntry]:
    workspace_path = Path(workspace)
    _validate_entry_id(entry_id)
    refs = _entry_refs(entry_id)
    entry = ConfigRegistryEntry(
        id=entry_id,
        source_kind="direct_config_profile",
        config_ref=refs.config_ref,
        registration_job_ref=refs.job_ref,
        registered_by=registered_by,
        note=note,
    )
    input_refs = [source_ref] if source_ref is not None else []
    job = ConfigRegistryRegistrationJob(
        id=entry_id,
        entry_id=entry_id,
        source_kind="direct_config_profile",
        input_refs=input_refs,
        output_refs=[
            CONFIG_REGISTRY_INDEX_REF,
            refs.entry_ref,
            refs.config_ref,
            refs.job_ref,
        ],
    )

    index = _read_index(workspace_path)
    existing = _find_existing_entry(
        workspace=workspace_path,
        index=index,
        entry_id=entry_id,
    )
    if existing is not None:
        existing_config = _read_config(
            _config_registry_config_path(workspace_path, existing.config_ref),
            existing.config_ref,
        )
        if _same_registration(existing, entry) and _same_config_profile(
            existing_config, config
        ):
            existing_job = _read_model(
                _workspace_relative_path(workspace_path, existing.registration_job_ref),
                ConfigRegistryRegistrationJob,
                existing.registration_job_ref,
            )
            return existing_job, existing
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_duplicate_entry",
                    f"config registry entry already exists: {entry_id}",
                    "entry_id",
                )
            ]
        )

    _write_config_registry_registration(
        workspace=workspace_path,
        index=index,
        entry=entry,
        job=job,
        config=config,
    )
    return job, entry


def register_and_activate_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    source_ref: str | None = None,
) -> tuple[
    ConfigRegistryRegistrationJob,
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    job, entry = register_config_profile(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        note=note,
        source_ref=source_ref,
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry.id,
        workspace=workspace,
        operator=operator,
        note=note if activation_note is None else activation_note,
    )
    return job, entry, active_state, activation


def register_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    run_id: str,
    change_set_ids: Sequence[str],
    change_set_artifact_ids: Sequence[str],
    candidate_artifact_id: str,
    note: str = "",
    source_ref: str | None = None,
) -> tuple[ConfigRegistryRegistrationJob, ConfigRegistryEntry]:
    workspace_path = Path(workspace)
    _validate_entry_id(entry_id)
    if not change_set_ids or not change_set_artifact_ids:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_config_missing_changes",
                    "candidate config registration requires parameter changes",
                    "change_set_ids",
                )
            ]
        )
    if len(change_set_ids) != len(change_set_artifact_ids):
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_candidate_config_change_mismatch",
                    "candidate config change ids and artifact ids must match",
                    "change_set_ids",
                )
            ]
        )
    refs = _entry_refs(entry_id)
    entry = ConfigRegistryEntry(
        id=entry_id,
        source_kind="candidate_config",
        source_run_id=run_id,
        change_set_ids=list(change_set_ids),
        change_set_artifact_ids=list(change_set_artifact_ids),
        candidate_artifact_id=candidate_artifact_id,
        source_candidate_artifact_id=candidate_artifact_id,
        config_ref=refs.config_ref,
        registration_job_ref=refs.job_ref,
        registered_by=registered_by,
        note=note,
    )
    source_manifest = open_run_store(workspace_path).read_manifest(run_id)
    change_artifacts = [
        _require_run_artifact(
            source_manifest=source_manifest,
            artifact_id=artifact_id,
            kind="parameter_change_set",
        )
        for artifact_id in change_set_artifact_ids
    ]
    candidate_artifact = _require_run_artifact(
        source_manifest=source_manifest,
        artifact_id=candidate_artifact_id,
        kind="candidate_config",
    )
    input_refs = [
        f"runs/{run_id}/manifest.json",
        *[f"runs/{run_id}/{artifact.path}" for artifact in change_artifacts],
        f"runs/{run_id}/{candidate_artifact.path}",
    ]
    if source_ref is not None:
        input_refs.append(source_ref)
    job = ConfigRegistryRegistrationJob(
        id=entry_id,
        entry_id=entry_id,
        source_kind="candidate_config",
        source_run_id=run_id,
        change_set_ids=list(change_set_ids),
        input_refs=input_refs,
        output_refs=[
            CONFIG_REGISTRY_INDEX_REF,
            refs.entry_ref,
            refs.config_ref,
            refs.job_ref,
        ],
    )

    index = _read_index(workspace_path)
    existing = _find_existing_entry(
        workspace=workspace_path,
        index=index,
        entry_id=entry_id,
    )
    if existing is not None:
        if _same_registration(existing, entry):
            existing_job = _read_model(
                _workspace_relative_path(workspace_path, existing.registration_job_ref),
                ConfigRegistryRegistrationJob,
                existing.registration_job_ref,
            )
            return existing_job, existing
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_duplicate_entry",
                    f"config registry entry already exists: {entry_id}",
                    "entry_id",
                )
            ]
        )

    _write_config_registry_registration(
        workspace=workspace_path,
        index=index,
        entry=entry,
        job=job,
        config=config,
    )
    return job, entry


def list_config_registry_entries(*, workspace: str | Path) -> list[ConfigRegistryEntry]:
    index = _read_index(Path(workspace))
    return sorted(index.entries, key=lambda entry: entry.registered_at)


def load_config_registry_entry(
    *, entry_id: str, workspace: str | Path
) -> ConfigRegistryEntry:
    _validate_entry_id(entry_id)
    refs = _entry_refs(entry_id)
    entry_path = _workspace_relative_path(Path(workspace), refs.entry_ref)
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
    return _read_model(entry_path, ConfigRegistryEntry, refs.entry_ref)


def load_config_registry_config(
    *, entry_id: str, workspace: str | Path
) -> ConfigProfileSnapshot:
    workspace_path = Path(workspace)
    entry = load_config_registry_entry(entry_id=entry_id, workspace=workspace_path)
    config_path = _config_registry_config_path(workspace_path, entry.config_ref)
    return _read_config(config_path, entry.config_ref)


def load_active_config_registry_config(
    *, workspace: str | Path
) -> ConfigProfileSnapshot:
    workspace_path = Path(workspace)
    state = load_active_config_registry_state(workspace=workspace_path)
    entry = load_config_registry_entry(
        entry_id=state.active_entry_id,
        workspace=workspace_path,
    )
    if state.active_config_ref != entry.config_ref:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_config_registry_active_state",
                    "config registry active config does not match active entry",
                    "active_config_ref",
                )
            ]
        )
    config_path = _config_registry_config_path(workspace_path, state.active_config_ref)
    return _read_config(config_path, state.active_config_ref)


def resolve_config_registry_config_source(
    *, selector: str, workspace: str | Path
) -> tuple[ConfigProfileSnapshot, ConfigRegistryConfigSourceProvenance]:
    if selector == ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR:
        return _resolve_active_config_registry_config_source(workspace=Path(workspace))
    return _resolve_entry_config_registry_config_source(
        selector=selector,
        workspace=Path(workspace),
    )


def activate_config_registry_entry(
    *,
    entry_id: str,
    workspace: str | Path,
    operator: str,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    workspace_path = Path(workspace)
    entry = load_config_registry_entry(entry_id=entry_id, workspace=workspace_path)
    _validate_entry_config(workspace_path, entry)
    current_state = _read_active_state_optional(workspace_path)
    previous_entry_id = (
        current_state.active_entry_id if current_state is not None else None
    )
    history = [] if current_state is None else [*current_state.history]
    record = ConfigRegistryActivationRecord(
        id=_next_record_id(history, "activation"),
        action="activation",
        entry_id=entry.id,
        previous_entry_id=previous_entry_id,
        operator=operator,
        note=note,
        config_ref=entry.config_ref,
    )
    state = ConfigRegistryActiveState(
        active_entry_id=entry.id,
        active_config_ref=entry.config_ref,
        history=[*history, record],
    )
    _write_model_atomic(workspace_path / CONFIG_REGISTRY_ACTIVE_REF, state)
    return state, record


def rollback_config_registry(
    *,
    workspace: str | Path,
    operator: str,
    note: str = "",
) -> tuple[ConfigRegistryActiveState, ConfigRegistryActivationRecord]:
    workspace_path = Path(workspace)
    current_state = load_active_config_registry_state(workspace=workspace_path)
    rollback_entry_id = _previous_distinct_entry_id(current_state)
    entry = load_config_registry_entry(
        entry_id=rollback_entry_id,
        workspace=workspace_path,
    )
    _validate_entry_config(workspace_path, entry)
    history = [*current_state.history]
    record = ConfigRegistryActivationRecord(
        id=_next_record_id(history, "rollback"),
        action="rollback",
        entry_id=entry.id,
        previous_entry_id=current_state.active_entry_id,
        operator=operator,
        note=note,
        config_ref=entry.config_ref,
    )
    state = ConfigRegistryActiveState(
        active_entry_id=entry.id,
        active_config_ref=entry.config_ref,
        history=[*history, record],
    )
    _write_model_atomic(workspace_path / CONFIG_REGISTRY_ACTIVE_REF, state)
    return state, record


def load_active_config_registry_state(
    *, workspace: str | Path
) -> ConfigRegistryActiveState:
    workspace_path = Path(workspace)
    active_path = workspace_path / CONFIG_REGISTRY_ACTIVE_REF
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
    state = load_active_config_registry_state(workspace=workspace_path)
    return load_config_registry_entry(
        entry_id=state.active_entry_id,
        workspace=workspace_path,
    )


def _resolve_entry_config_registry_config_source(
    *, selector: str, workspace: Path
) -> tuple[ConfigProfileSnapshot, ConfigRegistryConfigSourceProvenance]:
    entry = load_config_registry_entry(entry_id=selector, workspace=workspace)
    config_path = _config_registry_config_path(workspace, entry.config_ref)
    config = _read_config(config_path, entry.config_ref)
    provenance = ConfigRegistryConfigSourceProvenance(
        selector=selector,
        entry_id=entry.id,
        config_ref=entry.config_ref,
    )
    return _config_with_config_registry_source(config, provenance), provenance


def _resolve_active_config_registry_config_source(
    *, workspace: Path
) -> tuple[ConfigProfileSnapshot, ConfigRegistryConfigSourceProvenance]:
    state = load_active_config_registry_state(workspace=workspace)
    entry = load_config_registry_entry(
        entry_id=state.active_entry_id,
        workspace=workspace,
    )
    if state.active_config_ref != entry.config_ref:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "invalid_config_registry_active_state",
                    "config registry active config does not match active entry",
                    "active_config_ref",
                )
            ]
        )
    config_path = _config_registry_config_path(workspace, state.active_config_ref)
    config = _read_config(config_path, state.active_config_ref)
    provenance = ConfigRegistryConfigSourceProvenance(
        selector=ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        entry_id=entry.id,
        config_ref=state.active_config_ref,
        active_state_ref=CONFIG_REGISTRY_ACTIVE_REF,
        active_record_id=state.history[-1].id if state.history else None,
    )
    return _config_with_config_registry_source(config, provenance), provenance


def _config_with_config_registry_source(
    config: ConfigProfileSnapshot,
    provenance: ConfigRegistryConfigSourceProvenance,
) -> ConfigProfileSnapshot:
    source = ConfigProfileSnapshotSource(
        kind="config_registry_entry",
        selector=provenance.selector,
        entry_id=provenance.entry_id,
        config_ref=provenance.config_ref,
        active_state_ref=provenance.active_state_ref,
        active_record_id=provenance.active_record_id,
    )
    return config.model_copy(update={"source": source}, deep=True)


class _EntryRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_ref: str
    config_ref: str
    job_ref: str


def _entry_refs(entry_id: str) -> _EntryRefs:
    return _EntryRefs(
        entry_ref=f"{CONFIG_REGISTRY_ROOT}/entries/{entry_id}.json",
        config_ref=(
            f"{CONFIG_REGISTRY_ROOT}/configs/{entry_id}.config-profile-snapshot.json"
        ),
        job_ref=f"{CONFIG_REGISTRY_ROOT}/jobs/{entry_id}.registration.job.json",
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


def _require_run_artifact(
    *, source_manifest: RunManifest, artifact_id: str, kind: str
) -> Artifact:
    artifact = get_artifact_by_id(source_manifest, artifact_id)
    if artifact is None:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_missing_source_artifact",
                    f"config registry source artifact not found: {artifact_id}",
                    "artifact_id",
                )
            ]
        )
    if artifact.kind != kind:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "config_registry_invalid_source_artifact_kind",
                    (
                        "config registry source artifact has kind "
                        f"{artifact.kind}, expected {kind}: {artifact_id}"
                    ),
                    "artifact_id",
                )
            ]
        )
    return artifact


def _find_existing_entry(
    *,
    workspace: Path,
    index: ConfigRegistryIndex,
    entry_id: str,
) -> ConfigRegistryEntry | None:
    for entry in index.entries:
        if entry.id == entry_id:
            return entry
    refs = _entry_refs(entry_id)
    entry_path = _workspace_relative_path(workspace, refs.entry_ref)
    if entry_path.exists():
        return _read_model(entry_path, ConfigRegistryEntry, refs.entry_ref)
    return None


def _same_registration(
    existing: ConfigRegistryEntry, requested: ConfigRegistryEntry
) -> bool:
    if existing.source_kind != requested.source_kind:
        return False
    if existing.source_kind == "direct_config_profile":
        return (
            existing.registered_by == requested.registered_by
            and existing.note == requested.note
            and existing.config_ref == requested.config_ref
        )
    return (
        existing.source_run_id == requested.source_run_id
        and existing.change_set_ids == requested.change_set_ids
        and existing.change_set_artifact_ids == requested.change_set_artifact_ids
        and existing.candidate_artifact_id == requested.candidate_artifact_id
        and existing.source_candidate_artifact_id
        == requested.source_candidate_artifact_id
    )


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


def _validate_entry_config(workspace: Path, entry: ConfigRegistryEntry) -> None:
    config_path = _config_registry_config_path(workspace, entry.config_ref)
    _read_config(config_path, entry.config_ref)


def _previous_distinct_entry_id(state: ConfigRegistryActiveState) -> str:
    for record in reversed(state.history[:-1]):
        if record.entry_id != state.active_entry_id:
            return record.entry_id
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
    job: ConfigRegistryRegistrationJob,
    config: ConfigProfileSnapshot,
) -> None:
    refs = _entry_refs(entry.id)
    updated_entries = [
        existing for existing in index.entries if existing.id != entry.id
    ]
    updated_entries.append(entry)
    updated_index = ConfigRegistryIndex(
        entries=sorted(updated_entries, key=lambda item: item.registered_at)
    )

    _write_model(_workspace_relative_path(workspace, refs.entry_ref), entry)
    _write_model(_workspace_relative_path(workspace, refs.config_ref), config)
    _write_model(_workspace_relative_path(workspace, refs.job_ref), job)
    _write_model_atomic(workspace / CONFIG_REGISTRY_INDEX_REF, updated_index)


def _write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.model_dump(mode="json"), indent=2) + "\n")


def _write_model_atomic(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    _write_model(temporary_path, model)
    temporary_path.replace(path)


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
