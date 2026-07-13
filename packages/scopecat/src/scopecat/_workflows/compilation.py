"""One-way orchestration of the experiment compiler pipeline."""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from pathlib import Path

from scopecat._compiler.binding import materialize_local_plan
from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.linked import LinkedPlan, link_program
from scopecat._compiler.program import TypedProgram
from scopecat._product_identity import ProductUseId
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


@dataclass(frozen=True, slots=True)
class LinkedExperiment:
    """Target-neutral compiler result shared by all execution backends."""

    program: TypedProgram
    plan: LinkedPlan
    request: RunRequest
    template_id: str | None
    inputs: dict[str, object]
    config_source: RunConfigSource | None
    problems: tuple[Problem, ...] = ()


def link_experiment(
    invocation: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> LinkedExperiment:
    """Resolve config-backed authoring and stop before target selection."""

    resolved = resolve_compiled_invocation(
        invocation,
        environment=environment,
        workspace=workspace,
        config_source=config_source,
    )
    plan = link_program(resolved.experiment, environment)
    return LinkedExperiment(
        program=resolved.experiment,
        plan=plan,
        request=resolved.request,
        template_id=resolved.template_id,
        inputs=dict(resolved.inputs),
        config_source=resolved.config_source,
        problems=_merge_problem_references(resolved.problems),
    )


def compile_local_experiment(
    linked: LinkedExperiment,
    *,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
) -> CompiledExperiment:
    """Select the existing local backend for one already-linked program."""

    plan = materialize_local_plan(
        linked.plan,
        relation_backend=relation_backend,
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
        template_id=linked.template_id,
        inputs=dict(linked.inputs),
        config_source=linked.config_source,
    )


def compile_experiment(
    invocation: CompiledInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
    relation_backend: RelationBackend = REFERENCE_RELATION_BACKEND,
) -> CompiledExperiment:
    """Run config linking and current local-plan lowering for an invocation."""

    linked = link_experiment(
        invocation,
        environment=environment,
        workspace=workspace,
        config_source=config_source,
    )
    return compile_local_experiment(
        linked,
        relation_backend=relation_backend,
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
