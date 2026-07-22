"""Control-flow and resource verifier for fake realtime machine programs."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat_quantum import (
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
)

from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeCompileRequest,
    FakeRealtimeInstruction,
    FakeRealtimeRegister,
    FakeRealtimeTarget,
    RtDecrementAndJump,
    RtEmit,
    RtHalt,
    RtJump,
    RtJumpIf,
    RtLabel,
    RtMove,
    RtPulseTimeline,
    RtWait,
    RtXor,
)


@dataclass(frozen=True, slots=True)
class VerifiedFakeRealtimeRequest:
    """Compile request whose machine CFG, timing, and record shape are proven."""

    request: FakeRealtimeCompileRequest
    labels: tuple[tuple[str, int], ...]


def verify_fake_realtime_request(
    request: FakeRealtimeCompileRequest,
    target: FakeRealtimeTarget,
) -> VerifiedFakeRealtimeRequest:
    """Verify finite resources, CFG safety, register flow, and result records."""

    instructions = request.program.instructions
    issues: list[TargetCompilationIssue] = []
    _verify_finite_resources(request, target, issues)
    labels = _verify_labels_and_targets(request, issues)
    _verify_physical_operands(request, target, issues)
    _verify_record_layout(request, issues)
    if labels is not None:
        successors = _successors(instructions, dict(labels))
        _verify_termination(request, target, successors, issues)
        _verify_register_flow(request, target, successors, issues)
    if issues:
        raise TargetCompilationError(tuple(issues))
    assert labels is not None  # noqa: S101 - label issues would have raised
    return VerifiedFakeRealtimeRequest(request=request, labels=labels)


def _verify_finite_resources(
    request: FakeRealtimeCompileRequest,
    target: FakeRealtimeTarget,
    issues: list[TargetCompilationIssue],
) -> None:
    instructions = request.program.instructions
    executable_count = sum(not isinstance(item, RtLabel) for item in instructions)
    if executable_count > target.max_instructions:
        _issue(
            request,
            issues,
            "fake_realtime_instruction_limit_exceeded",
            (
                f"program uses {executable_count} instructions; target limit is "
                f"{target.max_instructions}"
            ),
        )
    registers = _registers(instructions)
    if len(registers) > target.max_registers:
        _issue(
            request,
            issues,
            "fake_realtime_register_limit_exceeded",
            (
                f"program uses {len(registers)} registers; target limit is "
                f"{target.max_registers}"
            ),
        )
    waveforms = {
        play.waveform_id
        for item in instructions
        if isinstance(item, RtPulseTimeline)
        for play in item.plays
    }
    if len(waveforms) > target.max_waveforms:
        _issue(
            request,
            issues,
            "fake_realtime_waveform_limit_exceeded",
            (
                f"program uses {len(waveforms)} waveforms; target limit is "
                f"{target.max_waveforms}"
            ),
        )
    result_record_count = len(request.acquisition_addresses) * request.repetitions
    if result_record_count > target.max_result_records:
        _issue(
            request,
            issues,
            "fake_realtime_result_memory_exceeded",
            (
                f"request emits {result_record_count} result records; target limit "
                f"is {target.max_result_records}"
            ),
        )


def _verify_labels_and_targets(
    request: FakeRealtimeCompileRequest,
    issues: list[TargetCompilationIssue],
) -> tuple[tuple[str, int], ...] | None:
    instructions = request.program.instructions
    if not isinstance(instructions[-1], RtHalt):
        _issue(
            request,
            issues,
            "fake_realtime_missing_halt",
            "realtime programs must end with Halt",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
    labels = tuple(
        (instruction.name, index)
        for index, instruction in enumerate(instructions)
        if isinstance(instruction, RtLabel)
    )
    label_names = tuple(name for name, _index in labels)
    if len(set(label_names)) != len(label_names):
        _issue(
            request,
            issues,
            "fake_realtime_duplicate_label",
            "realtime program labels must be unique",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
        return None
    known = set(label_names)
    unknown = {
        instruction.target
        for instruction in instructions
        if isinstance(instruction, RtJump | RtJumpIf | RtDecrementAndJump)
        if instruction.target not in known
    }
    for target_name in sorted(unknown):
        _issue(
            request,
            issues,
            "fake_realtime_unknown_jump_target",
            f"jump target {target_name!r} is not declared",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
    return None if unknown else labels


def _verify_physical_operands(
    request: FakeRealtimeCompileRequest,
    target: FakeRealtimeTarget,
    issues: list[TargetCompilationIssue],
) -> None:
    for instruction in request.program.instructions:
        if isinstance(instruction, RtPulseTimeline):
            for play in instruction.plays:
                if play.output not in target.outputs:
                    _issue(
                        request,
                        issues,
                        "fake_realtime_output_unbound",
                        f"output {play.output.value!r} is not configured",
                    )
            for acquisition in instruction.acquisitions:
                if acquisition.input not in target.inputs:
                    _issue(
                        request,
                        issues,
                        "fake_realtime_input_unbound",
                        f"input {acquisition.input.value!r} is not configured",
                    )


def _verify_record_layout(
    request: FakeRealtimeCompileRequest,
    issues: list[TargetCompilationIssue],
) -> None:
    produced = {
        result_id
        for instruction in request.program.instructions
        for result_id in _record_ids(instruction)
    }
    declared = {layout.slot_id.local_id for layout in request.result_layouts}
    missing = sorted(produced - declared)
    if missing:
        _issue(
            request,
            issues,
            "fake_realtime_result_layout_missing",
            "record producers have no result layout: "
            + ", ".join(repr(item) for item in missing),
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
    unproduced = sorted(declared - produced)
    if unproduced:
        _issue(
            request,
            issues,
            "fake_realtime_result_layout_unproduced",
            "result layouts have no record producer: "
            + ", ".join(repr(item) for item in unproduced),
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )


def _verify_termination(
    request: FakeRealtimeCompileRequest,
    target: FakeRealtimeTarget,
    successors: tuple[tuple[int, ...], ...],
    issues: list[TargetCompilationIssue],
) -> None:
    instructions = request.program.instructions
    reachable = _reachable(successors)
    halts = {
        index
        for index, instruction in enumerate(instructions)
        if isinstance(instruction, RtHalt)
    }
    can_halt = _reverse_reachable(successors, halts)
    if reachable - can_halt:
        _issue(
            request,
            issues,
            "fake_realtime_nonterminating_control_flow",
            "every reachable machine instruction must have a path to Halt",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )

    label_indices = {
        instruction.name: index
        for index, instruction in enumerate(instructions)
        if isinstance(instruction, RtLabel)
    }
    loop_counters: set[FakeRealtimeRegister] = set()
    for index, instruction in enumerate(instructions):
        if not isinstance(instruction, RtJump | RtJumpIf | RtDecrementAndJump):
            continue
        if label_indices[instruction.target] >= index:
            continue
        if not isinstance(instruction, RtDecrementAndJump):
            _issue(
                request,
                issues,
                "fake_realtime_unbounded_back_edge",
                "backward control flow requires DecrementAndJump",
                dimension=TargetCompilationIssueDimension.PROGRAM,
            )
        else:
            loop_counters.add(instruction.counter)
    initializers = {
        instruction.destination: instruction.source
        for instruction in instructions
        if isinstance(instruction, RtMove) and isinstance(instruction.source, int)
    }
    if any(
        counter not in initializers
        or initializers[counter] <= 0
        or initializers[counter] > target.max_loop_iterations
        for counter in loop_counters
    ):
        _issue(
            request,
            issues,
            "fake_realtime_loop_limit_exceeded",
            "loop counters require a positive bounded constant initializer",
        )


def _verify_register_flow(
    request: FakeRealtimeCompileRequest,
    target: FakeRealtimeTarget,
    successors: tuple[tuple[int, ...], ...],
    issues: list[TargetCompilationIssue],
) -> None:
    instructions = request.program.instructions
    reachable = _reachable(successors)
    registers = _registers(instructions)
    top = dict.fromkeys(registers, 0)
    predecessors = _predecessors(successors)
    incoming = [dict(top) for _instruction in instructions]
    outgoing = [dict(top) for _instruction in instructions]
    incoming[0] = {}

    changed = True
    while changed:
        changed = False
        for index in sorted(reachable):
            if index:
                states = [
                    outgoing[item] for item in predecessors[index] if item in reachable
                ]
                selected = _meet_states(states) if states else {}
                if selected != incoming[index]:
                    incoming[index] = selected
                    changed = True
            selected_out = _transfer(incoming[index], instructions[index], target)
            if selected_out != outgoing[index]:
                outgoing[index] = selected_out
                changed = True

    for index in sorted(reachable):
        instruction = instructions[index]
        state = incoming[index]
        read_advance = (
            0
            if isinstance(
                instruction,
                RtLabel | RtHalt | RtPulseTimeline | RtWait,
            )
            else target.classical_instruction_ticks
        )
        for register in _read_registers(instruction):
            if register not in state:
                _issue(
                    request,
                    issues,
                    "fake_realtime_register_uninitialized",
                    (
                        f"instruction {index} reads uninitialized register "
                        f"{register.value!r}"
                    ),
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )
            elif state[register] > read_advance:
                _issue(
                    request,
                    issues,
                    "fake_realtime_feedback_read_too_early",
                    (
                        f"instruction {index} reads register {register.value!r} "
                        f"{state[register] - read_advance} ticks before it is ready"
                    ),
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )


def _transfer(
    state: dict[FakeRealtimeRegister, int],
    instruction: FakeRealtimeInstruction,
    target: FakeRealtimeTarget,
) -> dict[FakeRealtimeRegister, int]:
    elapsed = _instruction_ticks(instruction, target)
    selected = {
        register: max(0, remaining - elapsed) for register, remaining in state.items()
    }
    if isinstance(instruction, RtPulseTimeline):
        for acquisition in instruction.acquisitions:
            residual = instruction.duration_ticks - (
                acquisition.start_ticks + acquisition.duration_ticks
            )
            selected[acquisition.destination] = max(
                0,
                target.discrimination_latency_ticks - residual,
            )
    elif isinstance(instruction, RtMove | RtXor):
        selected[instruction.destination] = 0
    elif isinstance(instruction, RtDecrementAndJump):
        selected[instruction.counter] = 0
    return selected


def _meet_states(
    states: list[dict[FakeRealtimeRegister, int]],
) -> dict[FakeRealtimeRegister, int]:
    if not states:
        return {}
    common = set(states[0]).intersection(*(set(state) for state in states[1:]))
    return {register: max(state[register] for state in states) for register in common}


def _successors(
    instructions: tuple[FakeRealtimeInstruction, ...],
    labels: dict[str, int],
) -> tuple[tuple[int, ...], ...]:
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


def _reachable(successors: tuple[tuple[int, ...], ...]) -> set[int]:
    selected: set[int] = set()
    pending = [0]
    while pending:
        index = pending.pop()
        if index in selected:
            continue
        selected.add(index)
        pending.extend(successors[index])
    return selected


def _reverse_reachable(
    successors: tuple[tuple[int, ...], ...],
    roots: set[int],
) -> set[int]:
    predecessors = _predecessors(successors)
    selected: set[int] = set()
    pending = list(roots)
    while pending:
        index = pending.pop()
        if index in selected:
            continue
        selected.add(index)
        pending.extend(predecessors[index])
    return selected


def _predecessors(
    successors: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    selected: list[list[int]] = [[] for _item in successors]
    for index, targets in enumerate(successors):
        for target in targets:
            selected[target].append(index)
    return tuple(tuple(items) for items in selected)


def _instruction_ticks(
    instruction: FakeRealtimeInstruction,
    target: FakeRealtimeTarget,
) -> int:
    if isinstance(instruction, RtWait | RtPulseTimeline):
        return instruction.duration_ticks
    if isinstance(instruction, RtLabel | RtHalt):
        return 0
    return target.classical_instruction_ticks


def _record_ids(instruction: FakeRealtimeInstruction) -> tuple[str, ...]:
    if isinstance(instruction, RtPulseTimeline):
        return tuple(item.result_id for item in instruction.acquisitions if item.record)
    if isinstance(instruction, RtEmit):
        return (instruction.result_id,)
    return ()


def _read_registers(
    instruction: FakeRealtimeInstruction,
) -> tuple[FakeRealtimeRegister, ...]:
    if isinstance(instruction, RtMove):
        return (
            (instruction.source,)
            if isinstance(instruction.source, FakeRealtimeRegister)
            else ()
        )
    if isinstance(instruction, RtXor):
        return (instruction.left, instruction.right)
    if isinstance(instruction, RtJumpIf):
        return (instruction.source,)
    if isinstance(instruction, RtDecrementAndJump):
        return (instruction.counter,)
    if isinstance(instruction, RtEmit):
        return (instruction.source,)
    return ()


def _registers(
    instructions: tuple[FakeRealtimeInstruction, ...],
) -> set[FakeRealtimeRegister]:
    selected: set[FakeRealtimeRegister] = set()
    for instruction in instructions:
        selected.update(_read_registers(instruction))
        if isinstance(instruction, RtMove | RtXor):
            selected.add(instruction.destination)
        elif isinstance(instruction, RtPulseTimeline):
            selected.update(item.destination for item in instruction.acquisitions)
    return selected


def _issue(
    request: FakeRealtimeCompileRequest,
    issues: list[TargetCompilationIssue],
    code: str,
    message: str,
    *,
    dimension: TargetCompilationIssueDimension = (
        TargetCompilationIssueDimension.CAPABILITY
    ),
) -> None:
    issues.append(
        TargetCompilationIssue(
            dimension=dimension,
            code=code,
            message=message,
            entry_id=request.entry_id,
        )
    )


__all__ = ["VerifiedFakeRealtimeRequest", "verify_fake_realtime_request"]
