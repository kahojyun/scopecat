"""One-way orchestration of the experiment compiler pipeline."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace

from scopecat.compiler.frontend.environment import ValidatedConfigEnvironment
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.linking.bound import BoundPlan
from scopecat.compiler.linking.linked import LinkedPlan, link_verified_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.typed.program import TypedProgram
from scopecat.kernel.problems import Problem
from scopecat.kernel.product_identity import ProductUseId
from scopecat.records.run import RunConfigSource
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class CompiledExperiment:
    """Closed compiler result shared by preview and execution."""

    program: TypedProgram
    plan: BoundPlan
    request: RunRequest
    config_source: RunConfigSource | None

    @property
    def template_id(self) -> str | None:
        return self.request.template_id

    @property
    def problems(self) -> tuple[Problem, ...]:
        return self.plan.problems

    @property
    def valid(self) -> bool:
        return self.plan.valid


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


def compile_local_experiment(
    linked: LinkedExperiment,
    *,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
) -> CompiledExperiment:
    """Select the existing local backend for one already-linked program."""

    plan = materialize_local_plan(
        linked.plan,
        product_use_ids=product_use_ids,
    )
    plan = replace(
        plan,
        problems=_merge_problem_references((*linked.problems, *plan.problems)),
    )
    return CompiledExperiment(
        program=linked.program,
        plan=plan,
        request=linked.request,
        config_source=linked.config_source,
    )


def compile_experiment(
    invocation: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    config_source: RunConfigSource | None = None,
) -> CompiledExperiment:
    """Run config linking and current local-plan lowering for an invocation."""

    linked = link_experiment(
        invocation,
        environment=environment,
        config_source=config_source,
    )
    return compile_local_experiment(
        linked,
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


__all__ = [
    "CompiledExperiment",
    "LinkedExperiment",
    "compile_experiment",
    "compile_local_experiment",
    "link_experiment",
]
