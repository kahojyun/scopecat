"""Project-backed planning helpers for repository tests."""

from __future__ import annotations

from collections.abc import Mapping

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.candidates import CandidateConfig
from scopecat.config.environment import build_config_environment
from scopecat.config.resolution import (
    ConfigProfileInput,
    resolve_experiment_config,
)
from scopecat.kernel.errors import CheckFailed, ProblemFailure
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.compilation import compile_run_program
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.service import PlannedRun
from scopecat.planning.system import ExperimentSystem
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot


def plan_experiment(
    experiment: ExperimentInvocation,
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> PlannedRun:
    """Compile a runnable program without creating durable run state."""

    compiled = compile_invocation(
        experiment,
        metadata=metadata,
        operator=operator,
    )
    resolved = resolve_experiment_config(
        services=services,
        config=config,
        config_profile=config_profile,
    )
    environment = build_config_environment(resolved.config)
    linked = resolve_compiled_invocation(compiled, environment=environment)
    return PlannedRun(
        config=resolved.config,
        request=compiled.request,
        program=compile_run_program(system, linked=linked),
        config_source=resolved.config_source,
        system=system,
    )


def check_experiment(
    experiment: ExperimentInvocation,
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    config_profile: ConfigProfileInput | None = None,
    system: ExperimentSystem | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> ExperimentCheckResult:
    """Build a preview while returning expected authoring and planning failures."""

    try:
        compiled = compile_invocation(
            experiment,
            metadata=metadata,
            operator=operator,
        )
    except CheckFailed as error:
        return ExperimentCheckResult(problems=error.problems, preview=None)
    return _check_compiled_experiment(
        compiled,
        services=services,
        config=config,
        config_profile=config_profile,
        system=system,
    )


def _check_compiled_experiment(
    experiment: CompiledInvocation,
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    config_profile: ConfigProfileInput | None,
    system: ExperimentSystem | None,
) -> ExperimentCheckResult:
    try:
        resolved = resolve_experiment_config(
            services=services,
            config=config,
            config_profile=config_profile,
        )
        environment = build_config_environment(resolved.config)
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.CONFIGURATION):
            raise
        return ExperimentCheckResult(problems=error.problems, preview=None)

    try:
        linked = resolve_compiled_invocation(experiment, environment=environment)
        preview = build_run_program_preview(compile_run_program(system, linked=linked))
        problems: tuple[Problem, ...] = ()
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.PLANNING):
            raise
        problems = error.problems
        preview = None
    return ExperimentCheckResult(problems=problems, preview=preview)


def _problems_match_phase(
    problems: tuple[Problem, ...],
    phase: ProblemPhase,
) -> bool:
    return all(item.phase is phase for item in problems)
