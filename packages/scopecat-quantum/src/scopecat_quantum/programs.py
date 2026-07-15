"""Mixed gate-and-pulse quantum programs and their pulse refinement.

The source tree in this module is deliberately heterogeneous: logical gate and
measurement operations may be composed with authored pulse blocks, while an
``ImplementedGate`` retains both a gate's semantic identity and a local pulse
implementation.  Refinement resolves only the still-abstract operations from a
calibration catalog, then produces the existing canonical pulse authoring IR.

Target compilers never consume this IR.  They continue to accept only scheduled
pulse programs, so unifying the source DSL does not weaken the target boundary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, replace
from typing import TypeGuard, cast

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
)
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    CalibrationSelection,
    GateCalibrationBinding,
    select_calibrations,
)
from scopecat_quantum.circuit_pulses import (
    CircuitPulseAcquisitionProvenance,
    CircuitPulseEventProvenance,
)
from scopecat_quantum.circuits import (
    CircuitProgram,
    Measure,
    VerifiedCircuitProgram,
    verify_circuit_program,
)
from scopecat_quantum.circuits import Parallel as CircuitParallel
from scopecat_quantum.circuits import Sequence as CircuitSequence
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.measurement_calibrations import MeasurementCalibrationBinding
from scopecat_quantum.pulses import (
    Acquire,
    AcquisitionSlot,
    PulseInstruction,
    PulseProgram,
    PulseValidationError,
    iter_pulse_leaves,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.pulses import Sequence as PulseSequence


@dataclass(frozen=True, slots=True)
class PulseBlock:
    """One authored occurrence of a reusable or inline pulse template."""

    id: CircuitOperationId
    pulse_template: PulseProgram
    acquisition_slot_bindings: tuple[
        tuple[AcquisitionSlotId, AcquisitionSlotId], ...
    ] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "acquisition_slot_bindings",
            tuple(self.acquisition_slot_bindings),
        )


@dataclass(frozen=True, slots=True)
class ImplementedGate:
    """A logical gate occurrence with an explicit local pulse implementation."""

    call: GateCall
    pulse_template: PulseProgram
    candidate_id: str | None = None

    @property
    def id(self) -> CircuitOperationId:
        return self.call.id


@dataclass(frozen=True, slots=True)
class Sequence:
    """Mixed quantum nodes executed in order."""

    operations: tuple[QuantumNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True, slots=True)
class Parallel:
    """Mixed quantum branches that begin together."""

    branches: tuple[QuantumNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "branches", tuple(self.branches))


type QuantumOperation = GateCall | Measure | PulseBlock | ImplementedGate
type QuantumNode = QuantumOperation | Sequence | Parallel


@dataclass(frozen=True, slots=True)
class QuantumProgramIR:
    """One concrete mixed quantum source tree before pulse refinement."""

    id: QuantumProgramId
    body: QuantumNode


type QuantumIssuePathItem = str | int


@dataclass(frozen=True, slots=True)
class QuantumProgramIssue:
    """One source-level mixed-program verification problem."""

    code: str
    message: str
    path: tuple[QuantumIssuePathItem, ...] = ()
    operation_id: CircuitOperationId | None = None


class QuantumProgramVerificationError(ValueError):
    """Aggregate of independently discoverable mixed-program issues."""

    __slots__ = ("issues",)

    def __init__(self, issues: SequenceCollection[QuantumProgramIssue]) -> None:
        selected = tuple(issues)
        if not selected:
            msg = "quantum program verification errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(
            sorted(
                selected,
                key=lambda issue: (
                    tuple(str(item) for item in issue.path),
                    issue.code,
                    issue.message,
                ),
            )
        )
        super().__init__(
            "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        )


@dataclass(frozen=True, slots=True, init=False)
class VerifiedQuantumProgram:
    """Mixed source plus verified logical and unresolved-circuit projections."""

    program: QuantumProgramIR
    gate_definitions: tuple[GateDefinition, ...]
    logical_circuit: VerifiedCircuitProgram
    unresolved_circuit: VerifiedCircuitProgram

    def __init__(
        self,
        program: QuantumProgramIR,
        gate_definitions: tuple[GateDefinition, ...],
        logical_circuit: VerifiedCircuitProgram,
        unresolved_circuit: VerifiedCircuitProgram,
    ) -> None:
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "gate_definitions", tuple(gate_definitions))
        object.__setattr__(self, "logical_circuit", logical_circuit)
        object.__setattr__(self, "unresolved_circuit", unresolved_circuit)

    @property
    def operations(self) -> tuple[QuantumOperation, ...]:
        return tuple(iter_quantum_operations(self.program.body))


def iter_quantum_operations(node: QuantumNode) -> Iterator[QuantumOperation]:
    """Yield mixed leaves in deterministic structural order."""

    if isinstance(node, GateCall | Measure | PulseBlock | ImplementedGate):
        yield node
        return
    children = node.operations if isinstance(node, Sequence) else node.branches
    for child in children:
        yield from iter_quantum_operations(child)


def verify_quantum_program(
    program: QuantumProgramIR,
    gate_definitions: SequenceCollection[GateDefinition],
) -> VerifiedQuantumProgram:
    """Verify the mixed source and both logical circuit projections."""

    if not isinstance(cast("object", program), QuantumProgramIR):
        raise QuantumProgramVerificationError(
            (
                QuantumProgramIssue(
                    code="quantum_program_invalid",
                    message="program must be a QuantumProgramIR",
                    path=("program",),
                ),
            )
        )
    if not isinstance(cast("object", program.id), QuantumProgramId):
        raise QuantumProgramVerificationError(
            (
                QuantumProgramIssue(
                    code="quantum_program_id_invalid",
                    message="program id must be a QuantumProgramId",
                    path=("id",),
                ),
            )
        )

    issues: list[QuantumProgramIssue] = []
    operation_entries = tuple(_iter_operations_with_paths(program.body, ("body",)))
    operation_ids = tuple(
        _operation_id(operation) for operation, _path in operation_entries
    )
    operation_id_counts = Counter(operation_ids)
    for operation_id, count in operation_id_counts.items():
        if count > 1:
            issues.append(
                QuantumProgramIssue(
                    code="quantum_operation_id_duplicate",
                    message=(
                        f"operation id {operation_id.value!r} is declared more than "
                        "once"
                    ),
                    operation_id=operation_id,
                )
            )

    acquisition_output_owners: dict[
        AcquisitionSlotId,
        tuple[CircuitOperationId, tuple[QuantumIssuePathItem, ...]],
    ] = {}
    for operation, path in operation_entries:
        if isinstance(operation, PulseBlock):
            if not isinstance(cast("object", operation.id), CircuitOperationId):
                issues.append(
                    QuantumProgramIssue(
                        code="quantum_operation_id_invalid",
                        message="pulse block id must be a CircuitOperationId",
                        path=(*path, "id"),
                    )
                )
            _verify_pulse_template(
                operation.pulse_template,
                operation_id=operation.id,
                path=(*path, "pulse_template"),
                allow_acquisition=True,
                issues=issues,
            )
            effective_outputs = _verify_acquisition_slot_bindings(
                operation,
                source_program_id=program.id,
                path=(*path, "acquisition_slot_bindings"),
                issues=issues,
            )
            if (
                effective_outputs is not None
                and isinstance(cast("object", operation.id), CircuitOperationId)
                and operation_id_counts[operation.id] == 1
            ):
                for output_id in effective_outputs:
                    existing = acquisition_output_owners.get(output_id)
                    if existing is not None:
                        existing_operation_id, _existing_path = existing
                        issues.append(
                            QuantumProgramIssue(
                                code="quantum_pulse_acquisition_output_duplicate",
                                message=(
                                    f"pulse acquisition output slot "
                                    f"{output_id.value!r} is produced by both "
                                    f"{existing_operation_id.value!r} and "
                                    f"{operation.id.value!r}"
                                ),
                                path=(*path, "acquisition_slot_bindings"),
                                operation_id=operation.id,
                            )
                        )
                    else:
                        acquisition_output_owners[output_id] = (operation.id, path)
        elif isinstance(operation, ImplementedGate):
            if (
                operation.candidate_id is not None
                and not operation.candidate_id.strip()
            ):
                issues.append(
                    QuantumProgramIssue(
                        code="quantum_candidate_id_invalid",
                        message="implemented gate candidate_id must be non-empty",
                        path=(*path, "candidate_id"),
                        operation_id=operation.id,
                    )
                )
            _verify_pulse_template(
                operation.pulse_template,
                operation_id=operation.id,
                path=(*path, "pulse_template"),
                allow_acquisition=False,
                issues=issues,
            )

    if issues:
        raise QuantumProgramVerificationError(issues)

    definitions = tuple(gate_definitions)
    logical_circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId(program.id.value),
            body=_circuit_projection(program.body, include_implemented=True),
        ),
        definitions,
    )
    unresolved_circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId(program.id.value),
            body=_circuit_projection(program.body, include_implemented=False),
        ),
        definitions,
    )
    return VerifiedQuantumProgram(
        program,
        logical_circuit.gate_definitions,
        logical_circuit,
        unresolved_circuit,
    )


def _verify_pulse_template(
    template: object,
    *,
    operation_id: CircuitOperationId,
    path: tuple[QuantumIssuePathItem, ...],
    allow_acquisition: bool,
    issues: list[QuantumProgramIssue],
) -> None:
    if not isinstance(template, PulseProgram):
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_template_invalid",
                message="pulse implementation must be a PulseProgram",
                path=path,
                operation_id=operation_id,
            )
        )
        return
    if not allow_acquisition and (
        template.acquisition_slots
        or any(isinstance(leaf, Acquire) for leaf in iter_pulse_leaves(template.body))
    ):
        issues.append(
            QuantumProgramIssue(
                code="quantum_gate_implementation_acquisition_unsupported",
                message="gate implementations cannot declare or acquire results",
                path=path,
                operation_id=operation_id,
            )
        )
        return
    try:
        schedule(template)
    except PulseValidationError as error:
        issues.extend(
            QuantumProgramIssue(
                code="quantum_pulse_template_invalid",
                message=issue.message,
                path=(*path, *issue.path),
                operation_id=operation_id,
            )
            for issue in error.issues
        )


def _verify_acquisition_slot_bindings(
    block: PulseBlock,
    *,
    source_program_id: QuantumProgramId,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[QuantumProgramIssue],
) -> tuple[AcquisitionSlotId, ...] | None:
    if not isinstance(cast("object", block.pulse_template), PulseProgram):
        return None
    raw_bindings_object = cast("object", block.acquisition_slot_bindings)
    if not isinstance(raw_bindings_object, tuple):
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_bindings_invalid",
                message="pulse acquisition slot bindings must be a tuple",
                path=path,
                operation_id=block.id,
            )
        )
        return None
    raw_bindings = cast("tuple[object, ...]", raw_bindings_object)
    if not all(_is_acquisition_slot_binding(binding) for binding in raw_bindings):
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_bindings_invalid",
                message=(
                    "pulse acquisition bindings must map AcquisitionSlotId "
                    "template slots to output slots"
                ),
                path=path,
                operation_id=block.id,
            )
        )
        return None
    bindings = cast(
        "tuple[tuple[AcquisitionSlotId, AcquisitionSlotId], ...]",
        raw_bindings,
    )
    template_ids = tuple(binding[0] for binding in bindings)
    output_ids = tuple(binding[1] for binding in bindings)
    raw_slots = cast("object", block.pulse_template.acquisition_slots)
    if not isinstance(raw_slots, tuple) or not all(
        isinstance(slot, AcquisitionSlot)
        and isinstance(cast("object", slot.id), AcquisitionSlotId)
        for slot in cast("tuple[object, ...]", raw_slots)
    ):
        return None
    slots = cast("tuple[AcquisitionSlot, ...]", raw_slots)
    declared_ids = {slot.id for slot in slots}
    valid = True
    if len(set(template_ids)) != len(template_ids):
        valid = False
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_binding_duplicate",
                message="pulse acquisition template slots may be bound only once",
                path=path,
                operation_id=block.id,
            )
        )
    unknown = set(template_ids) - declared_ids
    if unknown:
        valid = False
        rendered = ", ".join(
            repr(slot.value) for slot in sorted(unknown, key=lambda item: item.value)
        )
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_binding_unknown",
                message=f"pulse acquisition bindings contain unknown slots: {rendered}",
                path=path,
                operation_id=block.id,
            )
        )
    if len(set(output_ids)) != len(output_ids):
        valid = False
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_output_duplicate",
                message="pulse acquisition output slot ids must be unique",
                path=path,
                operation_id=block.id,
            )
        )
    if not valid or not isinstance(cast("object", block.id), CircuitOperationId):
        return None

    substitutions = dict(bindings)
    prefix = (
        "programs",
        source_program_id.value,
        "operations",
        block.id.value,
    )
    effective_outputs = tuple(
        substitutions.get(slot.id, slot.id.prefixed(*prefix)) for slot in slots
    )
    if len(set(effective_outputs)) != len(effective_outputs):
        issues.append(
            QuantumProgramIssue(
                code="quantum_pulse_acquisition_output_duplicate",
                message=("effective pulse acquisition output slot ids must be unique"),
                path=path,
                operation_id=block.id,
            )
        )
        return None
    return effective_outputs


def _is_acquisition_slot_binding(
    value: object,
) -> TypeGuard[tuple[AcquisitionSlotId, AcquisitionSlotId]]:
    if not isinstance(value, tuple):
        return False
    selected = cast("tuple[object, ...]", value)
    return (
        len(selected) == 2
        and isinstance(selected[0], AcquisitionSlotId)
        and isinstance(selected[1], AcquisitionSlotId)
    )


def _operation_id(operation: QuantumOperation) -> CircuitOperationId:
    return operation.id


def _iter_operations_with_paths(
    node: QuantumNode,
    path: tuple[QuantumIssuePathItem, ...],
) -> Iterator[tuple[QuantumOperation, tuple[QuantumIssuePathItem, ...]]]:
    if isinstance(node, GateCall | Measure | PulseBlock | ImplementedGate):
        yield node, path
        return
    if isinstance(node, Sequence):
        for index, operation in enumerate(node.operations):
            yield from _iter_operations_with_paths(
                operation,
                (*path, "operations", index),
            )
        return
    if not isinstance(cast("object", node), Parallel):
        raise QuantumProgramVerificationError(
            (
                QuantumProgramIssue(
                    code="quantum_node_invalid",
                    message=(
                        "quantum nodes must be gate, measure, pulse block, "
                        "implemented gate, sequence, or parallel values"
                    ),
                    path=path,
                ),
            )
        )
    for index, branch in enumerate(node.branches):
        yield from _iter_operations_with_paths(
            branch,
            (*path, "branches", index),
        )


def _circuit_projection(
    node: QuantumNode,
    *,
    include_implemented: bool,
) -> GateCall | Measure | CircuitSequence | CircuitParallel:
    if isinstance(node, GateCall | Measure):
        return node
    if isinstance(node, PulseBlock):
        return CircuitSequence(())
    if isinstance(node, ImplementedGate):
        return node.call if include_implemented else CircuitSequence(())
    if isinstance(node, Sequence):
        return CircuitSequence(
            tuple(
                _circuit_projection(child, include_implemented=include_implemented)
                for child in node.operations
            )
        )
    return CircuitParallel(
        tuple(
            _circuit_projection(child, include_implemented=include_implemented)
            for child in node.branches
        )
    )


@dataclass(frozen=True, slots=True)
class AuthoredPulseEventProvenance:
    """Origin of one event authored directly as a pulse block."""

    event_id: PulseEventId
    source_id: CircuitOperationId
    template_program_id: PulseProgramId
    template_event_id: PulseEventId
    template_path: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_path", tuple(self.template_path))


@dataclass(frozen=True, slots=True)
class ImplementedGatePulseEventProvenance:
    """Origin of one event from an explicitly implemented gate occurrence."""

    event_id: PulseEventId
    operation_id: CircuitOperationId
    gate_id: GateId
    candidate_id: str | None
    template_program_id: PulseProgramId
    template_event_id: PulseEventId
    template_path: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "template_path", tuple(self.template_path))


type QuantumPulseEventProvenance = (
    CircuitPulseEventProvenance
    | AuthoredPulseEventProvenance
    | ImplementedGatePulseEventProvenance
)


@dataclass(frozen=True, slots=True)
class AuthoredPulseAcquisitionProvenance:
    """Template-to-output mapping for one directly authored acquisition."""

    acquisition_slot_id: AcquisitionSlotId
    source_id: CircuitOperationId
    template_program_id: PulseProgramId
    template_acquisition_slot_id: AcquisitionSlotId
    acquire_event_id: PulseEventId


type QuantumPulseAcquisitionProvenance = (
    CircuitPulseAcquisitionProvenance | AuthoredPulseAcquisitionProvenance
)


@dataclass(frozen=True, slots=True, init=False)
class LoweredQuantumPulseProgram:
    """Pulse refinement with total mixed-source event and result provenance."""

    source_program_id: QuantumProgramId
    program: PulseProgram
    calibration_selection: CalibrationSelection
    event_provenance: tuple[QuantumPulseEventProvenance, ...]
    acquisition_provenance: tuple[QuantumPulseAcquisitionProvenance, ...]

    def __init__(
        self,
        source_program_id: QuantumProgramId,
        program: PulseProgram,
        calibration_selection: CalibrationSelection,
        event_provenance: tuple[QuantumPulseEventProvenance, ...],
        acquisition_provenance: tuple[QuantumPulseAcquisitionProvenance, ...],
    ) -> None:
        selected_events = tuple(event_provenance)
        selected_acquisitions = tuple(acquisition_provenance)
        event_ids = tuple(leaf.id for leaf in iter_pulse_leaves(program.body))
        provenance_event_ids = tuple(item.event_id for item in selected_events)
        if event_ids != provenance_event_ids or len(set(event_ids)) != len(event_ids):
            msg = "quantum pulse provenance must exactly cover unique pulse events"
            raise ValueError(msg)
        acquisition_ids = tuple(slot.id for slot in program.acquisition_slots)
        provenance_acquisition_ids = tuple(
            item.acquisition_slot_id for item in selected_acquisitions
        )
        if acquisition_ids != provenance_acquisition_ids or len(
            set(acquisition_ids)
        ) != len(acquisition_ids):
            msg = "quantum pulse acquisition provenance must exactly cover unique slots"
            raise ValueError(msg)
        if calibration_selection.circuit_id != CircuitId(source_program_id.value):
            msg = "quantum pulse calibration selection belongs to another program"
            raise ValueError(msg)
        object.__setattr__(self, "source_program_id", source_program_id)
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "calibration_selection", calibration_selection)
        object.__setattr__(self, "event_provenance", selected_events)
        object.__setattr__(self, "acquisition_provenance", selected_acquisitions)

    def provenance_for(
        self,
        event_id: PulseEventId,
    ) -> QuantumPulseEventProvenance:
        """Return the exact calibrated or authored origin of one pulse event."""

        for provenance in self.event_provenance:
            if provenance.event_id == event_id:
                return provenance
        msg = f"pulse event {event_id!r} does not belong to this quantum program"
        raise KeyError(msg)

    def acquisition_provenance_for(
        self,
        slot_id: AcquisitionSlotId,
    ) -> QuantumPulseAcquisitionProvenance:
        """Return the exact source origin of one acquisition slot."""

        for provenance in self.acquisition_provenance:
            if provenance.acquisition_slot_id == slot_id:
                return provenance
        msg = f"acquisition slot {slot_id!r} does not belong to this quantum program"
        raise KeyError(msg)


@dataclass(frozen=True, slots=True)
class _EventInstantiation:
    event_id: PulseEventId
    template_event_id: PulseEventId
    template_path: tuple[int, ...]
    instruction: PulseInstruction


@dataclass(frozen=True, slots=True)
class _SlotInstantiation:
    acquisition_slot_id: AcquisitionSlotId
    template_acquisition_slot_id: AcquisitionSlotId


@dataclass(frozen=True, slots=True)
class _InstantiatedTemplate:
    body: PulseInstruction
    acquisition_slots: tuple[AcquisitionSlot, ...]
    events: tuple[_EventInstantiation, ...]
    slots: tuple[_SlotInstantiation, ...]


def lower_quantum_program_to_pulses(
    program: VerifiedQuantumProgram,
    catalog: CalibrationCatalog,
    *,
    output_id: PulseProgramId,
) -> LoweredQuantumPulseProgram:
    """Resolve abstract leaves and lower one mixed program to pulse IR."""

    if not isinstance(cast("object", program), VerifiedQuantumProgram):
        raise TypeError("quantum pulse lowering requires a VerifiedQuantumProgram")
    if not isinstance(cast("object", catalog), CalibrationCatalog):
        raise TypeError("quantum pulse lowering requires a CalibrationCatalog")
    if not isinstance(cast("object", output_id), PulseProgramId):
        raise TypeError("quantum pulse lowering output_id must be a PulseProgramId")

    selection = select_calibrations(program.unresolved_circuit, catalog)
    event_provenance: list[QuantumPulseEventProvenance] = []
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance] = []
    acquisition_slots: list[AcquisitionSlot] = []
    body = _lower_node(
        program.program.body,
        source_program_id=program.program.id,
        selection=selection,
        event_provenance=event_provenance,
        acquisition_slots=acquisition_slots,
        acquisition_provenance=acquisition_provenance,
    )
    return LoweredQuantumPulseProgram(
        source_program_id=program.program.id,
        program=PulseProgram(
            id=output_id,
            body=body,
            acquisition_slots=tuple(acquisition_slots),
        ),
        calibration_selection=selection,
        event_provenance=tuple(event_provenance),
        acquisition_provenance=tuple(acquisition_provenance),
    )


def _lower_node(
    node: QuantumNode,
    *,
    source_program_id: QuantumProgramId,
    selection: CalibrationSelection,
    event_provenance: list[QuantumPulseEventProvenance],
    acquisition_slots: list[AcquisitionSlot],
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance],
) -> PulseInstruction:
    if isinstance(node, Sequence):
        return PulseSequence(
            tuple(
                _lower_node(
                    child,
                    source_program_id=source_program_id,
                    selection=selection,
                    event_provenance=event_provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                )
                for child in node.operations
            )
        )
    if isinstance(node, Parallel):
        return PulseParallel(
            tuple(
                _lower_node(
                    child,
                    source_program_id=source_program_id,
                    selection=selection,
                    event_provenance=event_provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                )
                for child in node.branches
            )
        )

    source_id = _operation_id(node)
    prefix = (
        "programs",
        source_program_id.value,
        "operations",
        source_id.value,
    )
    if isinstance(node, PulseBlock):
        instantiated = _instantiate_template(
            node.pulse_template,
            prefix=prefix,
            slot_substitutions=dict(node.acquisition_slot_bindings),
        )
        acquisition_slots.extend(instantiated.acquisition_slots)
        event_provenance.extend(
            AuthoredPulseEventProvenance(
                event_id=event.event_id,
                source_id=node.id,
                template_program_id=node.pulse_template.id,
                template_event_id=event.template_event_id,
                template_path=event.template_path,
            )
            for event in instantiated.events
        )
        for slot in instantiated.slots:
            acquire_events = tuple(
                event
                for event in instantiated.events
                if isinstance(event.instruction, Acquire)
                and event.instruction.slot_id == slot.acquisition_slot_id
            )
            if len(acquire_events) != 1:
                raise AssertionError(
                    "verified authored pulse slots must have exactly one Acquire"
                )
            acquisition_provenance.append(
                AuthoredPulseAcquisitionProvenance(
                    acquisition_slot_id=slot.acquisition_slot_id,
                    source_id=node.id,
                    template_program_id=node.pulse_template.id,
                    template_acquisition_slot_id=(slot.template_acquisition_slot_id),
                    acquire_event_id=acquire_events[0].event_id,
                )
            )
        return instantiated.body

    if isinstance(node, ImplementedGate):
        instantiated = _instantiate_template(node.pulse_template, prefix=prefix)
        event_provenance.extend(
            ImplementedGatePulseEventProvenance(
                event_id=event.event_id,
                operation_id=node.call.id,
                gate_id=node.call.gate_id,
                candidate_id=node.candidate_id,
                template_program_id=node.pulse_template.id,
                template_event_id=event.template_event_id,
                template_path=event.template_path,
            )
            for event in instantiated.events
        )
        return instantiated.body

    binding = selection.binding_for(node.id)
    if isinstance(node, GateCall):
        assert isinstance(binding, GateCalibrationBinding)
        instantiated = _instantiate_template(binding.pulse_template, prefix=prefix)
        event_provenance.extend(
            CircuitPulseEventProvenance(
                event_id=event.event_id,
                operation_id=node.id,
                calibration_id=binding.calibration_id,
                template_program_id=binding.pulse_template.id,
                template_event_id=event.template_event_id,
                template_path=event.template_path,
            )
            for event in instantiated.events
        )
        return instantiated.body

    assert isinstance(node, Measure)
    assert isinstance(binding, MeasurementCalibrationBinding)
    template_slot = binding.pulse_template.acquisition_slots[0]
    instantiated = _instantiate_template(
        binding.pulse_template,
        prefix=prefix,
        slot_substitutions={template_slot.id: node.acquisition_slot_id},
    )
    [output_slot] = instantiated.acquisition_slots
    acquisition_slots.append(output_slot)
    event_provenance.extend(
        CircuitPulseEventProvenance(
            event_id=event.event_id,
            operation_id=node.id,
            calibration_id=binding.calibration_id,
            template_program_id=binding.pulse_template.id,
            template_event_id=event.template_event_id,
            template_path=event.template_path,
        )
        for event in instantiated.events
    )
    acquire_events = tuple(
        event for event in instantiated.events if isinstance(event.instruction, Acquire)
    )
    if len(acquire_events) != 1:
        raise AssertionError("verified measurement templates have exactly one Acquire")
    acquisition_provenance.append(
        CircuitPulseAcquisitionProvenance(
            acquisition_slot_id=node.acquisition_slot_id,
            measurement_id=node.id,
            calibration_id=binding.calibration_id,
            template_program_id=binding.pulse_template.id,
            template_acquisition_slot_id=template_slot.id,
            acquire_event_id=acquire_events[0].event_id,
        )
    )
    return instantiated.body


def _instantiate_template(
    template: PulseProgram,
    *,
    prefix: tuple[str, ...],
    slot_substitutions: dict[AcquisitionSlotId, AcquisitionSlotId] | None = None,
) -> _InstantiatedTemplate:
    substitutions = slot_substitutions or {}
    slot_ids = {
        slot.id: substitutions.get(slot.id, slot.id.prefixed(*prefix))
        for slot in template.acquisition_slots
    }
    events: list[_EventInstantiation] = []

    def instantiate(
        instruction: PulseInstruction,
        path: tuple[int, ...],
    ) -> PulseInstruction:
        if isinstance(instruction, PulseSequence):
            return PulseSequence(
                tuple(
                    instantiate(child, (*path, index))
                    for index, child in enumerate(instruction.instructions)
                )
            )
        if isinstance(instruction, PulseParallel):
            return PulseParallel(
                tuple(
                    instantiate(child, (*path, index))
                    for index, child in enumerate(instruction.branches)
                )
            )
        event_id = instruction.id.prefixed(*prefix)
        selected = replace(instruction, id=event_id)
        if isinstance(selected, Acquire):
            selected = replace(selected, slot_id=slot_ids[selected.slot_id])
        events.append(
            _EventInstantiation(
                event_id=event_id,
                template_event_id=instruction.id,
                template_path=path,
                instruction=selected,
            )
        )
        return selected

    body = instantiate(template.body, ())
    slots = tuple(
        _SlotInstantiation(
            acquisition_slot_id=slot_ids[slot.id],
            template_acquisition_slot_id=slot.id,
        )
        for slot in template.acquisition_slots
    )
    return _InstantiatedTemplate(
        body=body,
        acquisition_slots=tuple(
            replace(slot, id=slot_ids[slot.id]) for slot in template.acquisition_slots
        ),
        events=tuple(events),
        slots=slots,
    )


__all__ = [
    "AuthoredPulseAcquisitionProvenance",
    "AuthoredPulseEventProvenance",
    "ImplementedGate",
    "ImplementedGatePulseEventProvenance",
    "LoweredQuantumPulseProgram",
    "Parallel",
    "PulseBlock",
    "QuantumNode",
    "QuantumOperation",
    "QuantumProgramIR",
    "QuantumProgramIssue",
    "QuantumProgramVerificationError",
    "QuantumPulseAcquisitionProvenance",
    "QuantumPulseEventProvenance",
    "Sequence",
    "VerifiedQuantumProgram",
    "iter_quantum_operations",
    "lower_quantum_program_to_pulses",
    "verify_quantum_program",
]
