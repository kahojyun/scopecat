"""Prepare public execution inputs for transient runtime execution."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat._runtime.graph import (
    RuntimeGraph,
    build_runtime_graph_for_experiment,
)
from scopecat._runtime.instruments import validate_instruments
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.instruments.sdk import InstrumentDriver
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.models.run import RunConfigSource
from scopecat.parameters import ParameterDerivationSet
from scopecat.planning.validation import has_blocking_diagnostics, validate_config


@dataclass(frozen=True)
class RuntimeExecutionInvocation:
    """Closed transient execution input after public facade preparation."""

    config: ConfigProfileSnapshot
    experiment: ExperimentSpec
    instruments: list[InstrumentDriver]
    graph: RuntimeGraph
    preflight_diagnostics: list[Diagnostic]
    config_source: RunConfigSource | None


def build_runtime_execution_invocation(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    instruments: list[InstrumentDriver],
    parameter_view: ParameterViewSnapshot | None,
    parameter_derivations: ParameterDerivationSet | None,
    config_source: RunConfigSource | None,
) -> RuntimeExecutionInvocation:
    preflight_diagnostics = validate_config(config) + validate_instruments(
        config=config,
        instruments=instruments,
    )
    if has_blocking_diagnostics(preflight_diagnostics):
        raise ValidationFailed(preflight_diagnostics)
    selected_parameter_view = parameter_view or build_config_parameters(
        config,
        derivations=parameter_derivations,
    )
    graph = build_runtime_graph_for_experiment(
        experiment,
        selected_parameter_view,
        config=config,
        derivations=parameter_derivations,
    )
    return RuntimeExecutionInvocation(
        config=config,
        experiment=experiment,
        instruments=instruments,
        graph=graph,
        preflight_diagnostics=preflight_diagnostics,
        config_source=config_source,
    )


__all__ = [
    "RuntimeExecutionInvocation",
    "build_runtime_execution_invocation",
]
