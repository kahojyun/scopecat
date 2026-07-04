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

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot, config_content_equal
from scopecat.models.run import RunConfigSource, RunManifest, utc_now
from scopecat.runs import get_record_by_id, open_run_store

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_INDEX_REF = f"{CONFIG_REGISTRY_ROOT}/index.json"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"
CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION = "scopecat.config_registry_entry.v3"
CONFIG_REGISTRY_INDEX_SCHEMA_VERSION = "scopecat.config_registry_index.v0"
CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION = "scopecat.config_registry_active_state.v1"
CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION = (
    "scopecat.config_registry_activation_record.v1"
)
ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR = "active"
SAFE_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
CONFIG_PROFILE_SNAPSHOT_REF = "config-profile.snapshot.json"


class DirectConfigRegistrySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["direct_config_profile"] = "direct_config_profile"


class CandidateConfigRegistrySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["candidate_config"] = "candidate_config"
    run_id: str
    change_set_ids: list[str] = Field(default_factory=list)
    candidate_record_id: str


ConfigRegistryEntrySource = Annotated[
    DirectConfigRegistrySource | CandidateConfigRegistrySource,
    Field(discriminator="kind"),
]


class ConfigRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ENTRY_SCHEMA_VERSION
    id: str
    status: str = "registered"
    source: ConfigRegistryEntrySource
    registered_by: str
    note: str = ""
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    registered_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_INDEX_SCHEMA_VERSION
    entries: list[ConfigRegistryEntry] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryActivationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ACTIVATION_RECORD_SCHEMA_VERSION
    id: str
    action: str
    entry_id: str
    previous_entry_id: str | None = None
    operator: str
    note: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)


class ConfigRegistryActiveState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONFIG_REGISTRY_ACTIVE_STATE_SCHEMA_VERSION
    active_entry_id: str
    history: list[ConfigRegistryActivationRecord] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    _validate_entry_id(entry_id)
    entry = ConfigRegistryEntry(
        id=entry_id,
        source=DirectConfigRegistrySource(),
        registered_by=registered_by,
        note=note,
    )

    index = _read_index(workspace_path)
    existing = _find_existing_entry(
        workspace=workspace_path,
        index=index,
        entry_id=entry_id,
    )
    if existing is not None:
        existing_refs = _entry_refs(existing.id)
        existing_config = _read_config(
            _config_registry_config_path(workspace_path, existing_refs.config_ref),
            existing_refs.config_ref,
        )
        if _same_registration(existing, entry) and _same_config_profile(
            existing_config, config
        ):
            return existing
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
        config=config,
    )
    return entry


def register_and_activate_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
) -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
    ConfigRegistryActivationRecord,
]:
    entry = register_config_profile(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        note=note,
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry.id,
        workspace=workspace,
        operator=operator,
        note=note if activation_note is None else activation_note,
    )
    return entry, active_state, activation


def register_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    run_id: str,
    change_set_ids: Sequence[str],
    candidate_record_id: str,
    note: str = "",
) -> ConfigRegistryEntry:
    workspace_path = Path(workspace)
    _validate_entry_id(entry_id)
    if not change_set_ids:
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
    entry = ConfigRegistryEntry(
        id=entry_id,
        source=CandidateConfigRegistrySource(
            run_id=run_id,
            change_set_ids=list(change_set_ids),
            candidate_record_id=candidate_record_id,
        ),
        registered_by=registered_by,
        note=note,
    )
    source_manifest = open_run_store(workspace_path).read_manifest(run_id)
    for change_set_id in change_set_ids:
        _require_run_record(
            source_manifest=source_manifest,
            record_id=change_set_id,
            kind="parameter_change_set",
        )
    _require_run_record(
        source_manifest=source_manifest,
        record_id=candidate_record_id,
        kind="candidate_config",
    )

    index = _read_index(workspace_path)
    existing = _find_existing_entry(
        workspace=workspace_path,
        index=index,
        entry_id=entry_id,
    )
    if existing is not None:
        if _same_registration(existing, entry):
            return existing
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
        config=config,
    )
    return entry


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
    config_ref = _entry_refs(entry.id).config_ref
    config_path = _config_registry_config_path(workspace_path, config_ref)
    return _read_config(config_path, config_ref)


def load_active_config_registry_config(
    *, workspace: str | Path
) -> ConfigProfileSnapshot:
    workspace_path = Path(workspace)
    state = load_active_config_registry_state(workspace=workspace_path)
    entry = load_config_registry_entry(
        entry_id=state.active_entry_id,
        workspace=workspace_path,
    )
    config_ref = _entry_refs(entry.id).config_ref
    config_path = _config_registry_config_path(workspace_path, config_ref)
    return _read_config(config_path, config_ref)


def resolve_config_registry_config_source(
    *, selector: str, workspace: str | Path
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
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
    )
    state = ConfigRegistryActiveState(
        active_entry_id=entry.id,
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
    )
    state = ConfigRegistryActiveState(
        active_entry_id=entry.id,
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
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    entry = load_config_registry_entry(entry_id=selector, workspace=workspace)
    config_ref = _entry_refs(entry.id).config_ref
    config_path = _config_registry_config_path(workspace, config_ref)
    config = _read_config(config_path, config_ref)
    source = RunConfigSource(
        selector=selector,
        entry_id=entry.id,
    )
    return config, source


def _resolve_active_config_registry_config_source(
    *, workspace: Path
) -> tuple[ConfigProfileSnapshot, RunConfigSource]:
    state = load_active_config_registry_state(workspace=workspace)
    entry = load_config_registry_entry(
        entry_id=state.active_entry_id,
        workspace=workspace,
    )
    config_ref = _entry_refs(entry.id).config_ref
    config_path = _config_registry_config_path(workspace, config_ref)
    config = _read_config(config_path, config_ref)
    source = RunConfigSource(
        selector=ACTIVE_CONFIG_REGISTRY_ENTRY_SELECTOR,
        entry_id=entry.id,
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
        return existing.source == requested.source
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
    config_ref = _entry_refs(entry.id).config_ref
    config_path = _config_registry_config_path(workspace, config_ref)
    _read_config(config_path, config_ref)


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
