"""One-way orchestration of the experiment compiler pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from scopecat._compiler.binding import bind_program
from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.program import TypedProgram
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    RelationBackend,
)
from scopecat.authoring._resolution import (
    CompiledInvocation,
    resolve_compiled_invocation,
)
from scopecat.models.run import RunConfigSource
from scopecat.models.run_request import RunRequest
from scopecat.problems import Problem


@dataclass(frozen=True, slots=True)
class CompiledExperiment:
    """Closed compiler result shared by preview and execution."""

    program: TypedProgram
    plan: BoundPlan
    request: RunRequest
    template_id: str | None
    inputs: dict[str, object]
    config_source: RunConfigSource | None

    @property
    def problems(self) -> tuple[Problem, ...]:
        return self.plan.problems

    @property
    def valid(self) -> bool:
        return self.plan.valid


def compile_experiment(
    invocation: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
) -> CompiledExperiment:
    """Run config linking and current local-plan lowering for an invocation."""

    resolved = resolve_compiled_invocation(
        invocation,
        environment=environment,
        workspace=workspace,
        config_source=config_source,
    )
    plan = bind_program(
        resolved.experiment,
        environment,
        relation_backend=relation_backend,
    )
    plan = replace(
        plan,
        problems=_merge_problem_references((*resolved.problems, *plan.problems)),
    )
    return CompiledExperiment(
        program=resolved.experiment,
        plan=plan,
        request=resolved.request,
        template_id=resolved.template_id,
        inputs=dict(resolved.inputs),
        config_source=resolved.config_source,
    )


def _merge_problem_references(problems: tuple[Problem, ...]) -> tuple[Problem, ...]:
    """Merge propagated findings without collapsing independent occurrences."""

    selected: list[Problem] = []
    seen: set[int] = set()
    for problem in problems:
        identity = id(problem)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(problem)
    return tuple(selected)


__all__ = ["CompiledExperiment", "compile_experiment"]
