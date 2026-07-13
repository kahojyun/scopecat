"""Config source and registry workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat.candidate_configs import (
    CandidateConfigInput,
    materialize_candidate_config,
)
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    activate_config_registry_entry,
    current_config_registry_generation,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.config_registry import (
    register_and_activate_candidate_config as registry_register_and_activate_candidate,
)
from scopecat.config_registry import (
    register_and_activate_config_profile as registry_register_and_activate_config,
)
from scopecat.config_registry import (
    register_config_profile as registry_register_config_profile,
)
from scopecat.errors import CheckFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.planning.validation import validate_config
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)

type ConfigProfileInput = str | Path | ConfigProfileSnapshot


@dataclass(frozen=True)
class ResolvedConfig:
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None


@dataclass(frozen=True)
class ValidateConfigProfileResult:
    config: ConfigProfileSnapshot
    problems: tuple[Problem, ...]


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
        raise CheckFailed(
            [
                blocking_problem(
                    "config.source_conflict",
                    "provide either a config profile or a registry entry, not both",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.CONFIGURATION,
                    location=model_location("config_source"),
                )
            ]
        )
    if not has_file_config and not has_config_entry:
        raise CheckFailed(
            [
                blocking_problem(
                    "config.source_missing",
                    "provide a config profile or a registry entry",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.CONFIGURATION,
                    location=model_location("config_source"),
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
    problems = validate_config(config)
    if has_blocking_problems(problems):
        raise CheckFailed(problems)
    return ValidateConfigProfileResult(config=config, problems=problems)


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
    expected_generation: int | None = None,
) -> RegisteredConfigActivation:
    entry, active_state, activation = registry_register_and_activate_config(
        config=config,
        workspace=workspace,
        entry_id=entry_id,
        registered_by=registered_by,
        operator=operator,
        note=note,
        activation_note=activation_note,
        expected_generation=expected_generation,
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
    expected_generation: int | None = None,
) -> RegisteredConfigActivation:
    selected_generation = (
        current_config_registry_generation(workspace=workspace)
        if expected_generation is None
        else expected_generation
    )
    candidate_config = materialize_candidate_config(candidate, workspace=workspace)
    selected_entry_id = entry_id or (
        f"{candidate_config.candidate_config_record_id}-"
        f"{candidate_config.candidate.source_run_id}"
    )
    entry, active_state, activation = registry_register_and_activate_candidate(
        config=candidate_config.config,
        workspace=workspace,
        entry_id=selected_entry_id,
        registered_by=registered_by,
        run_id=candidate_config.candidate.source_run_id,
        proposal_ids=candidate_config.candidate.proposal_ids,
        candidate_record_id=candidate_config.candidate_config_record_id,
        base_config_content_hash=candidate_config.candidate.base_config_content_hash,
        operator=operator,
        expected_generation=selected_generation,
        note=note,
        activation_note=activation_note,
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
    expected_generation: int | None = None,
) -> ConfigActivation:
    selected_generation = (
        current_config_registry_generation(workspace=workspace)
        if expected_generation is None
        else expected_generation
    )
    active_state, activation = activate_config_registry_entry(
        entry_id=entry_id,
        workspace=workspace,
        operator=operator,
        note=note,
        expected_generation=selected_generation,
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
    expected_generation: int | None = None,
) -> ConfigActivation:
    selected_generation = (
        current_config_registry_generation(workspace=workspace)
        if expected_generation is None
        else expected_generation
    )
    active_state, activation = rollback_config_registry(
        workspace=workspace,
        operator=operator,
        note=note,
        expected_generation=selected_generation,
    )
    return ConfigActivation(
        active_state=active_state,
        activation=activation,
    )
