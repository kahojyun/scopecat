"""Config source and registry workflow use cases."""

from __future__ import annotations

from pathlib import Path

from scopecat.candidate_configs import (
    CandidateConfigInput,
    resolve_candidate_config,
)
from scopecat.config_registry import (
    activate_config_registry_entry,
    register_candidate_config,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.config_registry import (
    register_and_activate_config_profile as registry_register_and_activate_config,
)
from scopecat.config_registry import (
    register_config_profile as registry_register_config_profile,
)
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.planning.validation import has_blocking_diagnostics, validate_config
from scopecat.workflows._diagnostics import diagnostic as _diagnostic
from scopecat.workflows._types import (
    ActivateConfigEntryResult,
    ConfigProfileInput,
    ConfigSourceResult,
    RegisterAndActivateCandidateConfigResult,
    RegisterAndActivateConfigProfileResult,
    RegisterConfigProfileResult,
    RollbackConfigRegistryResult,
    ValidateConfigProfileResult,
)


def resolve_config_source(
    *,
    workspace: str | Path,
    config_profile: ConfigProfileInput | None = None,
    config_entry: str | None = None,
) -> ConfigSourceResult:
    has_file_config = config_profile is not None
    has_config_entry = config_entry is not None
    if has_file_config and has_config_entry:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "conflicting_config_source",
                    "provide either --config-profile or --config-entry, not both",
                    "config",
                )
            ]
        )
    if not has_file_config and not has_config_entry:
        raise ValidationFailed(
            [
                _diagnostic(
                    "error",
                    "missing_config_source",
                    "provide --config-profile or --config-entry",
                    "config",
                )
            ]
        )
    if config_entry is not None:
        config, provenance = resolve_config_registry_config_source(
            selector=config_entry,
            workspace=workspace,
        )
        return ConfigSourceResult(config=config, provenance=provenance)
    if config_profile is None:
        raise AssertionError("unreachable config source state")
    if isinstance(config_profile, ConfigProfileSnapshot):
        return ConfigSourceResult(config=config_profile)
    return ConfigSourceResult(config=load_config_profile(config_profile))


def load_active_config(*, workspace: str | Path) -> ConfigSourceResult:
    config, provenance = resolve_config_registry_config_source(
        selector="active",
        workspace=workspace,
    )
    return ConfigSourceResult(config=config, provenance=provenance)


def validate_config_profile(
    config_profile: ConfigProfileInput,
) -> ValidateConfigProfileResult:
    config = (
        config_profile
        if isinstance(config_profile, ConfigProfileSnapshot)
        else load_config_profile(config_profile)
    )
    diagnostics = validate_config(config)
    if has_blocking_diagnostics(diagnostics):
        raise ValidationFailed(diagnostics)
    return ValidateConfigProfileResult(config=config, diagnostics=diagnostics)


def register_config_profile(
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    entry_id: str,
    registered_by: str,
    note: str = "",
    source_ref: str | None = None,
) -> RegisterConfigProfileResult:
    job, entry = registry_register_config_profile(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        note=note,
        source_ref=source_ref,
    )
    return RegisterConfigProfileResult(job=job, entry=entry)


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
) -> RegisterAndActivateConfigProfileResult:
    job, entry, active_state, activation = registry_register_and_activate_config(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        operator=operator,
        note=note,
        activation_note=activation_note,
        source_ref=source_ref,
    )
    return RegisterAndActivateConfigProfileResult(
        job=job,
        entry=entry,
        active_state=active_state,
        activation=activation,
    )


def register_and_activate_candidate_config(
    *,
    candidate: CandidateConfigInput,
    workspace: str | Path,
    entry_id: str | None = None,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
) -> RegisterAndActivateCandidateConfigResult:
    candidate_config = resolve_candidate_config(candidate, workspace=workspace)
    selected_entry_id = entry_id or (
        f"{candidate_config.candidate_config_artifact_id}-"
        f"{candidate_config.candidate.source_run_id}"
    )
    job, entry = register_candidate_config(
        config=candidate_config.config,
        workspace=workspace,
        entry_id=selected_entry_id,
        registered_by=registered_by,
        run_id=candidate_config.candidate.source_run_id,
        change_set_ids=candidate_config.candidate.change_set_ids,
        change_set_artifact_ids=candidate_config.change_set_artifact_ids,
        candidate_artifact_id=candidate_config.candidate_config_artifact_id,
        note=note,
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry.id,
        workspace=workspace,
        operator=operator,
        note=note if activation_note is None else activation_note,
    )
    return RegisterAndActivateCandidateConfigResult(
        job=job,
        entry=entry,
        active_state=active_state,
        activation=activation,
    )


def activate_config_entry(
    *,
    entry_id: str,
    workspace: str | Path,
    operator: str,
    note: str = "",
) -> ActivateConfigEntryResult:
    active_state, activation = activate_config_registry_entry(
        entry_id=entry_id,
        workspace=workspace,
        operator=operator,
        note=note,
    )
    return ActivateConfigEntryResult(
        active_state=active_state,
        activation=activation,
    )


def rollback_config(
    *,
    workspace: str | Path,
    operator: str,
    note: str = "",
) -> RollbackConfigRegistryResult:
    active_state, activation = rollback_config_registry(
        workspace=workspace,
        operator=operator,
        note=note,
    )
    return RollbackConfigRegistryResult(
        active_state=active_state,
        activation=activation,
    )
