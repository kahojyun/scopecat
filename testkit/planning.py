"""Project-backed planning helpers for repository tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from scopecat.authoring.experiments import ExperimentInvocation
from scopecat.compiler.bind import bind_program
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_invocation,
)
from scopecat.config.candidates import (
    CandidateConfig,
    resolve_candidate_config_snapshot,
)
from scopecat.config.environment import build_config_environment
from scopecat.config.registry import service as config_registry_service
from scopecat.kernel.errors import CheckFailed, ProblemFailure
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.planning.check_results import ExperimentCheckResult
from scopecat.planning.compilation import compile_run_program
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.service import PlannedRun
from scopecat.planning.system import ExperimentSystem
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import AnalysisCandidateRunConfigSource, RunConfigSource

type TestExperimentSystemBuilder = Callable[
    [ConfigProfileSnapshot],
    ExperimentSystem | None,
]


def plan_experiment(
    experiment: ExperimentInvocation,
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    system: ExperimentSystem | None = None,
    build_experiment_system: TestExperimentSystemBuilder | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> PlannedRun:
    """Compile a runnable program without creating durable run state."""

    compiled = compile_invocation(
        experiment,
        metadata=metadata,
        operator=operator,
    )
    selected_config, config_source = resolve_test_config(
        services=services,
        config=config,
    )
    selected_system = (
        system
        if build_experiment_system is None
        else build_experiment_system(selected_config)
    )
    environment = build_config_environment(selected_config)
    bound = bind_program(compiled.program, environment)
    return PlannedRun(
        config=selected_config,
        request=compiled.request,
        program=compile_run_program(selected_system, bound=bound),
        config_source=config_source,
        system=selected_system,
    )


def check_experiment(
    experiment: ExperimentInvocation,
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig = "active",
    system: ExperimentSystem | None = None,
    build_experiment_system: TestExperimentSystemBuilder | None = None,
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
        invocation=experiment,
        services=services,
        config=config,
        system=system,
        build_experiment_system=build_experiment_system,
    )


def _check_compiled_experiment(
    experiment: CompiledInvocation,
    *,
    invocation: ExperimentInvocation,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
    system: ExperimentSystem | None,
    build_experiment_system: TestExperimentSystemBuilder | None,
) -> ExperimentCheckResult:
    try:
        selected_config, _config_source = resolve_test_config(
            services=services,
            config=config,
        )
        selected_system = (
            system
            if build_experiment_system is None
            else build_experiment_system(selected_config)
        )
        environment = build_config_environment(selected_config)
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.CONFIGURATION):
            raise
        return ExperimentCheckResult(problems=error.problems, preview=None)

    try:
        bound = bind_program(experiment.program, environment)
        preview = build_run_program_preview(
            compile_run_program(selected_system, bound=bound),
            invocation=invocation,
        )
        problems: tuple[Problem, ...] = ()
    except ProblemFailure as error:
        if not _problems_match_phase(error.problems, ProblemPhase.PLANNING):
            raise
        problems = error.problems
        preview = None
    return ExperimentCheckResult(problems=problems, preview=preview)


def resolve_test_config(
    *,
    services: ProjectStateServices,
    config: str | ConfigProfileSnapshot | CandidateConfig,
) -> tuple[ConfigProfileSnapshot, RunConfigSource | None]:
    if isinstance(config, CandidateConfig):
        selected = resolve_candidate_config_snapshot(config, services=services)
        return (
            selected,
            AnalysisCandidateRunConfigSource(
                source_run_id=config.source_run_id,
                analysis_record_id=config.analysis_record_id,
                proposal_id=config.proposal_id,
                base_config_content_hash=config.base_config_content_hash,
                content_hash=config_content_hash(selected),
            ),
        )
    if isinstance(config, ConfigProfileSnapshot):
        return config, None
    return config_registry_service.resolve_config_registry_config_source(
        selector=config,
        unit_of_work=services.config_registry,
    )


def _problems_match_phase(
    problems: tuple[Problem, ...],
    phase: ProblemPhase,
) -> bool:
    return all(item.phase is phase for item in problems)
