"""Deterministic recursive execution of structured fake realtime artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat_quantum._ids import RealtimeValueId
from scopecat_quantum.programs import (
    StructuredPulseBlock,
    StructuredPulseNode,
    StructuredPulseParallel,
    StructuredPulseRepeat,
    StructuredPulseSequence,
)
from scopecat_quantum.pulses import Acquire, schedule
from scopecat_quantum.targets import CompiledTargetArtifact

from quantum_lab_demo.targets.fake_realtime.compiler import (
    controlled_outputs,
    pulse_region,
)
from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeArtifact,
    FakeRealtimeInputId,
    FakeRealtimeTarget,
)

type _NodePath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FakeRealtimeTraceEvent:
    """One structured operation observed at its start tick."""

    shot_index: int
    path: _NodePath
    tick: int
    operation: str


@dataclass(frozen=True, slots=True)
class FakeRealtimeRecord:
    """One target-visible acquisition result."""

    shot_index: int
    result_id: str
    occurrence: int
    value: int
    tick: int


@dataclass(frozen=True, slots=True)
class FakeRealtimeRun:
    artifact: FakeRealtimeArtifact
    events: tuple[FakeRealtimeTraceEvent, ...]
    records: tuple[FakeRealtimeRecord, ...]
    shot_end_ticks: tuple[int, ...]
    fingerprint: str


class FakeRealtimeExecutionError(RuntimeError):
    """A valid artifact could not execute under supplied measurement evidence."""


class _MeasurementCursor:
    def __init__(self, values: Mapping[str, Sequence[int]]) -> None:
        self._values = {name: tuple(items) for name, items in values.items()}
        self._offsets: dict[str, int] = {}

    def take(self, result_id: str) -> tuple[int, int]:
        occurrence = self._offsets.get(result_id, 0)
        values = self._values.get(result_id, ())
        if occurrence >= len(values):
            raise FakeRealtimeExecutionError(
                f"measurement script has no value for {result_id!r} "
                f"occurrence {occurrence}"
            )
        value = values[occurrence]
        if value not in (0, 1):
            raise FakeRealtimeExecutionError("measurement script values must be bits")
        self._offsets[result_id] = occurrence + 1
        return value, occurrence


@dataclass(frozen=True, slots=True)
class _RealtimeValue:
    value: int
    source: FakeRealtimeInputId
    completed_at: int


@dataclass(slots=True)
class _ShotState:
    shot_index: int
    cursor: _MeasurementCursor
    events: list[FakeRealtimeTraceEvent]
    records: list[FakeRealtimeRecord]
    tick: int = 0
    values: dict[RealtimeValueId, _RealtimeValue] = field(default_factory=dict)


class FakeRealtimeRuntime:
    """Execute the target artifact's structured pulse program directly."""

    def __init__(self, target: FakeRealtimeTarget) -> None:
        self._target = target

    def execute(
        self,
        compiled: CompiledTargetArtifact[FakeRealtimeArtifact],
        measurements: Mapping[str, Sequence[int]],
    ) -> FakeRealtimeRun:
        artifact = _verified_artifact(compiled)
        if artifact.target_id != self._target.id:
            raise ValueError("realtime artifact belongs to another target")
        if artifact.capability_fingerprint != self._target.capability_fingerprint:
            raise ValueError("realtime artifact capability fingerprint is stale")

        cursor = _MeasurementCursor(measurements)
        events: list[FakeRealtimeTraceEvent] = []
        records: list[FakeRealtimeRecord] = []
        end_ticks: list[int] = []
        for shot_index in range(artifact.repetitions):
            state = _ShotState(shot_index, cursor, events, records)
            self._execute_node(artifact.program.body, state, ("body",))
            end_ticks.append(state.tick)

        selected_events = tuple(events)
        selected_records = tuple(records)
        selected_end_ticks = tuple(end_ticks)
        return FakeRealtimeRun(
            artifact=artifact,
            events=selected_events,
            records=selected_records,
            shot_end_ticks=selected_end_ticks,
            fingerprint=stable_content_hash(
                content_fingerprint(
                    (
                        artifact.artifact_fingerprint,
                        selected_events,
                        selected_records,
                        selected_end_ticks,
                    )
                )
            ),
        )

    def _execute_node(
        self,
        node: StructuredPulseNode,
        state: _ShotState,
        path: _NodePath,
    ) -> None:
        if isinstance(node, StructuredPulseBlock | StructuredPulseParallel):
            self._execute_pulse_region(node, state, path)
            return
        if isinstance(node, StructuredPulseSequence):
            for index, operation in enumerate(node.operations):
                self._execute_node(operation, state, (*path, f"sequence[{index}]"))
            return
        if isinstance(node, StructuredPulseRepeat):
            state.events.append(
                FakeRealtimeTraceEvent(
                    state.shot_index,
                    path,
                    state.tick,
                    "repeat",
                )
            )
            for index in range(node.count):
                self._execute_node(
                    node.operation,
                    state,
                    (*path, f"repeat[{index}]"),
                )
            return

        value = state.values.get(node.condition.value_id)
        if value is None:
            raise FakeRealtimeExecutionError(
                f"condition value {node.condition.value_id.value!r} is unavailable"
            )
        destinations = controlled_outputs(node, self._target)
        route_latencies = [
            latency
            for destination in destinations
            if (latency := self._target.feedback_latency(value.source, destination))
            is not None
        ]
        state.tick = max(
            state.tick,
            value.completed_at
            + max(self._target.discrimination_latency_ticks, *route_latencies),
        )
        state.events.append(
            FakeRealtimeTraceEvent(
                state.shot_index,
                path,
                state.tick,
                "conditional",
            )
        )
        state.tick += self._target.decision_latency_ticks
        branch = node.when_true if value.value == node.equals else node.when_false
        self._execute_node(
            branch,
            state,
            (*path, "when-true" if branch is node.when_true else "when-false"),
        )

    def _execute_pulse_region(
        self,
        node: StructuredPulseBlock | StructuredPulseParallel,
        state: _ShotState,
        path: _NodePath,
    ) -> None:
        program, outputs = pulse_region(node)
        scheduled = schedule(program)
        start_tick = state.tick
        state.events.append(
            FakeRealtimeTraceEvent(
                state.shot_index,
                path,
                start_tick,
                "pulse",
            )
        )
        outputs_by_slot = {output.acquisition_slot_id: output for output in outputs}
        for event in scheduled.events:
            instruction = event.instruction
            if not isinstance(instruction, Acquire):
                continue
            result_id = instruction.slot_id.local_id
            value, occurrence = state.cursor.take(result_id)
            completed_at = (
                start_tick
                + self._ticks(event.start_seconds)
                + self._ticks(event.duration_seconds)
            )
            state.records.append(
                FakeRealtimeRecord(
                    shot_index=state.shot_index,
                    result_id=result_id,
                    occurrence=occurrence,
                    value=value,
                    tick=completed_at,
                )
            )
            output = outputs_by_slot.get(instruction.slot_id)
            if output is not None:
                source = self._target.input_for(instruction.signal)
                if source is None:
                    raise AssertionError("compiled acquisition lost its target input")
                state.values[output.value_id] = _RealtimeValue(
                    value,
                    source,
                    completed_at,
                )
        state.tick += self._ticks(scheduled.duration_seconds)

    def _ticks(self, seconds: Decimal) -> int:
        value = seconds * Decimal(self._target.clock_hz)
        if value != value.to_integral_value():
            raise AssertionError("compiled realtime timing lost clock alignment")
        return int(value)


def _verified_artifact(
    compiled: CompiledTargetArtifact[FakeRealtimeArtifact],
) -> FakeRealtimeArtifact:
    artifact = compiled.artifact
    if (
        compiled.artifact_id != artifact.id
        or compiled.target_id != artifact.target_id
        or compiled.compiler_id != artifact.compiler_id
        or compiled.capability_fingerprint != artifact.capability_fingerprint
        or compiled.artifact_fingerprint != artifact.artifact_fingerprint
        or compiled.source_entry_ids != artifact.source_entry_ids
        or compiled.repetitions != artifact.repetitions
    ):
        raise ValueError("compiled realtime artifact correlation mismatch")
    return artifact


__all__ = [
    "FakeRealtimeExecutionError",
    "FakeRealtimeRecord",
    "FakeRealtimeRun",
    "FakeRealtimeRuntime",
    "FakeRealtimeTraceEvent",
]
