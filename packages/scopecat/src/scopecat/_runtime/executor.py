"""Instrument execution orchestration."""

from __future__ import annotations

from pathlib import Path

from scopecat._runtime.cursor import ExecutionCursor
from scopecat._runtime.invocation import (
    RuntimeExecutionInvocation,
    build_runtime_execution_invocation,
)
from scopecat._runtime.observation import emit_run_finished, emit_run_started
from scopecat._runtime.outcome import (
    build_runtime_execution_outcome,
    persist_runtime_execution_outcome,
)
from scopecat._runtime.setup import prepare_runtime_execution
from scopecat.errors import ValidationFailed
from scopecat.experiments import ExperimentSpec
from scopecat.ids import new_run_id
from scopecat.instruments.events import (
    RuntimeEventSink,
    RuntimePayloadObserver,
)
from scopecat.instruments.sdk import InstrumentDriver
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.parameter import ParameterViewSnapshot
from scopecat.models.run import RunConfigSource, RunManifest
from scopecat.parameters import ParameterDerivationSet
from scopecat.planning.validation import has_blocking_diagnostics


def execute_run(
    *,
    config: ConfigProfileSnapshot,
    experiment: ExperimentSpec,
    instruments: list[InstrumentDriver],
    workspace: str | Path,
    parameter_view: ParameterViewSnapshot | None = None,
    parameter_derivations: ParameterDerivationSet | None = None,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
    payload_observer: RuntimePayloadObserver | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    invocation = build_runtime_execution_invocation(
        config=config,
        experiment=experiment,
        instruments=instruments,
        parameter_view=parameter_view,
        parameter_derivations=parameter_derivations,
        config_source=config_source,
    )
    return _execute_invocation(
        invocation=invocation,
        workspace=workspace,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )


def _execute_invocation(
    *,
    invocation: RuntimeExecutionInvocation,
    workspace: str | Path,
    event_sink: RuntimeEventSink | None,
    payload_observer: RuntimePayloadObserver | None,
) -> tuple[RunManifest, ExecutionSummary]:
    run_id = new_run_id()
    setup = prepare_runtime_execution(
        graph=invocation.graph,
        instruments=invocation.instruments,
        preflight_diagnostics=invocation.preflight_diagnostics,
    )
    emit_run_started(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=invocation.experiment.id,
        graph=invocation.graph,
        instrument_ids=sorted(setup.instruments_by_id),
    )
    if has_blocking_diagnostics(setup.diagnostics):
        raise ValidationFailed(setup.diagnostics)

    cursor = ExecutionCursor(
        run_id=run_id,
        experiment_id=invocation.experiment.id,
        graph=invocation.graph,
        instruments=invocation.instruments,
        instruments_by_id=setup.instruments_by_id,
        descriptions_by_id=setup.descriptions_by_id,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    cursor.run()

    outcome = build_runtime_execution_outcome(
        run_id=run_id,
        experiment_id=invocation.experiment.id,
        graph=invocation.graph,
        instrument_ids=sorted(setup.instruments_by_id),
        setup_diagnostics=setup.diagnostics,
        cursor=cursor,
        raw_measurement_schema=setup.raw_measurement_schema,
        config_source=invocation.config_source,
    )
    persist_runtime_execution_outcome(
        workspace=workspace,
        experiment=invocation.experiment,
        config=invocation.config,
        outcome=outcome,
    )
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=invocation.experiment.id,
        status=outcome.status,
        completed_point_count=cursor.completed_point_count,
        point_count=invocation.graph.point_count,
        measurement_count=len(outcome.measurements),
        diagnostic_count=len(outcome.diagnostics),
        compute_evaluated_node_count=cursor.compute_evaluated_node_count,
        compute_reused_node_count=cursor.compute_reused_node_count,
        compute_payload_count=cursor.compute_payload_count,
    )
    if not outcome.success:
        raise ValidationFailed(outcome.diagnostics)
    return outcome.manifest, outcome.summary
