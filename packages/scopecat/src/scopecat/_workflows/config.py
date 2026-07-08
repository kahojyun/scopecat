"""Config source and registry workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat._workflows._diagnostics import diagnostic as _diagnostic
from scopecat.candidate_configs import (
    CandidateConfigInput,
    resolve_candidate_config,
)
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
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
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.planning.validation import has_blocking_diagnostics, validate_config

type ConfigProfileInput = str | Path | ConfigProfileSnapshot


@dataclass(frozen=True)
class ResolvedConfig:
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None


@dataclass(frozen=True)
class ValidateConfigProfileResult:
    config: ConfigProfileSnapshot
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class RegisteredConfigActivation:
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


@dataclass(frozen=True)
class ConfigActivation:
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord


def resolve_config_source(
    *,
    workspace: str | Path,
    config_profile: ConfigProfileInput | None = None,
    config_entry: str | None = None,
) -> ResolvedConfig:
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
        config, source = resolve_config_registry_config_source(
            selector=config_entry,
            workspace=workspace,
        )
        return ResolvedConfig(config=config, config_source=source)
    if config_profile is None:
        raise AssertionError("unreachable config source state")
    if isinstance(config_profile, ConfigProfileSnapshot):
        return ResolvedConfig(config=config_profile)
    return ResolvedConfig(config=load_config_profile(config_profile))


def load_active_config(*, workspace: str | Path) -> ResolvedConfig:
    config, source = resolve_config_registry_config_source(
        selector="active",
        workspace=workspace,
    )
    return ResolvedConfig(config=config, config_source=source)


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
) -> ConfigRegistryEntry:
    return registry_register_config_profile(
        config=config,
        workspace=workspace,
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
) -> RegisteredConfigActivation:
    entry, active_state, activation = registry_register_and_activate_config(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        operator=operator,
        note=note,
        activation_note=activation_note,
    )
    return RegisteredConfigActivation(
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
) -> RegisteredConfigActivation:
    candidate_config = resolve_candidate_config(candidate, workspace=workspace)
    selected_entry_id = entry_id or (
        f"{candidate_config.candidate_config_record_id}-"
        f"{candidate_config.candidate.source_run_id}"
    )
    entry = register_candidate_config(
        config=candidate_config.config,
        workspace=workspace,
        entry_id=selected_entry_id,
        registered_by=registered_by,
        run_id=candidate_config.candidate.source_run_id,
        change_set_ids=candidate_config.candidate.change_set_ids,
        candidate_record_id=candidate_config.candidate_config_record_id,
        note=note,
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry.id,
        workspace=workspace,
        operator=operator,
        note=note if activation_note is None else activation_note,
    )
    return RegisteredConfigActivation(
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
) -> ConfigActivation:
    active_state, activation = activate_config_registry_entry(
        entry_id=entry_id,
        workspace=workspace,
        operator=operator,
        note=note,
    )
    return ConfigActivation(
        active_state=active_state,
        activation=activation,
    )


def rollback_config(
    *,
    workspace: str | Path,
    operator: str,
    note: str = "",
) -> ConfigActivation:
    active_state, activation = rollback_config_registry(
        workspace=workspace,
        operator=operator,
        note=note,
    )
    return ConfigActivation(
        active_state=active_state,
        activation=activation,
    )
