"""Prepare public execution inputs for transient runtime execution."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._compiler.program import LinkedProgram
from scopecat._parameter_resolution import resolve_config_parameters
from scopecat._planning.planner import build_planner_snapshot
from scopecat._relations import ParameterRelationData
from scopecat._runtime.graph import (
    RuntimeGraph,
    build_runtime_graph,
)
from scopecat._runtime.instruments import validate_instruments
from scopecat._workflows.preview import build_run_plan_record
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.instruments.sdk import InstrumentDriver
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.planning.validation import has_blocking_diagnostics, validate_config


@dataclass(frozen=True)
class RuntimeExecutionInvocation:
    """Closed transient execution input after public facade preparation."""

    config: ConfigProfileSnapshot
    experiment: LinkedProgram
    request: RunRequest | None
    instruments: list[InstrumentDriver]
    graph: RuntimeGraph
    plan: RunPlanRecord
    preflight_diagnostics: list[Diagnostic]
    config_source: RunConfigSource | None


def build_runtime_execution_invocation(
    *,
    config: ConfigProfileSnapshot,
    experiment: LinkedProgram,
    request: RunRequest | None,
    instruments: list[InstrumentDriver],
    parameters: ParameterRelationData | None,
    config_source: RunConfigSource | None,
) -> RuntimeExecutionInvocation:
    preflight_diagnostics = validate_config(config) + validate_instruments(
        config=config,
        instruments=instruments,
    )
    if has_blocking_diagnostics(preflight_diagnostics):
        raise ValidationFailed(preflight_diagnostics)
    selected_parameters = (
        parameters if parameters is not None else resolve_config_parameters(config).data
    )
    planner_snapshot = build_planner_snapshot(
        experiment,
        selected_parameters,
    )
    graph = build_runtime_graph(planner_snapshot, config=config)
    return RuntimeExecutionInvocation(
        config=config,
        experiment=experiment,
        request=request,
        instruments=instruments,
        graph=graph,
        plan=build_run_plan_record(planner_snapshot, graph=graph),
        preflight_diagnostics=preflight_diagnostics,
        config_source=config_source,
    )


__all__ = [
    "RuntimeExecutionInvocation",
    "build_runtime_execution_invocation",
]
