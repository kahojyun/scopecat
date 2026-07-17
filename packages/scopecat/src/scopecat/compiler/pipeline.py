"""One-way orchestration of the experiment compiler pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.linking.linked import LinkedPlan, link_verified_program
from scopecat.compiler.typed.program import TypedProgram
from scopecat.kernel.problems import Problem
from scopecat.records.run import RunConfigSource
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class LinkedExperiment:
    """Target-neutral compiler result shared by all execution backends."""

    plan: LinkedPlan
    request: RunRequest
    config_source: RunConfigSource | None

    @property
    def program(self) -> TypedProgram:
        return self.plan.program

    @property
    def template_id(self) -> str | None:
        return self.request.template_id

    @property
    def problems(self) -> tuple[Problem, ...]:
        return self.plan.environment.problems


def link_experiment(
    invocation: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    config_source: RunConfigSource | None = None,
) -> LinkedExperiment:
    """Resolve config-backed authoring and stop before target selection."""

    resolved = resolve_compiled_invocation(
        invocation,
        environment=environment,
        config_source=config_source,
    )
    plan = link_verified_program(resolved.verified_program, environment)
    return LinkedExperiment(
        plan=plan,
        request=resolved.request,
        config_source=resolved.config_source,
    )
