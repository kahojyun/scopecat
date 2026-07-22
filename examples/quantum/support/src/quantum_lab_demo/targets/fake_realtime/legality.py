"""Target legality for structured pulse programs before machine lowering."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from scopecat_quantum import (
    Acquire,
    AcquisitionSlot,
    Delay,
    Play,
    PulseInstruction,
    PulseProgram,
    PulseProgramId,
    PulseValidationError,
    RealtimeBitOutput,
    RealtimeBitStateInit,
    RealtimeBitStateRead,
    RealtimeBitStateWrite,
    RealtimeBitXor,
    RealtimeResultEmit,
    RealtimeValueId,
    ScheduledPulseProgram,
    StructuredPulseBlock,
    StructuredPulseNode,
    StructuredPulseParallel,
    StructuredPulseRepeat,
    StructuredPulseSequence,
    StructuredQuantumPulseProgram,
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
    TargetCompileEntryId,
    iter_pulse_leaves,
    schedule,
)
from scopecat_quantum import PulseParallel as IrPulseParallel
from scopecat_quantum import PulseSequence as IrPulseSequence

from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeInputId,
    FakeRealtimeOutputId,
    FakeRealtimeTarget,
)

type _NodePath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FakeRealtimePulseRegion:
    """One target-legal scheduled physical region at a structural path."""

    path: _NodePath
    program: ScheduledPulseProgram
    realtime_bit_outputs: tuple[RealtimeBitOutput, ...]


@dataclass(frozen=True, slots=True)
class FakeRealtimeFeedbackDependency:
    """One condition's exact capture-to-controlled-output timing dependency."""

    path: _NodePath
    value_id: RealtimeValueId
    source: FakeRealtimeInputId
    destinations: tuple[FakeRealtimeOutputId, ...]
    latency_ticks: int


@dataclass(frozen=True, slots=True)
class LegalizedFakeRealtimeProgram:
    """Structured source plus target-proven physical and feedback facts."""

    source: StructuredQuantumPulseProgram
    pulse_regions: tuple[FakeRealtimePulseRegion, ...]
    feedback_dependencies: tuple[FakeRealtimeFeedbackDependency, ...]
    feedback_value_latencies: tuple[tuple[RealtimeValueId, int], ...]

    def pulse_region(self, path: _NodePath) -> FakeRealtimePulseRegion:
        for region in self.pulse_regions:
            if region.path == path:
                return region
        raise KeyError(path)

    def feedback_dependency(
        self,
        path: _NodePath,
    ) -> FakeRealtimeFeedbackDependency:
        for dependency in self.feedback_dependencies:
            if dependency.path == path:
                return dependency
        raise KeyError(path)

    def feedback_value_latency(self, value_id: RealtimeValueId) -> int:
        for selected_id, latency in self.feedback_value_latencies:
            if selected_id == value_id:
                return latency
        return 0


def legalize_fake_realtime_program(
    program: StructuredQuantumPulseProgram,
    *,
    target: FakeRealtimeTarget,
    entry_id: TargetCompileEntryId,
) -> LegalizedFakeRealtimeProgram:
    """Prove target instruction, binding, discriminator, route, and tick legality."""

    issues: list[TargetCompilationIssue] = []
    regions: list[FakeRealtimePulseRegion] = []
    value_sources: dict[RealtimeValueId, FakeRealtimeInputId] = {}

    def add_region(
        path: _NodePath,
        pulse_program: PulseProgram,
        outputs: tuple[RealtimeBitOutput, ...],
    ) -> None:
        try:
            scheduled = schedule(pulse_program)
        except PulseValidationError as error:
            for pulse_issue in error.issues:
                _issue(
                    issues,
                    entry_id,
                    "fake_realtime_pulse_region_invalid",
                    pulse_issue.message,
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )
            return
        _ticks(
            scheduled.duration_seconds,
            target=target,
            field_name=f"pulse region {'/'.join(path)} duration",
            entry_id=entry_id,
            issues=issues,
        )
        for event in scheduled.events:
            instruction = event.instruction
            _ticks(
                event.start_seconds,
                target=target,
                field_name=f"event {instruction.id.value!r} start",
                entry_id=entry_id,
                issues=issues,
            )
            _ticks(
                event.duration_seconds,
                target=target,
                field_name=f"event {instruction.id.value!r} duration",
                entry_id=entry_id,
                issues=issues,
            )
            if isinstance(instruction, Play):
                if target.output_for(instruction.signal) is None:
                    _issue(
                        issues,
                        entry_id,
                        "fake_realtime_output_signal_unbound",
                        (
                            f"play signal {instruction.signal!r} is not bound "
                            "by the target"
                        ),
                    )
            elif isinstance(instruction, Acquire):
                if target.input_for(instruction.signal) is None:
                    _issue(
                        issues,
                        entry_id,
                        "fake_realtime_input_signal_unbound",
                        (
                            f"acquisition signal {instruction.signal!r} is not "
                            "bound by the target"
                        ),
                    )
            elif not isinstance(instruction, Delay):
                _issue(
                    issues,
                    entry_id,
                    "fake_realtime_pulse_instruction_unsupported",
                    f"{type(instruction).__name__} is not supported by this target",
                )

        slots = {slot.id: slot for slot in pulse_program.acquisition_slots}
        for output in outputs:
            if output.discriminator.id not in target.discriminator_ids:
                _issue(
                    issues,
                    entry_id,
                    "fake_realtime_discriminator_unsupported",
                    (
                        f"discriminator {output.discriminator.id!r} is not supported "
                        "by the target"
                    ),
                )
            source = target.input_for(slots[output.acquisition_slot_id].signal)
            if source is not None:
                value_sources[output.value_id] = source
        regions.append(FakeRealtimePulseRegion(path, scheduled, outputs))

    def collect_regions(node: StructuredPulseNode, path: _NodePath) -> None:
        if isinstance(node, StructuredPulseBlock):
            add_region(path, node.program, node.realtime_bit_outputs)
            return
        if isinstance(node, StructuredPulseParallel):
            try:
                body, slots, outputs = _pulse_region(node)
            except _ControlFlowInPulseRegion:
                _issue(
                    issues,
                    entry_id,
                    "fake_realtime_parallel_control_flow_unsupported",
                    "parallel realtime branches may contain only pulse regions",
                )
                return
            add_region(
                path,
                PulseProgram(
                    id=PulseProgramId("fake-realtime.parallel-region"),
                    body=body,
                    acquisition_slots=slots,
                ),
                outputs,
            )
            return
        if isinstance(
            node,
            RealtimeBitStateInit
            | RealtimeBitStateRead
            | RealtimeBitStateWrite
            | RealtimeBitXor
            | RealtimeResultEmit,
        ):
            return
        if isinstance(node, StructuredPulseSequence):
            for index, operation in enumerate(node.operations):
                collect_regions(operation, (*path, f"sequence[{index}]"))
            return
        if isinstance(node, StructuredPulseRepeat):
            if node.count:
                collect_regions(node.operation, (*path, "repeat-body"))
            return
        collect_regions(node.when_true, (*path, "when-true"))
        collect_regions(node.when_false, (*path, "when-false"))

    collect_regions(program.body, ("body",))

    dependencies = _feedback_dependencies(
        program.body,
        target=target,
        entry_id=entry_id,
        value_sources=value_sources,
        issues=issues,
    )
    if issues:
        raise TargetCompilationError(tuple(issues))
    return LegalizedFakeRealtimeProgram(
        source=program,
        pulse_regions=tuple(regions),
        feedback_dependencies=tuple(dependencies),
        feedback_value_latencies=tuple(
            (value_id, target.discrimination_latency_ticks)
            for value_id in value_sources
        ),
    )


def _feedback_dependencies(
    body: StructuredPulseNode,
    *,
    target: FakeRealtimeTarget,
    entry_id: TargetCompileEntryId,
    value_sources: dict[RealtimeValueId, FakeRealtimeInputId],
    issues: list[TargetCompilationIssue],
) -> list[FakeRealtimeFeedbackDependency]:
    dependencies: list[FakeRealtimeFeedbackDependency] = []

    def collect(node: StructuredPulseNode, path: _NodePath) -> None:
        if isinstance(
            node,
            StructuredPulseBlock
            | StructuredPulseParallel
            | RealtimeBitStateInit
            | RealtimeBitStateRead
            | RealtimeBitStateWrite
            | RealtimeBitXor
            | RealtimeResultEmit,
        ):
            return
        if isinstance(node, StructuredPulseSequence):
            for index, operation in enumerate(node.operations):
                collect(operation, (*path, f"sequence[{index}]"))
            return
        if isinstance(node, StructuredPulseRepeat):
            if node.count:
                collect(node.operation, (*path, "repeat-body"))
            return

        source = value_sources.get(node.condition.value_id)
        destinations = tuple(
            sorted(
                {
                    *_controlled_outputs(node.when_true, target),
                    *_controlled_outputs(node.when_false, target),
                },
                key=lambda item: item.value,
            )
        )
        if source is None:
            _issue(
                issues,
                entry_id,
                "fake_realtime_condition_value_unavailable",
                (
                    f"condition value {node.condition.value_id.value!r} has no "
                    "target acquisition source"
                ),
                dimension=TargetCompilationIssueDimension.PROGRAM,
            )
        else:
            route_latencies = _feedback_route_latencies(
                source,
                destinations,
                target=target,
                entry_id=entry_id,
                issues=issues,
            )
            if len(route_latencies) == len(destinations):
                dependencies.append(
                    FakeRealtimeFeedbackDependency(
                        path=path,
                        value_id=node.condition.value_id,
                        source=source,
                        destinations=destinations,
                        latency_ticks=max(
                            target.discrimination_latency_ticks,
                            *route_latencies,
                        ),
                    )
                )
        collect(node.when_true, (*path, "when-true"))
        collect(node.when_false, (*path, "when-false"))

    collect(body, ("body",))
    return dependencies


def _feedback_route_latencies(
    source: FakeRealtimeInputId,
    destinations: tuple[FakeRealtimeOutputId, ...],
    *,
    target: FakeRealtimeTarget,
    entry_id: TargetCompileEntryId,
    issues: list[TargetCompilationIssue],
) -> list[int]:
    selected: list[int] = []
    for destination in destinations:
        latency = target.feedback_latency(source, destination)
        if latency is None:
            _issue(
                issues,
                entry_id,
                "fake_realtime_feedback_route_missing",
                (
                    f"no feedback route connects input {source.value!r} to "
                    f"controlled output {destination.value!r}"
                ),
            )
        else:
            selected.append(latency)
    return selected


class _ControlFlowInPulseRegion(Exception):
    pass


def _pulse_region(
    node: StructuredPulseNode,
) -> tuple[
    PulseInstruction,
    tuple[AcquisitionSlot, ...],
    tuple[RealtimeBitOutput, ...],
]:
    if isinstance(node, StructuredPulseBlock):
        return (
            node.program.body,
            node.program.acquisition_slots,
            node.realtime_bit_outputs,
        )
    if isinstance(node, StructuredPulseSequence | StructuredPulseParallel):
        children = (
            node.operations
            if isinstance(node, StructuredPulseSequence)
            else node.branches
        )
        selected = tuple(_pulse_region(item) for item in children)
        instruction_type = (
            IrPulseSequence
            if isinstance(node, StructuredPulseSequence)
            else IrPulseParallel
        )
        return (
            instruction_type(tuple(body for body, _slots, _outputs in selected)),
            tuple(slot for _body, slots, _outputs in selected for slot in slots),
            tuple(output for _body, _slots, outputs in selected for output in outputs),
        )
    raise _ControlFlowInPulseRegion


def _controlled_outputs(
    node: StructuredPulseNode,
    target: FakeRealtimeTarget,
) -> set[FakeRealtimeOutputId]:
    if isinstance(node, StructuredPulseBlock):
        return {
            output
            for instruction in iter_pulse_leaves(node.program.body)
            if isinstance(instruction, Play)
            if (output := target.output_for(instruction.signal)) is not None
        }
    if isinstance(
        node,
        RealtimeBitStateInit
        | RealtimeBitStateRead
        | RealtimeBitStateWrite
        | RealtimeBitXor
        | RealtimeResultEmit,
    ):
        return set()
    if isinstance(node, StructuredPulseSequence):
        children = node.operations
    elif isinstance(node, StructuredPulseParallel):
        children = node.branches
    elif isinstance(node, StructuredPulseRepeat):
        return set() if not node.count else _controlled_outputs(node.operation, target)
    else:
        children = (node.when_true, node.when_false)
    return {
        output for child in children for output in _controlled_outputs(child, target)
    }


def _ticks(
    seconds: Decimal,
    *,
    target: FakeRealtimeTarget,
    field_name: str,
    entry_id: TargetCompileEntryId,
    issues: list[TargetCompilationIssue],
) -> int | None:
    value = seconds * Decimal(target.clock_hz)
    if value != value.to_integral_value():
        _issue(
            issues,
            entry_id,
            "fake_realtime_timing_not_on_clock",
            f"{field_name} {seconds} s is not aligned to the target clock",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
        return None
    return int(value)


def _issue(
    issues: list[TargetCompilationIssue],
    entry_id: TargetCompileEntryId,
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
            entry_id=entry_id,
        )
    )


__all__ = [
    "FakeRealtimeFeedbackDependency",
    "FakeRealtimePulseRegion",
    "LegalizedFakeRealtimeProgram",
    "legalize_fake_realtime_program",
]
