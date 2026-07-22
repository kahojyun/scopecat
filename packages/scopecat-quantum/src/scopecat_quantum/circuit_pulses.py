"""Checked, hygienic lowering from logical circuits to pulse authoring IR.

Lowering maps circuit composition homomorphically and keeps circuit,
operation, implementation, template-event, and acquisition provenance in a
sidecar rather than coupling Pulse IR back to Circuit IR. Template-relative
event identities are structurally prefixed for each occurrence, while a
measurement template's local acquisition slot is replaced by the exact slot
declared by the circuit.

This proof deliberately stops before scheduling. Disjoint circuit qubits do
not prove that selected implementations avoid a shared logical signal, so time
normalization, acquisition closure, and overlap checks remain the independent
scheduler's responsibility.
"""

from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, replace
from enum import StrEnum

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
)
from scopecat_quantum.circuits import (
    CircuitIssuePathItem,
    CircuitNode,
    CircuitOperation,
    Measure,
    VerifiedCircuitProgram,
)
from scopecat_quantum.circuits import (
    Sequence as CircuitSequence,
)
from scopecat_quantum.gates import GateCall
from scopecat_quantum.measurement_implementations import (
    MeasurementPulseImplementationBinding,
    MeasurementPulseImplementationKey,
)
from scopecat_quantum.pulse_implementations import (
    GatePulseImplementationBinding,
    GatePulseImplementationKey,
    PulseImplementationBinding,
    PulseImplementationBindings,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquisitionSlot,
    PulseInstruction,
    PulseProgram,
)
from scopecat_quantum.pulses import (
    Parallel as PulseParallel,
)
from scopecat_quantum.pulses import (
    Sequence as PulseSequence,
)


class CircuitPulseLoweringIssueCode(StrEnum):
    """Stable kinds of circuit-to-pulse lowering failure."""

    BINDINGS_CIRCUIT_MISMATCH = "circuit_pulse_bindings_circuit_mismatch"
    BINDINGS_COVERAGE_MISMATCH = "circuit_pulse_bindings_coverage_mismatch"
    BINDING_KEY_MISMATCH = "circuit_pulse_binding_key_mismatch"
    TEMPLATE_STRUCTURE_INVALID = "circuit_pulse_template_structure_invalid"
    TEMPLATE_PROGRAM_ID_INVALID = "circuit_pulse_template_program_id_invalid"
    TEMPLATE_ACQUISITION_UNSUPPORTED = "circuit_pulse_template_acquisition_unsupported"
    TEMPLATE_EVENT_ID_INVALID = "circuit_pulse_template_event_id_invalid"
    TEMPLATE_EVENT_DUPLICATE = "circuit_pulse_template_event_duplicate"
    MEASUREMENT_TEMPLATE_INVALID = "circuit_pulse_measurement_template_invalid"


@dataclass(frozen=True, slots=True)
class CircuitPulseLoweringIssue:
    """One stable, machine-readable circuit-to-pulse lowering problem."""

    code: CircuitPulseLoweringIssueCode
    message: str
    path: tuple[CircuitIssuePathItem, ...] = ()
    operation_id: CircuitOperationId | None = None
    implementation_id: PulseImplementationId | None = None
    template_event_id: PulseEventId | None = None


class CircuitPulseLoweringError(ValueError):
    """Aggregate failure raised before any partial pulse program is returned."""

    __slots__ = ("issues",)

    def __init__(
        self,
        issues: SequenceCollection[CircuitPulseLoweringIssue],
    ) -> None:
        selected = tuple(issues)
        if not selected:
            msg = "circuit pulse lowering errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(sorted(set(selected), key=_issue_sort_key))
        summary = "; ".join(
            f"{issue.code.value}: {issue.message}" for issue in self.issues
        )
        super().__init__(summary)


@dataclass(frozen=True, slots=True)
class GatePulseInstantiation:
    """One resolved implementation instantiated for one gate call."""

    call_id: CircuitOperationId
    key: GatePulseImplementationKey
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    template_program_id: PulseProgramId
    event_ids: tuple[PulseEventId, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ids", tuple(self.event_ids))


@dataclass(frozen=True, slots=True)
class MeasurementPulseInstantiation:
    """One selected readout template instantiated for one measurement."""

    measurement_id: CircuitOperationId
    key: MeasurementPulseImplementationKey
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    template_program_id: PulseProgramId
    template_acquisition_slot_id: AcquisitionSlotId
    acquisition_slot_id: AcquisitionSlotId
    acquire_event_id: PulseEventId
    event_ids: tuple[PulseEventId, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ids", tuple(self.event_ids))


type CircuitPulseInstantiation = GatePulseInstantiation | MeasurementPulseInstantiation


@dataclass(frozen=True, slots=True)
class CircuitPulseEventProvenance:
    """Exact typed origin of one instantiated pulse event."""

    event_id: PulseEventId
    operation_id: CircuitOperationId
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    template_program_id: PulseProgramId
    template_event_id: PulseEventId
    template_path: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_path", tuple(self.template_path))


@dataclass(frozen=True, slots=True)
class CircuitPulseAcquisitionProvenance:
    """Exact template-to-circuit mapping for one acquisition result slot."""

    acquisition_slot_id: AcquisitionSlotId
    measurement_id: CircuitOperationId
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    template_program_id: PulseProgramId
    template_acquisition_slot_id: AcquisitionSlotId
    acquire_event_id: PulseEventId


@dataclass(frozen=True, slots=True)
class LoweredCircuitPulseProgram:
    """Hygienic logical-circuit pulse instantiation.

    The lowering factory owns binding congruence, structural composition,
    event hygiene, and provenance coverage. This value deliberately does not
    cover pulse timing or logical-signal non-overlap;
    :func:`scopecat_quantum.schedule` remains the independent refinement for
    those properties.
    """

    source_circuit_id: CircuitId
    program: PulseProgram
    instantiations: tuple[CircuitPulseInstantiation, ...]
    event_provenance: tuple[CircuitPulseEventProvenance, ...]
    acquisition_provenance: tuple[CircuitPulseAcquisitionProvenance, ...]

    def instantiation_for(
        self,
        operation_id: CircuitOperationId,
    ) -> CircuitPulseInstantiation:
        """Return the selected instantiation for one circuit operation."""

        for instantiation in self.instantiations:
            selected_id = (
                instantiation.call_id
                if isinstance(instantiation, GatePulseInstantiation)
                else instantiation.measurement_id
            )
            if selected_id == operation_id:
                return instantiation
        msg = f"operation {operation_id.value!r} has no pulse instantiation"
        raise KeyError(msg)

    def provenance_for(
        self,
        event_id: PulseEventId,
    ) -> CircuitPulseEventProvenance:
        """Return the typed origin of one instantiated event."""

        for provenance in self.event_provenance:
            if provenance.event_id == event_id:
                return provenance
        msg = f"pulse event {event_id.value!r} has no circuit provenance"
        raise KeyError(msg)

    def acquisition_provenance_for(
        self,
        acquisition_slot_id: AcquisitionSlotId,
    ) -> CircuitPulseAcquisitionProvenance:
        """Return the template origin of one circuit acquisition slot."""

        for provenance in self.acquisition_provenance:
            if provenance.acquisition_slot_id == acquisition_slot_id:
                return provenance
        msg = (
            f"acquisition slot {acquisition_slot_id.value!r} has no circuit provenance"
        )
        raise KeyError(msg)


def lower_circuit_to_pulses(
    program: VerifiedCircuitProgram,
    bindings: PulseImplementationBindings,
    *,
    output_id: PulseProgramId,
) -> LoweredCircuitPulseProgram:
    """Instantiate every resolved gate and measurement homomorphically."""

    issues: list[CircuitPulseLoweringIssue] = []
    source_circuit_id = program.program.id
    if bindings.circuit_id != source_circuit_id:
        issues.append(
            CircuitPulseLoweringIssue(
                code=CircuitPulseLoweringIssueCode.BINDINGS_CIRCUIT_MISMATCH,
                message=(
                    f"pulse implementation bindings belong to circuit "
                    f"{bindings.circuit_id.value!r}, not "
                    f"{source_circuit_id.value!r}"
                ),
                path=("bindings", "circuit_id"),
            )
        )

    expected_operation_ids = tuple(operation.id for operation in program.operations)
    if bindings.operation_ids != expected_operation_ids:
        issues.append(
            CircuitPulseLoweringIssue(
                code=CircuitPulseLoweringIssueCode.BINDINGS_COVERAGE_MISMATCH,
                message=(
                    "pulse implementation bindings do not cover every verified "
                    "circuit operation in order"
                ),
                path=("bindings", "operation_ids"),
            )
        )

    operation_paths = {
        operation.id: path
        for operation, path in _iter_circuit_operations_with_paths(
            program.program.body,
            ("body",),
        )
    }
    bindings_by_operation = {
        (
            binding.call_id
            if isinstance(binding, GatePulseImplementationBinding)
            else binding.measurement_id
        ): binding
        for binding in bindings.bindings
    }

    for operation in program.operations:
        binding = bindings_by_operation.get(operation.id)
        if binding is None:
            continue
        expected_key = (
            GatePulseImplementationKey.from_call(operation)
            if isinstance(operation, GateCall)
            else MeasurementPulseImplementationKey.from_measurement(operation)
        )
        binding_kind_matches = (
            isinstance(operation, GateCall)
            and isinstance(binding, GatePulseImplementationBinding)
        ) or (
            isinstance(operation, Measure)
            and isinstance(binding, MeasurementPulseImplementationBinding)
        )
        if not binding_kind_matches or binding.key != expected_key:
            issues.append(
                CircuitPulseLoweringIssue(
                    code=CircuitPulseLoweringIssueCode.BINDING_KEY_MISMATCH,
                    message=(
                        f"pulse implementation binding for operation "
                        f"{operation.id.value!r} "
                        "does not match its canonical typed key"
                    ),
                    path=operation_paths.get(operation.id, ("body",)),
                    operation_id=operation.id,
                    implementation_id=binding.implementation_id,
                )
            )

    if issues:
        raise CircuitPulseLoweringError(issues)

    instantiations: list[CircuitPulseInstantiation] = []
    provenance: list[CircuitPulseEventProvenance] = []
    acquisition_slots: list[AcquisitionSlot] = []
    acquisition_provenance: list[CircuitPulseAcquisitionProvenance] = []
    lowered_body = _lower_circuit_node(
        program.program.body,
        source_circuit_id=source_circuit_id,
        bindings_by_operation=bindings_by_operation,
        instantiations=instantiations,
        provenance=provenance,
        acquisition_slots=acquisition_slots,
        acquisition_provenance=acquisition_provenance,
    )
    pulse_program = PulseProgram(
        id=output_id,
        body=lowered_body,
        acquisition_slots=tuple(acquisition_slots),
    )
    return LoweredCircuitPulseProgram(
        source_circuit_id=source_circuit_id,
        program=pulse_program,
        instantiations=tuple(instantiations),
        event_provenance=tuple(provenance),
        acquisition_provenance=tuple(acquisition_provenance),
    )


def _iter_circuit_operations_with_paths(
    node: CircuitNode,
    path: tuple[CircuitIssuePathItem, ...],
) -> Iterator[tuple[CircuitOperation, tuple[CircuitIssuePathItem, ...]]]:
    if isinstance(node, GateCall | Measure):
        yield node, path
        return
    if isinstance(node, CircuitSequence):
        for index, operation in enumerate(node.operations):
            yield from _iter_circuit_operations_with_paths(
                operation,
                (*path, "operations", index),
            )
        return
    for index, branch in enumerate(node.branches):
        yield from _iter_circuit_operations_with_paths(
            branch,
            (*path, "branches", index),
        )


def _lower_circuit_node(
    node: CircuitNode,
    *,
    source_circuit_id: CircuitId,
    bindings_by_operation: dict[CircuitOperationId, PulseImplementationBinding],
    instantiations: list[CircuitPulseInstantiation],
    provenance: list[CircuitPulseEventProvenance],
    acquisition_slots: list[AcquisitionSlot],
    acquisition_provenance: list[CircuitPulseAcquisitionProvenance],
) -> PulseInstruction:
    if isinstance(node, GateCall):
        binding = bindings_by_operation[node.id]
        assert isinstance(binding, GatePulseImplementationBinding)  # noqa: S101
        prefix = (
            "circuits",
            source_circuit_id.value,
            "operations",
            node.id.value,
        )
        event_ids: list[PulseEventId] = []
        acquire_event_ids: list[PulseEventId] = []
        lowered = _instantiate_template_instruction(
            binding.pulse_template.body,
            prefix=prefix,
            template_path=(),
            operation_id=node.id,
            implementation_id=binding.implementation_id,
            implementation_fingerprint=binding.implementation_fingerprint,
            template_program_id=binding.pulse_template.id,
            slot_substitution=None,
            event_ids=event_ids,
            acquire_event_ids=acquire_event_ids,
            provenance=provenance,
        )
        assert not acquire_event_ids  # noqa: S101
        instantiations.append(
            GatePulseInstantiation(
                call_id=node.id,
                key=binding.key,
                implementation_id=binding.implementation_id,
                implementation_fingerprint=binding.implementation_fingerprint,
                template_program_id=binding.pulse_template.id,
                event_ids=tuple(event_ids),
            )
        )
        return lowered
    if isinstance(node, Measure):
        binding = bindings_by_operation[node.id]
        assert isinstance(binding, MeasurementPulseImplementationBinding)  # noqa: S101
        template_slot = binding.pulse_template.acquisition_slots[0]
        output_slot = replace(template_slot, id=node.acquisition_slot_id)
        prefix = (
            "circuits",
            source_circuit_id.value,
            "operations",
            node.id.value,
        )
        event_ids = []
        acquire_event_ids = []
        lowered = _instantiate_template_instruction(
            binding.pulse_template.body,
            prefix=prefix,
            template_path=(),
            operation_id=node.id,
            implementation_id=binding.implementation_id,
            implementation_fingerprint=binding.implementation_fingerprint,
            template_program_id=binding.pulse_template.id,
            slot_substitution=(template_slot.id, node.acquisition_slot_id),
            event_ids=event_ids,
            acquire_event_ids=acquire_event_ids,
            provenance=provenance,
        )
        if len(acquire_event_ids) != 1:
            msg = "validated measurement templates must contain exactly one Acquire"
            raise AssertionError(msg)
        acquire_event_id = acquire_event_ids[0]
        instantiations.append(
            MeasurementPulseInstantiation(
                measurement_id=node.id,
                key=binding.key,
                implementation_id=binding.implementation_id,
                implementation_fingerprint=binding.implementation_fingerprint,
                template_program_id=binding.pulse_template.id,
                template_acquisition_slot_id=template_slot.id,
                acquisition_slot_id=node.acquisition_slot_id,
                acquire_event_id=acquire_event_id,
                event_ids=tuple(event_ids),
            )
        )
        acquisition_slots.append(output_slot)
        acquisition_provenance.append(
            CircuitPulseAcquisitionProvenance(
                acquisition_slot_id=node.acquisition_slot_id,
                measurement_id=node.id,
                implementation_id=binding.implementation_id,
                implementation_fingerprint=binding.implementation_fingerprint,
                template_program_id=binding.pulse_template.id,
                template_acquisition_slot_id=template_slot.id,
                acquire_event_id=acquire_event_id,
            )
        )
        return lowered
    if isinstance(node, CircuitSequence):
        return PulseSequence(
            tuple(
                _lower_circuit_node(
                    operation,
                    source_circuit_id=source_circuit_id,
                    bindings_by_operation=bindings_by_operation,
                    instantiations=instantiations,
                    provenance=provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                )
                for operation in node.operations
            )
        )
    return PulseParallel(
        tuple(
            _lower_circuit_node(
                branch,
                source_circuit_id=source_circuit_id,
                bindings_by_operation=bindings_by_operation,
                instantiations=instantiations,
                provenance=provenance,
                acquisition_slots=acquisition_slots,
                acquisition_provenance=acquisition_provenance,
            )
            for branch in node.branches
        )
    )


def _instantiate_template_instruction(
    instruction: PulseInstruction,
    *,
    prefix: tuple[str, ...],
    template_path: tuple[int, ...],
    operation_id: CircuitOperationId,
    implementation_id: PulseImplementationId,
    implementation_fingerprint: str,
    template_program_id: PulseProgramId,
    slot_substitution: tuple[AcquisitionSlotId, AcquisitionSlotId] | None,
    event_ids: list[PulseEventId],
    acquire_event_ids: list[PulseEventId],
    provenance: list[CircuitPulseEventProvenance],
) -> PulseInstruction:
    if isinstance(instruction, PulseSequence):
        return PulseSequence(
            tuple(
                _instantiate_template_instruction(
                    child,
                    prefix=prefix,
                    template_path=(*template_path, index),
                    operation_id=operation_id,
                    implementation_id=implementation_id,
                    implementation_fingerprint=implementation_fingerprint,
                    template_program_id=template_program_id,
                    slot_substitution=slot_substitution,
                    event_ids=event_ids,
                    acquire_event_ids=acquire_event_ids,
                    provenance=provenance,
                )
                for index, child in enumerate(instruction.instructions)
            )
        )
    if isinstance(instruction, PulseParallel):
        return PulseParallel(
            tuple(
                _instantiate_template_instruction(
                    branch,
                    prefix=prefix,
                    template_path=(*template_path, index),
                    operation_id=operation_id,
                    implementation_id=implementation_id,
                    implementation_fingerprint=implementation_fingerprint,
                    template_program_id=template_program_id,
                    slot_substitution=slot_substitution,
                    event_ids=event_ids,
                    acquire_event_ids=acquire_event_ids,
                    provenance=provenance,
                )
                for index, branch in enumerate(instruction.branches)
            )
        )

    template_event_id = instruction.id
    event_id = template_event_id.prefixed(*prefix)
    event_ids.append(event_id)
    lowered_instruction = replace(instruction, id=event_id)
    if isinstance(lowered_instruction, Acquire):
        acquire_event_ids.append(event_id)
        if slot_substitution is not None:
            template_slot_id, output_slot_id = slot_substitution
            if lowered_instruction.slot_id == template_slot_id:
                lowered_instruction = replace(
                    lowered_instruction,
                    slot_id=output_slot_id,
                )
    provenance.append(
        CircuitPulseEventProvenance(
            event_id=event_id,
            operation_id=operation_id,
            implementation_id=implementation_id,
            implementation_fingerprint=implementation_fingerprint,
            template_program_id=template_program_id,
            template_event_id=template_event_id,
            template_path=template_path,
        )
    )
    return lowered_instruction


def _issue_sort_key(
    issue: CircuitPulseLoweringIssue,
) -> tuple[object, ...]:
    path = tuple(
        (0, item) if isinstance(item, int) else (1, item) for item in issue.path
    )
    operation_id = issue.operation_id.value if issue.operation_id is not None else ""
    implementation_id = (
        issue.implementation_id.value if issue.implementation_id is not None else ""
    )
    template_event_id = (
        (0, (), "")
        if issue.template_event_id is None
        else (
            1,
            issue.template_event_id.scope,
            issue.template_event_id.local_id,
        )
    )
    return (
        path,
        issue.code.value,
        operation_id,
        implementation_id,
        template_event_id,
        issue.message,
    )
