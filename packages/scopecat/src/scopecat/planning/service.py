"""Transient experiment planning workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.program import RunProgram
from scopecat.planning.compilation import compile_run_program
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunConfigSource
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class PlannedRun:
    """Transient program and the accepted facts used to plan it."""

    config: ConfigProfileSnapshot
    request: RunRequest
    program: RunProgram
    config_source: RunConfigSource | None = None
    system: ExperimentSystem | None = field(default=None, repr=False, compare=False)


def _plan_compiled_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: CompiledInvocation,
    system: ExperimentSystem | None,
    config_source: RunConfigSource | None,
) -> PlannedRun:
    environment = build_config_environment(config)
    linked = resolve_compiled_invocation(
        experiment,
        environment=environment,
    )
    program = compile_run_program(
        system,
        linked=linked,
    )
    return PlannedRun(
        config=config,
        request=experiment.request,
        program=program,
        config_source=config_source,
        system=system,
    )


def plan_scratch_experiment(
    experiment: ExperimentInvocation,
    *,
    config: ConfigProfileSnapshot,
    system: ExperimentSystem,
    config_source: RunConfigSource | None = None,
    metadata: Mapping[str, object] | None = None,
    operator: str | None = None,
) -> PlannedRun:
    """Plan notebook code against an explicit snapshot without project I/O."""

    return _plan_compiled_run(
        config=config,
        experiment=compile_invocation(
            experiment,
            metadata=metadata,
            operator=operator,
        ),
        system=system,
        config_source=config_source,
    )
