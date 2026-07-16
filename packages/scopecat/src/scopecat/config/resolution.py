"""Config source and registry workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat.application.services import WorkspaceServices
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.config.registry import service as registry_service
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.planning.validation import validate_config
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource

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
    services: WorkspaceServices,
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
        config, source = registry_service.resolve_config_registry_config_source(
            selector=config_entry,
            unit_of_work=services.config_registry,
        )
        return ResolvedConfig(config=config, config_source=source)
    if config_profile is None:
        raise AssertionError("unreachable config source state")
    if isinstance(config_profile, ConfigProfileSnapshot):
        return ResolvedConfig(config=config_profile)
    return ResolvedConfig(config=load_config_profile(config_profile))


def resolve_experiment_config(
    *,
    services: WorkspaceServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None = None,
) -> ResolvedConfig:
    """Resolve one experiment config selection from its authoritative source."""

    if isinstance(config, CandidateConfig | ConfigProfileSnapshot):
        if config_profile is not None:
            raise CheckFailed(
                [
                    blocking_problem(
                        "config.source_conflict",
                        "provide either config or config_profile, not both",
                        category=ProblemCategory.INVALID_INPUT,
                        phase=ProblemPhase.CONFIGURATION,
                        location=model_location("run_options", "config"),
                    )
                ]
            )
        if isinstance(config, CandidateConfig):
            return ResolvedConfig(
                config=resolve_candidate_config_snapshot(config, services=services)
            )
        return ResolvedConfig(config=config)

    config_entry = None if config_profile is not None and config == "active" else config
    return resolve_config_source(
        services=services,
        config_profile=config_profile,
        config_entry=config_entry,
    )


def load_active_config(*, services: WorkspaceServices) -> ResolvedConfig:
    config, source = registry_service.resolve_config_registry_config_source(
        selector="active",
        unit_of_work=services.config_registry,
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
    services: WorkspaceServices,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryEntry:
    return registry_service.register_config_profile(
        config=config,
        unit_of_work=services.config_registry,
        entry_id=entry_id,
        registered_by=registered_by,
        note=note,
    )


def register_and_activate_config_profile(
    *,
    config: ConfigProfileSnapshot,
    services: WorkspaceServices,
    entry_id: str,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    expected_generation: int | None = None,
) -> RegisteredConfigActivation:
    entry, active_state, activation = (
        registry_service.register_and_activate_config_profile(
            config=config,
            unit_of_work=services.config_registry,
            entry_id=entry_id,
            registered_by=registered_by,
            operator=operator,
            note=note,
            activation_note=activation_note,
            expected_generation=expected_generation,
        )
    )
    return RegisteredConfigActivation(
        entry=entry,
        active_state=active_state,
        activation=activation,
    )


def register_and_activate_candidate_config(
    *,
    candidate: CandidateConfig,
    services: WorkspaceServices,
    entry_id: str | None = None,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    expected_generation: int | None = None,
) -> RegisteredConfigActivation:
    selected_generation = (
        registry_service.current_config_registry_generation(
            unit_of_work=services.config_registry
        )
        if expected_generation is None
        else expected_generation
    )
    candidate_config = resolve_candidate_config_snapshot(candidate, services=services)
    selected_entry_id = entry_id or f"{candidate_config.id}-{candidate.source_run_id}"
    entry, active_state, activation = (
        registry_service.register_and_activate_candidate_config(
            config=candidate_config,
            unit_of_work=services.config_registry,
            entry_id=selected_entry_id,
            registered_by=registered_by,
            run_id=candidate.source_run_id,
            proposal_ids=candidate.proposal_ids,
            base_config_content_hash=candidate.base_config_content_hash,
            operator=operator,
            expected_generation=selected_generation,
            note=note,
            activation_note=activation_note,
        )
    )
    return RegisteredConfigActivation(
        entry=entry,
        active_state=active_state,
        activation=activation,
    )


def activate_config_entry(
    *,
    entry_id: str,
    services: WorkspaceServices,
    operator: str,
    note: str = "",
    expected_generation: int | None = None,
) -> ConfigActivation:
    selected_generation = (
        registry_service.current_config_registry_generation(
            unit_of_work=services.config_registry
        )
        if expected_generation is None
        else expected_generation
    )
    active_state, activation = registry_service.activate_config_registry_entry(
        entry_id=entry_id,
        unit_of_work=services.config_registry,
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
    services: WorkspaceServices,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> ConfigActivation:
    active_state, activation = registry_service.rollback_config_registry(
        unit_of_work=services.config_registry,
        operator=operator,
        note=note,
        expected_generation=expected_generation,
    )
    return ConfigActivation(
        active_state=active_state,
        activation=activation,
    )
