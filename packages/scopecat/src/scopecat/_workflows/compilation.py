"""One-way orchestration of the experiment compiler pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from scopecat._compiler.binding import bind_program
from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.environment import ValidatedConfigEnvironment
from scopecat._compiler.program import TypedProgram
from scopecat.authoring._invocation_plan import PreparedInvocation
from scopecat.authoring._resolution import resolve_prepared_invocation
from scopecat.diagnostics import Diagnostic
from scopecat.models.run import RunConfigSource
from scopecat.models.run_request import RunRequest


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
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.plan.diagnostics

    @property
    def valid(self) -> bool:
        return self.plan.valid


def compile_experiment(
    prepared: PreparedInvocation,
    *,
    environment: ValidatedConfigEnvironment,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
) -> CompiledExperiment:
    """Run authoring, typed linking, and config binding exactly once."""

    resolved = resolve_prepared_invocation(
        prepared,
        environment=environment,
        workspace=workspace,
        config_source=config_source,
    )
    plan = bind_program(resolved.experiment, environment)
    plan = replace(
        plan,
        diagnostics=_deduplicate_diagnostics(
            (*resolved.diagnostics, *plan.diagnostics)
        ),
    )
    return CompiledExperiment(
        program=resolved.experiment,
        plan=plan,
        request=resolved.request,
        template_id=resolved.template_id,
        inputs=dict(resolved.inputs),
        config_source=resolved.config_source,
    )


def _deduplicate_diagnostics(
    diagnostics: tuple[Diagnostic, ...],
) -> tuple[Diagnostic, ...]:
    selected: list[Diagnostic] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.severity,
            diagnostic.code,
            diagnostic.message,
            diagnostic.path,
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(diagnostic)
    return tuple(selected)


__all__ = ["CompiledExperiment", "compile_experiment"]
