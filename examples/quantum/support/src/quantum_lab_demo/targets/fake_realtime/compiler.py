"""Validation and packaging for the structured fake realtime target."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat_quantum._ids import (
    PulseProgramId,
    RealtimeValueId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.programs import (
    RealtimeBitOutput,
    StructuredPulseBlock,
    StructuredPulseNode,
    StructuredPulseParallel,
    StructuredPulseRepeat,
    StructuredPulseSequence,
    StructuredQuantumPulseProgram,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquisitionSlot,
    Delay,
    Play,
    PulseInstruction,
    PulseProgram,
    PulseValidationError,
    iter_pulse_leaves,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.pulses import Sequence as PulseSequence
from scopecat_quantum.targets import (
    TargetAcquisitionLayout,
    TargetCompilationError,
    TargetCompilationIssue,
    TargetCompilationIssueDimension,
)

from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeArtifact,
    FakeRealtimeCompileRequest,
    FakeRealtimeInputId,
    FakeRealtimeOutputId,
    FakeRealtimeTarget,
)

type _NodePath = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FakeRealtimeCompiler:
    """Validate and retain one already-bound structured pulse program."""

    id: TargetCompilerId
    target: FakeRealtimeTarget

    @property
    def target_id(self) -> TargetId:
        return self.target.id

    @property
    def capability_fingerprint(self) -> str:
        return self.target.capability_fingerprint

    def request(
        self,
        entry_id: TargetCompileEntryId,
        program: StructuredQuantumPulseProgram,
        *,
        result_layouts: tuple[TargetAcquisitionLayout, ...],
        repetitions: int,
    ) -> FakeRealtimeCompileRequest:
        return FakeRealtimeCompileRequest(
            target_id=self.target_id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            entry_id=entry_id,
            program=program,
            result_layouts=result_layouts,
            repetitions=repetitions,
        )

    def compile(self, request: FakeRealtimeCompileRequest) -> FakeRealtimeArtifact:
        validator = _StructuredProgramValidator(
            target=self.target,
            compiler_id=self.id,
            entry_id=request.entry_id,
        )
        validator.validate(request)
        if validator.issues:
            raise TargetCompilationError(tuple(validator.issues))

        fingerprint = stable_content_hash(
            content_fingerprint(
                (
                    "quantum_lab_demo.fake_realtime.artifact.v2",
                    self.target_id,
                    self.id,
                    self.capability_fingerprint,
                    request.source_entry_ids,
                    request.repetitions,
                    request.program,
                    request.result_layouts,
                )
            )
        )
        return FakeRealtimeArtifact(
            id=TargetArtifactId(f"fake-realtime-artifact-{fingerprint}"),
            target_id=self.target_id,
            compiler_id=self.id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_fingerprint=fingerprint,
            source_entry_ids=request.source_entry_ids,
            repetitions=request.repetitions,
            program=request.program,
            result_layouts=request.result_layouts,
        )


@dataclass(slots=True)
class _StructuredProgramValidator:
    target: FakeRealtimeTarget
    compiler_id: TargetCompilerId
    entry_id: TargetCompileEntryId
    issues: list[TargetCompilationIssue] = field(default_factory=list)
    value_sources: dict[RealtimeValueId, FakeRealtimeInputId] = field(
        default_factory=dict
    )

    def validate(self, request: FakeRealtimeCompileRequest) -> None:
        if request.target_id != self.target.id:
            self._issue(
                "fake_realtime_target_mismatch",
                "compile request belongs to another target",
            )
        if request.compiler_id != self.compiler_id:
            self._issue(
                "fake_realtime_compiler_mismatch",
                "compile request belongs to another target compiler",
            )
        if request.capability_fingerprint != self.target.capability_fingerprint:
            self._issue(
                "fake_realtime_capability_mismatch",
                "compile request uses a stale target capability fingerprint",
            )

        self._visit(request.program.body, ("body",))
        counts = self._record_counts(request.program.body, ("body",))
        expected = {
            layout.slot_id.local_id: len(layout.acquisition_addresses)
            for layout in request.result_layouts
        }
        for result_id in sorted(set(counts) | set(expected)):
            if counts.get(result_id, 0) != expected.get(result_id, 0):
                self._issue(
                    "fake_realtime_result_layout_mismatch",
                    (
                        f"result {result_id!r} produces {counts.get(result_id, 0)} "
                        f"records per shot but its layout declares "
                        f"{expected.get(result_id, 0)}"
                    ),
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )
        record_count = sum(counts.values()) * request.repetitions
        if record_count > self.target.max_result_records:
            self._issue(
                "fake_realtime_result_memory_exceeded",
                (
                    f"program produces {record_count} records; target limit is "
                    f"{self.target.max_result_records}"
                ),
            )

    def _visit(self, node: StructuredPulseNode, path: _NodePath) -> None:
        if isinstance(node, StructuredPulseBlock | StructuredPulseParallel):
            self._validate_pulse_region(node, path)
            return
        if isinstance(node, StructuredPulseSequence):
            for index, operation in enumerate(node.operations):
                self._visit(operation, (*path, f"sequence[{index}]"))
            return
        if isinstance(node, StructuredPulseRepeat):
            if node.count > self.target.max_loop_iterations:
                self._issue(
                    "fake_realtime_loop_limit_exceeded",
                    (
                        f"repeat count {node.count} exceeds target limit "
                        f"{self.target.max_loop_iterations}"
                    ),
                )
            if node.count:
                self._visit(node.operation, (*path, "repeat-body"))
            return

        source = self.value_sources.get(node.condition.value_id)
        destinations = tuple(
            sorted(
                {
                    *controlled_outputs(node.when_true, self.target),
                    *controlled_outputs(node.when_false, self.target),
                },
                key=lambda item: item.value,
            )
        )
        if source is None:
            self._issue(
                "fake_realtime_condition_value_unavailable",
                (
                    f"condition value {node.condition.value_id.value!r} has no "
                    "target acquisition source"
                ),
                dimension=TargetCompilationIssueDimension.PROGRAM,
            )
        else:
            for destination in destinations:
                if self.target.feedback_latency(source, destination) is None:
                    self._issue(
                        "fake_realtime_feedback_route_missing",
                        (
                            f"no feedback route connects input {source.value!r} to "
                            f"controlled output {destination.value!r}"
                        ),
                    )
        self._visit(node.when_true, (*path, "when-true"))
        self._visit(node.when_false, (*path, "when-false"))

    def _validate_pulse_region(
        self,
        node: StructuredPulseBlock | StructuredPulseParallel,
        path: _NodePath,
    ) -> None:
        try:
            program, outputs = pulse_region(node)
            scheduled = schedule(program)
        except _ControlFlowInPulseRegion:
            self._issue(
                "fake_realtime_parallel_control_flow_unsupported",
                "parallel realtime branches may contain only pulse regions",
                dimension=TargetCompilationIssueDimension.PROGRAM,
            )
            return
        except PulseValidationError as error:
            for pulse_issue in error.issues:
                self._issue(
                    "fake_realtime_pulse_region_invalid",
                    pulse_issue.message,
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )
            return

        self._ticks(scheduled.duration_seconds, f"pulse region {'/'.join(path)}")
        for event in scheduled.events:
            instruction = event.instruction
            self._ticks(
                event.start_seconds,
                f"event {instruction.id.value!r} start",
            )
            self._ticks(
                event.duration_seconds,
                f"event {instruction.id.value!r} duration",
            )
            if isinstance(instruction, Play):
                if self.target.output_for(instruction.signal) is None:
                    self._issue(
                        "fake_realtime_output_signal_unbound",
                        (
                            f"play signal {instruction.signal!r} is not bound "
                            "by the target"
                        ),
                    )
            elif isinstance(instruction, Acquire):
                if self.target.input_for(instruction.signal) is None:
                    self._issue(
                        "fake_realtime_input_signal_unbound",
                        (
                            f"acquisition signal {instruction.signal!r} is not "
                            "bound by the target"
                        ),
                    )
            elif not isinstance(instruction, Delay):
                self._issue(
                    "fake_realtime_pulse_instruction_unsupported",
                    f"{type(instruction).__name__} is not supported by this target",
                )

        slots = {slot.id: slot for slot in program.acquisition_slots}
        for output in outputs:
            if output.discriminator.id not in self.target.discriminator_ids:
                self._issue(
                    "fake_realtime_discriminator_unsupported",
                    (
                        f"discriminator {output.discriminator.id!r} is not supported "
                        "by the target"
                    ),
                )
            slot = slots.get(output.acquisition_slot_id)
            if slot is None:
                self._issue(
                    "fake_realtime_discriminator_slot_missing",
                    "realtime discriminator output has no acquisition slot",
                    dimension=TargetCompilationIssueDimension.PROGRAM,
                )
                continue
            source = self.target.input_for(slot.signal)
            if source is not None:
                self.value_sources[output.value_id] = source

    def _record_counts(
        self,
        node: StructuredPulseNode,
        path: _NodePath,
    ) -> Counter[str]:
        if isinstance(node, StructuredPulseBlock | StructuredPulseParallel):
            try:
                program, _outputs = pulse_region(node)
            except _ControlFlowInPulseRegion:
                return Counter()
            return Counter(slot.id.local_id for slot in program.acquisition_slots)
        if isinstance(node, StructuredPulseSequence):
            total: Counter[str] = Counter()
            for index, operation in enumerate(node.operations):
                total.update(
                    self._record_counts(operation, (*path, f"sequence[{index}]"))
                )
            return total
        if isinstance(node, StructuredPulseRepeat):
            return Counter(
                {
                    result_id: count * node.count
                    for result_id, count in self._record_counts(
                        node.operation,
                        (*path, "repeat-body"),
                    ).items()
                }
            )
        when_true = self._record_counts(node.when_true, (*path, "when-true"))
        when_false = self._record_counts(node.when_false, (*path, "when-false"))
        if when_true != when_false:
            self._issue(
                "fake_realtime_conditional_result_shape_mismatch",
                "realtime conditional branches must produce the same result shape",
                dimension=TargetCompilationIssueDimension.PROGRAM,
            )
        return Counter(
            {
                result_id: max(when_true[result_id], when_false[result_id])
                for result_id in set(when_true) | set(when_false)
            }
        )

    def _ticks(self, seconds: Decimal, field_name: str) -> int | None:
        value = seconds * Decimal(self.target.clock_hz)
        if value == value.to_integral_value():
            return int(value)
        self._issue(
            "fake_realtime_timing_not_on_clock",
            f"{field_name} {seconds} s is not aligned to the target clock",
            dimension=TargetCompilationIssueDimension.PROGRAM,
        )
        return None

    def _issue(
        self,
        code: str,
        message: str,
        *,
        dimension: TargetCompilationIssueDimension = (
            TargetCompilationIssueDimension.CAPABILITY
        ),
    ) -> None:
        self.issues.append(
            TargetCompilationIssue(
                dimension=dimension,
                code=code,
                message=message,
                entry_id=self.entry_id,
            )
        )


class _ControlFlowInPulseRegion(Exception):
    pass


def pulse_region(
    node: StructuredPulseBlock | StructuredPulseParallel,
) -> tuple[PulseProgram, tuple[RealtimeBitOutput, ...]]:
    """Collapse one control-free structured region to canonical pulse IR."""

    body, slots, outputs = _pulse_region_parts(node)
    return (
        PulseProgram(
            id=PulseProgramId("fake-realtime.pulse-region"),
            body=body,
            acquisition_slots=slots,
        ),
        outputs,
    )


def _pulse_region_parts(
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
        selected = tuple(_pulse_region_parts(child) for child in children)
        instruction_type = (
            PulseSequence
            if isinstance(node, StructuredPulseSequence)
            else PulseParallel
        )
        return (
            instruction_type(tuple(body for body, _slots, _outputs in selected)),
            tuple(slot for _body, slots, _outputs in selected for slot in slots),
            tuple(output for _body, _slots, outputs in selected for output in outputs),
        )
    raise _ControlFlowInPulseRegion


def controlled_outputs(
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
    if isinstance(node, StructuredPulseSequence):
        children = node.operations
    elif isinstance(node, StructuredPulseParallel):
        children = node.branches
    elif isinstance(node, StructuredPulseRepeat):
        return set() if not node.count else controlled_outputs(node.operation, target)
    else:
        children = (node.when_true, node.when_false)
    return {
        output for child in children for output in controlled_outputs(child, target)
    }


__all__ = ["FakeRealtimeCompiler"]
