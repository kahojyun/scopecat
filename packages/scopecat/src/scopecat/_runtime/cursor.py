"""Execution cursor over the transient runtime graph."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from scopecat._runtime.collect import (
    RuntimeCollectInstruction,
    collect_instruction,
    merge_readback,
)
from scopecat._runtime.compute import ComputeApplySummary, RuntimeComputeCache
from scopecat._runtime.graph import RuntimeGraph, RuntimePoint
from scopecat._runtime.instruments import (
    abort_all,
    cleanup_all,
    diagnostic_from_exception,
    readback_all,
)
from scopecat._runtime.observation import emit_compute_payload_events, emit_event
from scopecat._runtime.state import StateApplySummary, apply_desired_state
from scopecat._runtime.validation import validate_point_outputs
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.events import (
    RuntimeEvent,
    RuntimeEventSink,
    RuntimePayloadObserver,
)
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.models.artifact import CommandPayload
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.results import MeasurementRecord, MeasurementSink, MeasurementValue


@dataclass
class ExecutionPointStats:
    """Point-local runtime counters kept out of persisted run evidence."""

    point_index: int
    changed_field_count: int
    skipped_field_count: int = 0
    state_command_count: int = 0
    compute_evaluated_node_count: int = 0
    compute_reused_node_count: int = 0
    compute_payload_count: int = 0
    payload_count: int = 0
    acquired_record_count: int = 0


@dataclass
class _PointExecutionFrame:
    """Point-local execution state owned by the cursor."""

    point: RuntimePoint
    measurement_count_before: int
    state_summary: StateApplySummary = dataclass_field(
        default_factory=StateApplySummary
    )
    compute_summary: ComputeApplySummary = dataclass_field(
        default_factory=ComputeApplySummary
    )
    observables: dict[str, MeasurementValue] = dataclass_field(default_factory=dict)
    instruments: list[str] = dataclass_field(default_factory=list)
    payloads: dict[str, CommandPayload] = dataclass_field(default_factory=dict)

    @property
    def point_index(self) -> int:
        return self.point.point_index

    def stats(self, *, measurement_count_after: int) -> ExecutionPointStats:
        return ExecutionPointStats(
            point_index=self.point.point_index,
            changed_field_count=self.state_summary.changed_field_count,
            skipped_field_count=self.state_summary.skipped_field_count,
            state_command_count=self.state_summary.state_command_count,
            compute_evaluated_node_count=(self.compute_summary.evaluated_node_count),
            compute_reused_node_count=self.compute_summary.reused_node_count,
            compute_payload_count=self.compute_summary.payload_count,
            payload_count=self.state_summary.payload_count,
            acquired_record_count=measurement_count_after
            - self.measurement_count_before,
        )


@dataclass
class ExecutionCursor:
    """Internal point cursor over the transient runtime graph."""

    run_id: str
    experiment_id: str
    graph: RuntimeGraph
    instruments: list[InstrumentDriver]
    instruments_by_id: dict[str, InstrumentDriver]
    descriptions_by_id: dict[str, InstrumentDescription]
    event_sink: RuntimeEventSink | None = None
    payload_observer: RuntimePayloadObserver | None = None
    sink: MeasurementSink = dataclass_field(init=False)
    initial_state: list[InstrumentStateSnapshot] = dataclass_field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = dataclass_field(default_factory=list)
    current_states: dict[str, InstrumentStateSnapshot] = dataclass_field(
        default_factory=dict
    )
    point_stats: list[ExecutionPointStats] = dataclass_field(default_factory=list)
    diagnostics: list[Diagnostic] = dataclass_field(default_factory=list)
    compute_cache: RuntimeComputeCache = dataclass_field(
        default_factory=RuntimeComputeCache
    )

    def __post_init__(self) -> None:
        self.sink = MeasurementSink(run_id=self.run_id)

    @property
    def measurements(self) -> tuple[MeasurementRecord, ...]:
        return tuple(self.sink.measurements)

    @property
    def completed_point_count(self) -> int:
        return len(self.point_stats)

    @property
    def compute_evaluated_node_count(self) -> int:
        return sum(point.compute_evaluated_node_count for point in self.point_stats)

    @property
    def compute_reused_node_count(self) -> int:
        return sum(point.compute_reused_node_count for point in self.point_stats)

    @property
    def compute_payload_count(self) -> int:
        return sum(point.compute_payload_count for point in self.point_stats)

    @property
    def changed_field_count(self) -> int:
        return sum(point.changed_field_count for point in self.point_stats)

    @property
    def skipped_field_count(self) -> int:
        return sum(point.skipped_field_count for point in self.point_stats)

    @property
    def state_command_count(self) -> int:
        return sum(point.state_command_count for point in self.point_stats)

    @property
    def state_payload_count(self) -> int:
        return sum(point.payload_count for point in self.point_stats)

    def run(self) -> None:
        try:
            self.initial_state = readback_all(self.instruments, self.diagnostics)
            self.current_states = {
                state.instrument_id: state for state in self.initial_state
            }
            if not has_blocking_diagnostics(self.diagnostics):
                for point_program in self.graph.points:
                    self.advance(point_program)
                    if has_blocking_diagnostics(self.diagnostics):
                        break
            self.final_state = readback_all(self.instruments, self.diagnostics)
        finally:
            if has_blocking_diagnostics(self.diagnostics):
                abort_all(self.instruments, self.diagnostics)
            else:
                cleanup_all(self.instruments, self.diagnostics)

    def advance(self, point_program: RuntimePoint) -> None:
        frame = _PointExecutionFrame(
            point=point_program,
            measurement_count_before=len(self.sink.measurements),
        )
        self._emit_point_started(frame)
        frame.payloads, frame.compute_summary = self._evaluate_compute(frame)
        if has_blocking_diagnostics(self.diagnostics):
            return
        frame.state_summary = apply_desired_state(
            desired=list(frame.point.desired_state),
            current_states=self.current_states,
            instruments_by_id=self.instruments_by_id,
            descriptions_by_id=self.descriptions_by_id,
            payloads=frame.payloads,
            route_bindings=list(frame.point.route_bindings),
            diagnostics=self.diagnostics,
        )
        self._emit_state_applied(frame)
        if has_blocking_diagnostics(self.diagnostics):
            return

        frame.observables, frame.instruments = self._collect_point(frame)
        validate_point_outputs(
            point_index=frame.point_index,
            expected_output_ids=self.graph.observable_output_ids,
            observables=frame.observables,
            diagnostics=self.diagnostics,
        )
        if frame.observables:
            self.sink.record(
                point_index=frame.point_index,
                coordinates=dict(frame.point.coordinates),
                observables=frame.observables,
                metadata={"instruments": sorted(set(frame.instruments))},
            )
            self._emit_record_emitted(frame)
        self.point_stats.append(
            frame.stats(measurement_count_after=len(self.sink.measurements))
        )

    def _collect_point(
        self, frame: _PointExecutionFrame
    ) -> tuple[dict[str, MeasurementValue], list[str]]:
        observables: dict[str, MeasurementValue] = {}
        instruments: list[str] = []
        for instrument in self.instruments:
            collect = collect_instruction(
                point=frame.point,
                instrument_id=instrument.instrument_id,
                point_count=self.graph.point_count,
            )
            if collect is None:
                continue
            self._emit_collect_started(frame, instrument, collect)
            try:
                readback = instrument.collect(collect.command)
            except Exception as error:
                self.diagnostics.append(
                    diagnostic_from_exception(
                        "error",
                        "instrument_collect_failed",
                        "instrument record collection failed for "
                        f"{instrument.instrument_id}: "
                        f"{type(error).__name__}: {error}",
                        instrument.instrument_id,
                        error,
                    )
                )
                continue
            self._emit_collect_finished(frame, instrument, readback)
            self.diagnostics.extend(readback.diagnostics)
            merge_readback(
                point_index=frame.point_index,
                command=collect.command,
                record_bindings=collect.record_bindings,
                readback=readback,
                observables=observables,
                instruments=instruments,
                diagnostics=self.diagnostics,
            )
        return observables, instruments

    def _evaluate_compute(
        self,
        frame: _PointExecutionFrame,
    ) -> tuple[dict[str, CommandPayload], ComputeApplySummary]:
        result = self.compute_cache.evaluate_point(
            point=frame.point,
            graph=self.graph,
        )
        self.diagnostics.extend(result.diagnostics)
        emit_compute_payload_events(
            event_sink=self.event_sink,
            payload_observer=self.payload_observer,
            run_id=self.run_id,
            experiment_id=self.experiment_id,
            graph=self.graph,
            payloads=result.payloads,
            progress=self._progress(),
        )
        return result.payloads, result.summary

    def _progress(self, *, completed_points: int | None = None) -> dict[str, int]:
        return {
            "completed_points": (
                self.completed_point_count
                if completed_points is None
                else completed_points
            ),
            "total_points": self.graph.point_count,
        }

    def _emit(self, event: RuntimeEvent) -> None:
        emit_event(self.event_sink, event)

    def _emit_point_started(self, frame: _PointExecutionFrame) -> None:
        self._emit(
            RuntimeEvent(
                kind="point_started",
                run_id=self.run_id,
                experiment_id=self.experiment_id,
                point_index=frame.point_index,
                progress=self._progress(),
                summary={
                    "coordinate_ids": sorted(frame.point.coordinates),
                    "compute_step_count": len(frame.point.compute_steps),
                    "compute_node_ids": [
                        step.node_id for step in frame.point.compute_steps
                    ],
                    "route_count": len(frame.point.route_bindings),
                    "state_resource_count": len(frame.point.desired_state),
                },
            )
        )

    def _emit_state_applied(self, frame: _PointExecutionFrame) -> None:
        self._emit(
            RuntimeEvent(
                kind="state_applied",
                run_id=self.run_id,
                experiment_id=self.experiment_id,
                point_index=frame.point_index,
                progress=self._progress(),
                summary={
                    "compute_evaluated_node_count": (
                        frame.compute_summary.evaluated_node_count
                    ),
                    "compute_reused_node_count": (
                        frame.compute_summary.reused_node_count
                    ),
                    "compute_payload_count": frame.compute_summary.payload_count,
                    "changed_field_count": frame.state_summary.changed_field_count,
                    "skipped_field_count": frame.state_summary.skipped_field_count,
                    "state_command_count": frame.state_summary.state_command_count,
                    "payload_count": frame.state_summary.payload_count,
                },
            )
        )

    def _emit_collect_started(
        self,
        frame: _PointExecutionFrame,
        instrument: InstrumentDriver,
        collect: RuntimeCollectInstruction,
    ) -> None:
        self._emit(
            RuntimeEvent(
                kind="collect_started",
                run_id=self.run_id,
                experiment_id=self.experiment_id,
                point_index=frame.point_index,
                instrument_id=instrument.instrument_id,
                progress=self._progress(),
                summary={
                    "request_count": len(collect.command.requests),
                    "product_ids": [request.id for request in collect.command.requests],
                },
            )
        )

    def _emit_collect_finished(
        self,
        frame: _PointExecutionFrame,
        instrument: InstrumentDriver,
        readback: InstrumentReadback,
    ) -> None:
        self._emit(
            RuntimeEvent(
                kind="collect_finished",
                run_id=self.run_id,
                experiment_id=self.experiment_id,
                point_index=frame.point_index,
                instrument_id=instrument.instrument_id,
                progress=self._progress(),
                summary={
                    "value_count": len(readback.values),
                    "diagnostic_count": len(readback.diagnostics),
                },
            )
        )

    def _emit_record_emitted(
        self,
        frame: _PointExecutionFrame,
    ) -> None:
        self._emit(
            RuntimeEvent(
                kind="record_emitted",
                run_id=self.run_id,
                experiment_id=self.experiment_id,
                point_index=frame.point_index,
                progress=self._progress(
                    completed_points=self.completed_point_count + 1
                ),
                summary={
                    "observable_ids": sorted(frame.observables),
                    "instrument_ids": sorted(set(frame.instruments)),
                },
            )
        )
