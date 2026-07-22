"""Cycle-accurate deterministic interpreter for fake realtime artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat_quantum import CompiledTargetArtifact, QubitId

from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeArtifact,
    FakeRealtimeRegister,
    FakeRealtimeTarget,
    RtAcquire,
    RtDecrementAndJump,
    RtEmit,
    RtHalt,
    RtJump,
    RtJumpIf,
    RtLabel,
    RtMove,
    RtPlay,
    RtPulseTimeline,
    RtWait,
    RtXor,
)


@dataclass(frozen=True, slots=True)
class FakeRealtimeTraceEvent:
    """One executed instruction at its start tick."""

    shot_index: int
    program_counter: int
    tick: int
    operation: str


@dataclass(frozen=True, slots=True)
class FakeRealtimeRecord:
    """One target-visible measurement or derived classical result."""

    shot_index: int
    result_id: str
    occurrence: int
    value: int
    tick: int


@dataclass(frozen=True, slots=True)
class FakeRealtimeFrame:
    """Final Pauli frame tracked by the fake controller for one shot."""

    shot_index: int
    qubit: QubitId
    x: int
    z: int


@dataclass(frozen=True, slots=True)
class FakeRealtimeRun:
    artifact: FakeRealtimeArtifact
    events: tuple[FakeRealtimeTraceEvent, ...]
    records: tuple[FakeRealtimeRecord, ...]
    frames: tuple[FakeRealtimeFrame, ...]
    shot_end_ticks: tuple[int, ...]
    fingerprint: str


class FakeRealtimeExecutionError(RuntimeError):
    """A valid artifact could not execute under supplied runtime evidence."""


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


class FakeRealtimeRuntime:
    """Interpret immutable artifacts without modeling analog quantum physics."""

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
        frames: list[FakeRealtimeFrame] = []
        end_ticks: list[int] = []
        for shot_index in range(artifact.repetitions):
            shot_frames, end_tick = self._execute_shot(
                artifact,
                shot_index=shot_index,
                cursor=cursor,
                events=events,
                records=records,
            )
            frames.extend(shot_frames)
            end_ticks.append(end_tick)
        selected_events = tuple(events)
        selected_records = tuple(records)
        selected_frames = tuple(frames)
        selected_end_ticks = tuple(end_ticks)
        return FakeRealtimeRun(
            artifact=artifact,
            events=selected_events,
            records=selected_records,
            frames=selected_frames,
            shot_end_ticks=selected_end_ticks,
            fingerprint=stable_content_hash(
                content_fingerprint(
                    (
                        artifact.artifact_fingerprint,
                        selected_events,
                        selected_records,
                        selected_frames,
                        selected_end_ticks,
                    )
                )
            ),
        )

    def _execute_shot(
        self,
        artifact: FakeRealtimeArtifact,
        *,
        shot_index: int,
        cursor: _MeasurementCursor,
        events: list[FakeRealtimeTraceEvent],
        records: list[FakeRealtimeRecord],
    ) -> tuple[tuple[FakeRealtimeFrame, ...], int]:
        instructions = artifact.program.instructions
        labels = dict(artifact.labels)
        registers: dict[FakeRealtimeRegister, int] = {}
        ready_ticks: dict[FakeRealtimeRegister, int] = {}
        frame_values: dict[tuple[QubitId, str], int] = {}
        tick = 0
        pc = 0
        executed = 0
        while pc < len(instructions):
            executed += 1
            if (
                executed
                > self._target.max_instructions * self._target.max_loop_iterations
            ):
                raise FakeRealtimeExecutionError(
                    "realtime program exceeded bounded execution"
                )
            instruction = instructions[pc]
            operation = type(instruction).__name__.removeprefix("Rt").lower()
            events.append(
                FakeRealtimeTraceEvent(
                    shot_index=shot_index,
                    program_counter=pc,
                    tick=tick,
                    operation=operation,
                )
            )
            if isinstance(instruction, RtLabel):
                pc += 1
                continue
            if isinstance(instruction, RtHalt):
                break
            if isinstance(instruction, RtPlay):
                tick += instruction.duration_ticks
                pc += 1
                continue
            if isinstance(instruction, RtAcquire):
                value, occurrence = cursor.take(instruction.result_id)
                tick += instruction.duration_ticks
                registers[instruction.destination] = value
                ready_ticks[instruction.destination] = (
                    tick + self._target.discrimination_latency_ticks
                )
                if instruction.record:
                    records.append(
                        FakeRealtimeRecord(
                            shot_index=shot_index,
                            result_id=instruction.result_id,
                            occurrence=occurrence,
                            value=value,
                            tick=tick,
                        )
                    )
                pc += 1
                continue
            if isinstance(instruction, RtPulseTimeline):
                for acquisition in instruction.acquisitions:
                    value, occurrence = cursor.take(acquisition.result_id)
                    completed_at = (
                        tick + acquisition.start_ticks + acquisition.duration_ticks
                    )
                    registers[acquisition.destination] = value
                    ready_ticks[acquisition.destination] = (
                        completed_at + self._target.discrimination_latency_ticks
                    )
                    if acquisition.record:
                        records.append(
                            FakeRealtimeRecord(
                                shot_index=shot_index,
                                result_id=acquisition.result_id,
                                occurrence=occurrence,
                                value=value,
                                tick=completed_at,
                            )
                        )
                if len(records) > self._target.max_result_records:
                    raise FakeRealtimeExecutionError("realtime result memory exceeded")
                tick += instruction.duration_ticks
                pc += 1
                continue
            if isinstance(instruction, RtWait):
                tick += instruction.duration_ticks
                pc += 1
                continue

            tick += self._target.classical_instruction_ticks
            if isinstance(instruction, RtMove):
                registers[instruction.destination] = (
                    self._read(instruction.source, registers, ready_ticks, tick)
                    if isinstance(instruction.source, FakeRealtimeRegister)
                    else instruction.source
                )
                ready_ticks[instruction.destination] = tick
                pc += 1
                continue
            if isinstance(instruction, RtXor):
                registers[instruction.destination] = self._read(
                    instruction.left, registers, ready_ticks, tick
                ) ^ self._read(instruction.right, registers, ready_ticks, tick)
                ready_ticks[instruction.destination] = tick
                pc += 1
                continue
            if isinstance(instruction, RtJump):
                pc = labels[instruction.target]
                continue
            if isinstance(instruction, RtJumpIf):
                value = self._read(instruction.source, registers, ready_ticks, tick)
                pc = (
                    labels[instruction.target]
                    if value == instruction.equals
                    else pc + 1
                )
                continue
            if isinstance(instruction, RtDecrementAndJump):
                value = (
                    self._read(instruction.counter, registers, ready_ticks, tick) - 1
                )
                registers[instruction.counter] = value
                ready_ticks[instruction.counter] = tick
                pc = labels[instruction.target] if value != 0 else pc + 1
                continue
            if isinstance(instruction, RtEmit):
                value = self._read(instruction.source, registers, ready_ticks, tick)
                records.append(
                    FakeRealtimeRecord(
                        shot_index=shot_index,
                        result_id=instruction.result_id,
                        occurrence=sum(
                            record.result_id == instruction.result_id
                            for record in records
                        ),
                        value=value,
                        tick=tick,
                    )
                )
                if len(records) > self._target.max_result_records:
                    raise FakeRealtimeExecutionError("realtime result memory exceeded")
                pc += 1
                continue
            value = self._read(instruction.source, registers, ready_ticks, tick)
            key = (instruction.qubit, instruction.axis)
            frame_values[key] = frame_values.get(key, 0) ^ (value & 1)
            pc += 1
        else:
            raise FakeRealtimeExecutionError("realtime program terminated without Halt")

        qubits = sorted(
            {qubit for qubit, _axis in frame_values}, key=lambda item: item.value
        )
        return (
            tuple(
                FakeRealtimeFrame(
                    shot_index=shot_index,
                    qubit=qubit,
                    x=frame_values.get((qubit, "x"), 0),
                    z=frame_values.get((qubit, "z"), 0),
                )
                for qubit in qubits
            ),
            tick,
        )

    @staticmethod
    def _read(
        register: FakeRealtimeRegister,
        values: Mapping[FakeRealtimeRegister, int],
        ready_ticks: Mapping[FakeRealtimeRegister, int],
        tick: int,
    ) -> int:
        if register not in values:
            raise FakeRealtimeExecutionError(
                f"realtime register {register.value!r} is uninitialized"
            )
        if tick < ready_ticks[register]:
            raise FakeRealtimeExecutionError(
                f"realtime register {register.value!r} is read before feedback is ready"
            )
        return values[register]


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
    "FakeRealtimeFrame",
    "FakeRealtimeRecord",
    "FakeRealtimeRun",
    "FakeRealtimeRuntime",
    "FakeRealtimeTraceEvent",
]
