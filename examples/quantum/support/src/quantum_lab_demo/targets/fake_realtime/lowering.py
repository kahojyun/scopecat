"""Lower legal structured pulses and schedule feedback for the fake ISA."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from decimal import Decimal

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat_quantum import (
    Acquire,
    Delay,
    PauliFrameXor,
    Play,
    RealtimeBitStateInit,
    RealtimeBitStateRead,
    RealtimeBitStateWrite,
    RealtimeBitXor,
    RealtimeResultEmit,
    RealtimeStateId,
    RealtimeValueId,
    StructuredPulseBlock,
    StructuredPulseNode,
    StructuredPulseParallel,
    StructuredPulseRepeat,
    StructuredPulseSequence,
    StructuredQuantumPulseProgram,
    TargetAcquisitionLayout,
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntryId,
    TargetCompilerId,
)

from quantum_lab_demo.targets.fake_realtime.legality import (
    LegalizedFakeRealtimeProgram,
    legalize_fake_realtime_program,
)
from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeCompileRequest,
    FakeRealtimeInstruction,
    FakeRealtimeProgram,
    FakeRealtimeRegister,
    FakeRealtimeTarget,
    RtAcquire,
    RtDecrementAndJump,
    RtEmit,
    RtFrameXor,
    RtHalt,
    RtJump,
    RtJumpIf,
    RtLabel,
    RtMove,
    RtPlay,
    RtPulseTimeline,
    RtScheduledAcquire,
    RtScheduledPlay,
    RtWait,
    RtXor,
)

type _NodePath = tuple[str, ...]


def prepare_fake_realtime_request(
    entry_id: TargetCompileEntryId,
    program: StructuredQuantumPulseProgram,
    *,
    target: FakeRealtimeTarget,
    compiler_id: TargetCompilerId,
    result_layouts: tuple[TargetAcquisitionLayout, ...],
    repetitions: int,
) -> FakeRealtimeCompileRequest:
    """Legalize, lower, schedule, and close one target compile request."""

    legal = legalize_fake_realtime_program(
        program,
        target=target,
        entry_id=entry_id,
    )
    assembler = _Assembler(entry_id=entry_id, target=target, legal=legal)
    assembler.lower(program.body, path=("body",))
    assembler.instructions.append(RtHalt())
    instructions = _schedule_feedback(
        tuple(assembler.instructions),
        tuple(assembler.feedback_uses),
        target=target,
        entry_id=entry_id,
    )
    return FakeRealtimeCompileRequest(
        target_id=target.id,
        compiler_id=compiler_id,
        capability_fingerprint=target.capability_fingerprint,
        entry_id=entry_id,
        program=FakeRealtimeProgram(
            id=f"{program.source_program_id.value}.realtime",
            instructions=instructions,
        ),
        result_layouts=result_layouts,
        repetitions=repetitions,
        realtime_result_provenance=program.realtime_result_provenance,
    )


@dataclass(frozen=True, slots=True)
class _FeedbackUse:
    instruction_index: int
    source: FakeRealtimeRegister
    latency_ticks: int


@dataclass(slots=True)
class _Assembler:
    entry_id: TargetCompileEntryId
    target: FakeRealtimeTarget
    legal: LegalizedFakeRealtimeProgram
    instructions: list[FakeRealtimeInstruction] = field(default_factory=list)
    feedback_uses: list[_FeedbackUse] = field(default_factory=list)
    result_registers: dict[RealtimeValueId, FakeRealtimeRegister] = field(
        default_factory=dict
    )
    state_registers: dict[RealtimeStateId, FakeRealtimeRegister] = field(
        default_factory=dict
    )
    next_register: int = 0
    next_label: int = 0

    def lower(self, node: StructuredPulseNode, *, path: _NodePath) -> None:
        if isinstance(node, RealtimeBitStateInit):
            register = self._register("state")
            self.state_registers[node.state_id] = register
            self.instructions.append(RtMove(register, node.value))
            return
        if isinstance(node, RealtimeBitStateRead):
            register = self._register("state-read")
            self.result_registers[node.output_id] = register
            self.instructions.append(
                RtMove(register, self.state_registers[node.state_id])
            )
            return
        if isinstance(node, RealtimeBitStateWrite):
            source = self.result_registers[node.source.value_id]
            index = len(self.instructions)
            self.instructions.append(
                RtMove(self.state_registers[node.state_id], source)
            )
            self._record_value_use(node.source.value_id, source, index)
            return
        if isinstance(node, RealtimeBitXor):
            left = self.result_registers[node.left.value_id]
            right = self.result_registers[node.right.value_id]
            output = self._register("xor")
            self.result_registers[node.output_id] = output
            index = len(self.instructions)
            self.instructions.append(RtXor(output, left, right))
            self._record_value_use(node.left.value_id, left, index)
            self._record_value_use(node.right.value_id, right, index)
            return
        if isinstance(node, RealtimeResultEmit):
            source = self.result_registers[node.source.value_id]
            index = len(self.instructions)
            self.instructions.append(RtEmit(node.result_id.local_id, source))
            self._record_value_use(node.source.value_id, source, index)
            return
        if isinstance(node, PauliFrameXor):
            source = self.result_registers[node.source.value_id]
            index = len(self.instructions)
            self.instructions.append(RtFrameXor(node.qubit, node.axis, source))
            self._record_value_use(node.source.value_id, source, index)
            return
        if isinstance(node, StructuredPulseBlock | StructuredPulseParallel):
            self._lower_pulse_region(path)
            return
        if isinstance(node, StructuredPulseSequence):
            for index, operation in enumerate(node.operations):
                self.lower(operation, path=(*path, f"sequence[{index}]"))
            return
        if isinstance(node, StructuredPulseRepeat):
            if node.count == 0:
                return
            counter = self._register("loop")
            loop = self._label("loop")
            self.instructions.extend((RtMove(counter, node.count), RtLabel(loop)))
            self.lower(node.operation, path=(*path, "repeat-body"))
            self.instructions.append(RtDecrementAndJump(counter, loop))
            return

        register = self.result_registers[node.condition.value_id]
        dependency = self.legal.feedback_dependency(path)
        when_true = self._label("when-true")
        done = self._label("conditional-done")
        jump_index = len(self.instructions)
        self.instructions.append(RtJumpIf(register, node.equals, when_true))
        self.feedback_uses.append(
            _FeedbackUse(
                instruction_index=jump_index,
                source=register,
                latency_ticks=dependency.latency_ticks,
            )
        )
        self.lower(node.when_false, path=(*path, "when-false"))
        self.instructions.extend((RtJump(done), RtLabel(when_true)))
        self.lower(node.when_true, path=(*path, "when-true"))
        self.instructions.append(RtLabel(done))

    def _record_value_use(
        self,
        value_id: RealtimeValueId,
        register: FakeRealtimeRegister,
        instruction_index: int,
    ) -> None:
        latency = self.legal.feedback_value_latency(value_id)
        if latency:
            self.feedback_uses.append(
                _FeedbackUse(
                    instruction_index=instruction_index,
                    source=register,
                    latency_ticks=latency,
                )
            )

    def _lower_pulse_region(self, path: _NodePath) -> None:
        region = self.legal.pulse_region(path)
        scheduled = region.program
        duration_ticks = self._ticks(scheduled.duration_seconds)
        outputs_by_slot = {
            output.acquisition_slot_id: output for output in region.realtime_bit_outputs
        }
        plays: list[RtScheduledPlay] = []
        acquisitions: list[RtScheduledAcquire] = []
        for event in scheduled.events:
            instruction = event.instruction
            start_ticks = self._ticks(event.start_seconds)
            event_ticks = self._ticks(event.duration_seconds)
            if isinstance(instruction, Play):
                output = self.target.output_for(instruction.signal)
                assert output is not None  # noqa: S101 - established by legality
                plays.append(
                    RtScheduledPlay(
                        output=output,
                        waveform_id=(
                            "waveform:"
                            + stable_content_hash(
                                content_fingerprint(instruction.envelope)
                            )
                        ),
                        start_ticks=start_ticks,
                        duration_ticks=event_ticks,
                    )
                )
                continue
            if isinstance(instruction, Acquire):
                input_id = self.target.input_for(instruction.signal)
                assert input_id is not None  # noqa: S101 - established by legality
                register = self._register("acquire")
                realtime_output = outputs_by_slot.get(instruction.slot_id)
                if realtime_output is not None:
                    self.result_registers[realtime_output.value_id] = register
                acquisitions.append(
                    RtScheduledAcquire(
                        input=input_id,
                        result_id=instruction.slot_id.local_id,
                        destination=register,
                        start_ticks=start_ticks,
                        duration_ticks=event_ticks,
                    )
                )
                continue
            assert isinstance(instruction, Delay)  # noqa: S101 - target legality

        if plays or acquisitions:
            self.instructions.append(
                RtPulseTimeline(
                    duration_ticks=duration_ticks,
                    plays=tuple(plays),
                    acquisitions=tuple(acquisitions),
                )
            )
        elif duration_ticks:
            self.instructions.append(RtWait(duration_ticks))

    def _register(self, role: str) -> FakeRealtimeRegister:
        register = FakeRealtimeRegister(f"{role}-{self.next_register}")
        self.next_register += 1
        return register

    def _label(self, role: str) -> str:
        label = f"{role}-{self.next_label}"
        self.next_label += 1
        return label

    def _ticks(self, seconds: Decimal) -> int:
        value = seconds * Decimal(self.target.clock_hz)
        assert value == value.to_integral_value()  # noqa: S101 - target legality
        return int(value)


def _schedule_feedback(
    instructions: tuple[FakeRealtimeInstruction, ...],
    uses: tuple[_FeedbackUse, ...],
    *,
    target: FakeRealtimeTarget,
    entry_id: TargetCompileEntryId,
) -> tuple[FakeRealtimeInstruction, ...]:
    """Insert the minimum route-aware wait required on the shortest CFG path."""

    waits: dict[int, int] = {}
    for use in sorted(uses, key=lambda item: item.instruction_index):
        elapsed = _shortest_elapsed_from_definition(
            instructions,
            source=use.source,
            use_index=use.instruction_index,
            target=target,
            planned_waits=waits,
        )
        if elapsed is None:
            raise TargetCompilationError(
                (
                    TargetCompilationIssue(
                        dimension=TargetCompilationIssueDimension.PROGRAM,
                        code="fake_realtime_feedback_definition_unreachable",
                        message=(
                            f"register {use.source.value!r} has no acquisition "
                            "definition reaching its feedback use"
                        ),
                        entry_id=entry_id,
                    ),
                )
            )
        remaining = max(0, use.latency_ticks - elapsed)
        if remaining:
            waits[use.instruction_index] = max(
                waits.get(use.instruction_index, 0),
                remaining,
            )

    return tuple(
        selected
        for index, instruction in enumerate(instructions)
        for selected in (
            *((RtWait(waits[index]),) if index in waits else ()),
            instruction,
        )
    )


def _shortest_elapsed_from_definition(
    instructions: tuple[FakeRealtimeInstruction, ...],
    *,
    source: FakeRealtimeRegister,
    use_index: int,
    target: FakeRealtimeTarget,
    planned_waits: dict[int, int],
) -> int | None:
    successors = _successors(instructions)
    queue: list[tuple[int, int]] = []
    for index, instruction in enumerate(instructions):
        residual = _acquisition_definition_residual(instruction, source)
        if residual is None:
            continue
        for successor in successors[index]:
            heapq.heappush(queue, (residual, successor))

    best: dict[int, int] = {}
    while queue:
        elapsed, index = heapq.heappop(queue)
        elapsed += planned_waits.get(index, 0)
        if elapsed >= best.get(index, elapsed + 1):
            continue
        best[index] = elapsed
        if index == use_index:
            return elapsed
        instruction = instructions[index]
        if _defines_register(instruction, source):
            continue
        next_elapsed = elapsed + _instruction_ticks(instruction, target)
        for successor in successors[index]:
            heapq.heappush(queue, (next_elapsed, successor))
    return None


def _successors(
    instructions: tuple[FakeRealtimeInstruction, ...],
) -> tuple[tuple[int, ...], ...]:
    labels = {
        instruction.name: index
        for index, instruction in enumerate(instructions)
        if isinstance(instruction, RtLabel)
    }
    selected: list[tuple[int, ...]] = []
    for index, instruction in enumerate(instructions):
        fallthrough = (index + 1,) if index + 1 < len(instructions) else ()
        if isinstance(instruction, RtHalt):
            selected.append(())
        elif isinstance(instruction, RtJump):
            selected.append((labels[instruction.target],))
        elif isinstance(instruction, RtJumpIf | RtDecrementAndJump):
            selected.append((*fallthrough, labels[instruction.target]))
        else:
            selected.append(fallthrough)
    return tuple(selected)


def _acquisition_definition_residual(
    instruction: FakeRealtimeInstruction,
    register: FakeRealtimeRegister,
) -> int | None:
    if isinstance(instruction, RtAcquire) and instruction.destination == register:
        return 0
    if isinstance(instruction, RtPulseTimeline):
        for acquisition in instruction.acquisitions:
            if acquisition.destination == register:
                completed = acquisition.start_ticks + acquisition.duration_ticks
                return instruction.duration_ticks - completed
    return None


def _defines_register(
    instruction: FakeRealtimeInstruction,
    register: FakeRealtimeRegister,
) -> bool:
    if isinstance(instruction, RtMove | RtXor | RtAcquire):
        return instruction.destination == register
    return isinstance(instruction, RtPulseTimeline) and any(
        acquisition.destination == register for acquisition in instruction.acquisitions
    )


def _instruction_ticks(
    instruction: FakeRealtimeInstruction,
    target: FakeRealtimeTarget,
) -> int:
    if isinstance(instruction, RtPlay | RtAcquire):
        return instruction.duration_ticks
    if isinstance(instruction, RtPulseTimeline | RtWait):
        return instruction.duration_ticks
    if isinstance(instruction, RtLabel | RtHalt):
        return 0
    return target.classical_instruction_ticks


__all__ = ["prepare_fake_realtime_request"]
