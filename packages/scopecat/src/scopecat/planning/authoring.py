"""Application ingress for compiling authoring invocations with configuration."""

from __future__ import annotations

from pathlib import Path

from scopecat.authoring.templates import ConfigProfileInput, ExperimentInvocation
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import (
    ResolvedExperiment,
    compile_prepared_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry.ports import WorkspaceUnitOfWorkFactory
from scopecat.config.registry.service import resolve_config_registry_config_source
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource


def resolve_experiment(
    experiment: ExperimentInvocation,
    *,
    workspace: str | Path,
    config_registry: WorkspaceUnitOfWorkFactory | None = None,
    config_entry: str | None = "active",
    config_profile: ConfigProfileInput | None = None,
) -> ResolvedExperiment:
    """Compile an invocation after resolving its selected configuration source."""

    compiled = compile_prepared_invocation(prepare_invocation(experiment))
    config, source = _resolve_config_source(
        config_registry=config_registry,
        config_entry=config_entry,
        config_profile=config_profile,
    )
    return resolve_compiled_invocation(
        compiled,
        environment=validate_config_environment(config),
        workspace=workspace,
        config_source=source,
    )


def resolve_experiment_with_config(
    experiment: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> ResolvedExperiment:
    """Compile an invocation against an already loaded configuration snapshot."""

    compiled = compile_prepared_invocation(prepare_invocation(experiment))
    return resolve_compiled_invocation(
        compiled,
        environment=validate_config_environment(config),
        workspace=workspace,
        config_source=config_source,
    )


def _resolve_config_source(
    *,
    config_registry: WorkspaceUnitOfWorkFactory | None,
    config_entry: str | None,
    config_profile: ConfigProfileInput | None,
) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
    if config_profile is not None:
        if config_entry not in (None, "active"):
            raise CheckFailed(
                [
                    _configuration_problem(
                        "conflicting_experiment_authoring_config_source",
                        "provide either config_profile or config_entry, not both",
                    )
                ]
            )
        if isinstance(config_profile, ConfigProfileSnapshot):
            return config_profile, None
        return load_config_profile(config_profile), None
    if config_entry is None:
        raise CheckFailed(
            [
                _configuration_problem(
                    "missing_experiment_authoring_config_source",
                    "provide config_profile or config_entry",
                )
            ]
        )
    if config_registry is None:
        raise CheckFailed(
            [
                _configuration_problem(
                    "missing_experiment_authoring_services",
                    "registry-backed authoring requires workspace services",
                )
            ]
        )
    return resolve_config_registry_config_source(
        selector=config_entry,
        unit_of_work=config_registry,
    )


def _configuration_problem(code: str, message: str) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.INVALID_INPUT,
        phase=ProblemPhase.CONFIGURATION,
        location=model_location("config"),
    )


__all__ = ["resolve_experiment", "resolve_experiment_with_config"]
