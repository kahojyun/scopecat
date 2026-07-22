"""Mixed gate-and-pulse quantum programs and their pulse refinement.

The source tree in this module is deliberately heterogeneous: logical gate and
measurement operations may be composed with authored pulse blocks, while an
``ImplementedGate`` retains both a gate's semantic identity and a local pulse
implementation. Refinement binds only the still-abstract operations to resolved
pulse implementations, then produces the canonical pulse authoring IR.

Pulse refinement has two explicit exits. Straight-line targets receive an
expanded canonical pulse program; realtime targets receive resolved pulse
regions while bounded loops and feedback remain structural. Both forms stay
behind target-owned compile requests.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, field, replace
from typing import Literal

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
    RealtimeStateId,
    RealtimeValueId,
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
from scopecat_quantum.measurement_implementations import (
    MeasurementDiscriminator,
    MeasurementPulseImplementationBinding,
)
from scopecat_quantum.pulse_implementations import (
    GatePulseImplementationBinding,
    PulseImplementationBindings,
    ResolvedPulseImplementations,
    bind_pulse_implementations,
)
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


@dataclass(frozen=True, slots=True)
class Parallel:
    """Mixed quantum branches that begin together."""

    branches: tuple[QuantumNode, ...]


@dataclass(frozen=True, slots=True)
class RealtimeBitRef:
    """An exact use of one target-local discriminated SSA value."""

    value_id: RealtimeValueId


@dataclass(frozen=True, slots=True)
class Repeat:
    """A finite loop retained for target-aware lowering."""

    operation: QuantumNode
    count: int
    axis_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or self.count < 0:
            raise ValueError("quantum repeat count must be a non-negative integer")
        if self.axis_id is not None and not self.axis_id.strip():
            raise ValueError("quantum repeat axis id must be non-empty")


@dataclass(frozen=True, slots=True)
class Conditional:
    """Measurement-conditioned control with two result-free branches."""

    condition: RealtimeBitRef
    equals: int
    when_true: QuantumNode
    when_false: QuantumNode

    def __post_init__(self) -> None:
        if self.equals not in (0, 1):
            raise ValueError("quantum realtime conditions compare against one bit")


@dataclass(frozen=True, slots=True)
class RealtimeBitStateInit:
    """Initialize explicit target-local state before a realtime loop."""

    id: CircuitOperationId
    state_id: RealtimeStateId
    value: Literal[0, 1]


@dataclass(frozen=True, slots=True)
class RealtimeBitStateRead:
    """Read explicit state into one exact SSA value."""

    id: CircuitOperationId
    state_id: RealtimeStateId
    output_id: RealtimeValueId


@dataclass(frozen=True, slots=True)
class RealtimeBitStateWrite:
    """Commit one SSA bit as the state carried to a later iteration."""

    id: CircuitOperationId
    state_id: RealtimeStateId
    source: RealtimeBitRef


@dataclass(frozen=True, slots=True)
class RealtimeBitXor:
    """Define one SSA bit as the XOR of two exact inputs."""

    id: CircuitOperationId
    output_id: RealtimeValueId
    left: RealtimeBitRef
    right: RealtimeBitRef


@dataclass(frozen=True, slots=True)
class RealtimeResultEmit:
    """Emit one target-local bit into a declared result slot."""

    id: CircuitOperationId
    result_id: AcquisitionSlotId
    source: RealtimeBitRef


@dataclass(frozen=True, slots=True)
class RealtimeResultProvenance:
    """Exact authored operation and SSA value behind one emitted result."""

    result_id: AcquisitionSlotId
    source_id: CircuitOperationId
    source_value_id: RealtimeValueId


type RealtimeOperation = (
    RealtimeBitStateInit
    | RealtimeBitStateRead
    | RealtimeBitStateWrite
    | RealtimeBitXor
    | RealtimeResultEmit
)
type QuantumOperation = (
    GateCall | Measure | PulseBlock | ImplementedGate | RealtimeOperation
)
type QuantumNode = QuantumOperation | Sequence | Parallel | Repeat | Conditional


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


@dataclass(frozen=True, slots=True)
class VerifiedQuantumProgram:
    """Mixed source plus verified logical and unresolved-circuit projections."""

    program: QuantumProgramIR
    gate_definitions: tuple[GateDefinition, ...]
    logical_circuit: VerifiedCircuitProgram = field(init=False)
    unresolved_circuit: VerifiedCircuitProgram = field(init=False)

    def __post_init__(self) -> None:
        definitions, logical, unresolved = _verified_quantum_program_components(
            self.program,
            self.gate_definitions,
        )
        object.__setattr__(self, "gate_definitions", definitions)
        object.__setattr__(self, "logical_circuit", logical)
        object.__setattr__(self, "unresolved_circuit", unresolved)

    @property
    def operations(self) -> tuple[QuantumOperation, ...]:
        return tuple(iter_quantum_operations(self.program.body))


def iter_quantum_operations(node: QuantumNode) -> Iterator[QuantumOperation]:
    """Yield mixed leaves in deterministic structural order."""

    if isinstance(
        node,
        GateCall
        | Measure
        | PulseBlock
        | ImplementedGate
        | RealtimeBitStateInit
        | RealtimeBitStateRead
        | RealtimeBitStateWrite
        | RealtimeBitXor
        | RealtimeResultEmit,
    ):
        yield node
        return
    if isinstance(node, Repeat):
        if node.count:
            yield from iter_quantum_operations(node.operation)
        return
    if isinstance(node, Conditional):
        yield from iter_quantum_operations(node.when_true)
        yield from iter_quantum_operations(node.when_false)
        return
    children = node.operations if isinstance(node, Sequence) else node.branches
    for child in children:
        yield from iter_quantum_operations(child)


def verify_quantum_program(
    program: QuantumProgramIR,
    gate_definitions: SequenceCollection[GateDefinition],
) -> VerifiedQuantumProgram:
    """Verify the mixed source and both logical circuit projections."""

    return VerifiedQuantumProgram(program, tuple(gate_definitions))


def _verified_quantum_program_components(
    program: QuantumProgramIR,
    gate_definitions: SequenceCollection[GateDefinition],
) -> tuple[
    tuple[GateDefinition, ...],
    VerifiedCircuitProgram,
    VerifiedCircuitProgram,
]:
    """Validate and canonicalize the fields stored by a verified program."""

    issues: list[QuantumProgramIssue] = []
    operation_entries = tuple(_iter_operations_with_paths(program.body, ("body",)))
    _verify_realtime_flow(program.body, _RealtimeFlow(), ("body",), issues)
    realtime_value_ids = tuple(
        value_id
        for operation, _path in operation_entries
        if (value_id := _defined_realtime_value(operation)) is not None
    )
    for value_id, count in Counter(realtime_value_ids).items():
        if count > 1:
            issues.append(
                QuantumProgramIssue(
                    code="quantum_realtime_value_duplicate",
                    message=(
                        f"realtime value {value_id.value!r} has multiple definitions"
                    ),
                )
            )
    realtime_state_ids = tuple(
        operation.state_id
        for operation, _path in operation_entries
        if isinstance(operation, RealtimeBitStateInit)
    )
    for state_id, count in Counter(realtime_state_ids).items():
        if count > 1:
            issues.append(
                QuantumProgramIssue(
                    code="quantum_realtime_state_duplicate",
                    message=f"realtime state {state_id.value!r} is initialized twice",
                )
            )
    emitted_result_ids = tuple(
        operation.result_id
        for operation, _path in operation_entries
        if isinstance(operation, RealtimeResultEmit)
    )
    for result_id, count in Counter(emitted_result_ids).items():
        if count > 1:
            issues.append(
                QuantumProgramIssue(
                    code="quantum_realtime_result_duplicate",
                    message=f"realtime result {result_id.value!r} is emitted twice",
                )
            )
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
            if effective_outputs is not None and operation_id_counts[operation.id] == 1:
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
    return (
        logical_circuit.gate_definitions,
        logical_circuit,
        unresolved_circuit,
    )


def _verify_pulse_template(
    template: PulseProgram,
    *,
    operation_id: CircuitOperationId,
    path: tuple[QuantumIssuePathItem, ...],
    allow_acquisition: bool,
    issues: list[QuantumProgramIssue],
) -> None:
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
    bindings = block.acquisition_slot_bindings
    template_ids = tuple(binding[0] for binding in bindings)
    output_ids = tuple(binding[1] for binding in bindings)
    slots = block.pulse_template.acquisition_slots
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
    if not valid:
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


def _operation_id(operation: QuantumOperation) -> CircuitOperationId:
    return operation.id


def _defined_realtime_value(
    operation: QuantumOperation,
) -> RealtimeValueId | None:
    if isinstance(operation, Measure):
        return operation.realtime_bit_id
    if isinstance(operation, RealtimeBitStateRead | RealtimeBitXor):
        return operation.output_id
    return None


def _iter_operations_with_paths(
    node: QuantumNode,
    path: tuple[QuantumIssuePathItem, ...],
) -> Iterator[tuple[QuantumOperation, tuple[QuantumIssuePathItem, ...]]]:
    if isinstance(
        node,
        GateCall
        | Measure
        | PulseBlock
        | ImplementedGate
        | RealtimeBitStateInit
        | RealtimeBitStateRead
        | RealtimeBitStateWrite
        | RealtimeBitXor
        | RealtimeResultEmit,
    ):
        yield node, path
        return
    if isinstance(node, Sequence):
        for index, operation in enumerate(node.operations):
            yield from _iter_operations_with_paths(
                operation,
                (*path, "operations", index),
            )
        return
    if isinstance(node, Parallel):
        for index, branch in enumerate(node.branches):
            yield from _iter_operations_with_paths(
                branch,
                (*path, "branches", index),
            )
        return
    if isinstance(node, Repeat):
        if node.count:
            yield from _iter_operations_with_paths(
                node.operation,
                (*path, "operation"),
            )
        return
    for branch_name, branch in (
        ("when_true", node.when_true),
        ("when_false", node.when_false),
    ):
        yield from _iter_operations_with_paths(
            branch,
            (*path, branch_name),
        )


@dataclass(frozen=True, slots=True)
class _RealtimeFlow:
    values: tuple[RealtimeValueId, ...] = ()
    states: tuple[RealtimeStateId, ...] = ()


def _verify_realtime_flow(
    node: QuantumNode,
    flow: _RealtimeFlow,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[QuantumProgramIssue],
) -> _RealtimeFlow:
    """Verify exact SSA dominance and explicit state-effect ordering."""

    if isinstance(node, Measure):
        return (
            flow
            if node.realtime_bit_id is None
            else replace(flow, values=(*flow.values, node.realtime_bit_id))
        )
    if isinstance(node, GateCall | PulseBlock | ImplementedGate):
        return flow
    if isinstance(node, RealtimeBitStateInit):
        return replace(flow, states=(*flow.states, node.state_id))
    if isinstance(node, RealtimeBitStateRead):
        _require_realtime_state(node.state_id, flow, path, issues)
        return replace(flow, values=(*flow.values, node.output_id))
    if isinstance(node, RealtimeBitStateWrite):
        _require_realtime_state(node.state_id, flow, path, issues)
        _require_realtime_value(node.source, flow, path, issues)
        return flow
    if isinstance(node, RealtimeBitXor):
        _require_realtime_value(node.left, flow, (*path, "left"), issues)
        _require_realtime_value(node.right, flow, (*path, "right"), issues)
        return replace(flow, values=(*flow.values, node.output_id))
    if isinstance(node, RealtimeResultEmit):
        _require_realtime_value(node.source, flow, path, issues)
        return flow
    if isinstance(node, Sequence):
        selected = flow
        for index, operation in enumerate(node.operations):
            selected = _verify_realtime_flow(
                operation,
                selected,
                (*path, "operations", index),
                issues,
            )
        return selected
    if isinstance(node, Parallel):
        branches = tuple(
            _verify_realtime_flow(
                branch,
                flow,
                (*path, "branches", index),
                issues,
            )
            for index, branch in enumerate(node.branches)
        )
        return _RealtimeFlow(
            values=tuple(
                dict.fromkeys(value for branch in branches for value in branch.values)
            ),
            states=tuple(
                dict.fromkeys(state for branch in branches for state in branch.states)
            ),
        )
    if isinstance(node, Repeat):
        if not node.count:
            return flow
        return _verify_realtime_flow(
            node.operation,
            flow,
            (*path, "operation"),
            issues,
        )

    _require_realtime_value(
        node.condition,
        flow,
        (*path, "condition"),
        issues,
        code="quantum_realtime_condition_not_dominated",
    )
    when_true = _verify_realtime_flow(
        node.when_true,
        flow,
        (*path, "when_true"),
        issues,
    )
    when_false = _verify_realtime_flow(
        node.when_false,
        flow,
        (*path, "when_false"),
        issues,
    )
    false_values = set(when_false.values)
    false_states = set(when_false.states)
    return _RealtimeFlow(
        values=tuple(value for value in when_true.values if value in false_values),
        states=tuple(state for state in when_true.states if state in false_states),
    )


def _require_realtime_value(
    value: RealtimeBitRef,
    flow: _RealtimeFlow,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[QuantumProgramIssue],
    *,
    code: str = "quantum_realtime_value_not_dominated",
) -> None:
    if value.value_id in flow.values:
        return
    issues.append(
        QuantumProgramIssue(
            code=code,
            message=(
                f"realtime value {value.value_id.value!r} must be defined on every "
                "preceding control path"
            ),
            path=path,
        )
    )


def _require_realtime_state(
    state_id: RealtimeStateId,
    flow: _RealtimeFlow,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[QuantumProgramIssue],
) -> None:
    if state_id in flow.states:
        return
    issues.append(
        QuantumProgramIssue(
            code="quantum_realtime_state_uninitialized",
            message=f"realtime state {state_id.value!r} must be initialized first",
            path=path,
        )
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
    if isinstance(
        node,
        RealtimeBitStateInit
        | RealtimeBitStateRead
        | RealtimeBitStateWrite
        | RealtimeBitXor
        | RealtimeResultEmit,
    ):
        return CircuitSequence(())
    if isinstance(node, Sequence):
        return CircuitSequence(
            tuple(
                _circuit_projection(child, include_implemented=include_implemented)
                for child in node.operations
            )
        )
    if isinstance(node, Parallel):
        return CircuitParallel(
            tuple(
                _circuit_projection(child, include_implemented=include_implemented)
                for child in node.branches
            )
        )
    if isinstance(node, Repeat):
        if not node.count:
            return CircuitSequence(())
        return _circuit_projection(
            node.operation,
            include_implemented=include_implemented,
        )
    return CircuitSequence(
        (
            _circuit_projection(
                node.when_true,
                include_implemented=include_implemented,
            ),
            _circuit_projection(
                node.when_false,
                include_implemented=include_implemented,
            ),
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


@dataclass(frozen=True, slots=True)
class StructuredPulseBlock:
    """One resolved pulse region inside retained control flow."""

    source_id: CircuitOperationId
    program: PulseProgram
    realtime_bit_outputs: tuple[RealtimeBitOutput, ...] = ()


@dataclass(frozen=True, slots=True)
class RealtimeBitOutput:
    """One exact acquisition-to-discriminator definition in a pulse region."""

    value_id: RealtimeValueId
    acquisition_slot_id: AcquisitionSlotId
    discriminator: MeasurementDiscriminator


@dataclass(frozen=True, slots=True)
class StructuredPulseSequence:
    operations: tuple[StructuredPulseNode, ...]


@dataclass(frozen=True, slots=True)
class StructuredPulseParallel:
    branches: tuple[StructuredPulseNode, ...]


@dataclass(frozen=True, slots=True)
class StructuredPulseRepeat:
    operation: StructuredPulseNode
    count: int
    axis_id: str | None = None


@dataclass(frozen=True, slots=True)
class StructuredPulseConditional:
    condition: RealtimeBitRef
    equals: int
    when_true: StructuredPulseNode
    when_false: StructuredPulseNode


type StructuredPulseNode = (
    StructuredPulseBlock
    | RealtimeOperation
    | StructuredPulseSequence
    | StructuredPulseParallel
    | StructuredPulseRepeat
    | StructuredPulseConditional
)


@dataclass(frozen=True, slots=True)
class StructuredQuantumPulseProgram:
    """Resolved pulse regions with bounded loops and feedback retained."""

    source_program_id: QuantumProgramId
    body: StructuredPulseNode
    implementation_bindings: PulseImplementationBindings
    event_provenance: tuple[QuantumPulseEventProvenance, ...]
    acquisition_provenance: tuple[QuantumPulseAcquisitionProvenance, ...]
    realtime_result_provenance: tuple[RealtimeResultProvenance, ...]


@dataclass(frozen=True, slots=True)
class LoweredQuantumPulseProgram:
    """Pulse refinement with mixed-source event and result provenance.

    :func:`lower_quantum_program_to_pulses` owns total provenance coverage and
    implementation congruence for instances of this internal lowering snapshot.
    """

    source_program_id: QuantumProgramId
    program: PulseProgram
    implementation_bindings: PulseImplementationBindings
    event_provenance: tuple[QuantumPulseEventProvenance, ...]
    acquisition_provenance: tuple[QuantumPulseAcquisitionProvenance, ...]

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


class RealtimeControlFlowUnsupportedError(ValueError):
    """A straight-line pulse backend received measurement-conditioned control."""


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


def lower_quantum_program_to_structured_pulses(
    program: VerifiedQuantumProgram,
    implementations: ResolvedPulseImplementations,
    *,
    output_id: PulseProgramId,
) -> StructuredQuantumPulseProgram:
    """Resolve pulse implementations while retaining bounded control flow."""

    bindings = bind_pulse_implementations(
        program.unresolved_circuit,
        implementations,
    )
    event_provenance: list[QuantumPulseEventProvenance] = []
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance] = []
    realtime_result_provenance: list[RealtimeResultProvenance] = []

    def refine(node: QuantumNode) -> StructuredPulseNode:
        if isinstance(node, Sequence):
            return StructuredPulseSequence(
                tuple(refine(item) for item in node.operations)
            )
        if isinstance(node, Parallel):
            return StructuredPulseParallel(
                tuple(refine(item) for item in node.branches)
            )
        if isinstance(node, Repeat):
            return StructuredPulseRepeat(
                refine(node.operation),
                count=node.count,
                axis_id=node.axis_id,
            )
        if isinstance(node, Conditional):
            return StructuredPulseConditional(
                condition=node.condition,
                equals=node.equals,
                when_true=refine(node.when_true),
                when_false=refine(node.when_false),
            )
        if isinstance(node, RealtimeResultEmit):
            realtime_result_provenance.append(
                RealtimeResultProvenance(
                    result_id=node.result_id,
                    source_id=node.id,
                    source_value_id=node.source.value_id,
                )
            )
            return node
        if isinstance(
            node,
            RealtimeBitStateInit
            | RealtimeBitStateRead
            | RealtimeBitStateWrite
            | RealtimeBitXor,
        ):
            return node

        acquisition_slots: list[AcquisitionSlot] = []
        body = _lower_leaf(
            node,
            source_program_id=program.program.id,
            bindings=bindings,
            event_provenance=event_provenance,
            acquisition_slots=acquisition_slots,
            acquisition_provenance=acquisition_provenance,
            occurrence_scope=(),
        )
        source_id = _operation_id(node)
        realtime_bit_outputs: tuple[RealtimeBitOutput, ...] = ()
        if isinstance(node, Measure) and node.realtime_bit_id is not None:
            binding = bindings.binding_for(node.id)
            assert isinstance(  # noqa: S101
                binding, MeasurementPulseImplementationBinding
            )
            assert binding.discriminator is not None  # noqa: S101
            [output_slot] = acquisition_slots
            realtime_bit_outputs = (
                RealtimeBitOutput(
                    value_id=node.realtime_bit_id,
                    acquisition_slot_id=output_slot.id,
                    discriminator=binding.discriminator,
                ),
            )
        return StructuredPulseBlock(
            source_id=source_id,
            program=PulseProgram(
                id=PulseProgramId(f"{output_id.value}.blocks.{source_id.value}"),
                body=body,
                acquisition_slots=tuple(acquisition_slots),
            ),
            realtime_bit_outputs=realtime_bit_outputs,
        )

    return StructuredQuantumPulseProgram(
        source_program_id=program.program.id,
        body=refine(program.program.body),
        implementation_bindings=bindings,
        event_provenance=tuple(event_provenance),
        acquisition_provenance=tuple(acquisition_provenance),
        realtime_result_provenance=tuple(realtime_result_provenance),
    )


def lower_quantum_program_to_pulses(
    program: VerifiedQuantumProgram,
    implementations: ResolvedPulseImplementations,
    *,
    output_id: PulseProgramId,
) -> LoweredQuantumPulseProgram:
    """Resolve abstract leaves and lower one mixed program to pulse IR."""

    bindings = bind_pulse_implementations(
        program.unresolved_circuit,
        implementations,
    )
    event_provenance: list[QuantumPulseEventProvenance] = []
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance] = []
    acquisition_slots: list[AcquisitionSlot] = []
    body = _lower_node(
        program.program.body,
        source_program_id=program.program.id,
        bindings=bindings,
        event_provenance=event_provenance,
        acquisition_slots=acquisition_slots,
        acquisition_provenance=acquisition_provenance,
        occurrence_scope=(),
    )
    return LoweredQuantumPulseProgram(
        source_program_id=program.program.id,
        program=PulseProgram(
            id=output_id,
            body=body,
            acquisition_slots=tuple(acquisition_slots),
        ),
        implementation_bindings=bindings,
        event_provenance=tuple(event_provenance),
        acquisition_provenance=tuple(acquisition_provenance),
    )


def _lower_node(
    node: QuantumNode,
    *,
    source_program_id: QuantumProgramId,
    bindings: PulseImplementationBindings,
    event_provenance: list[QuantumPulseEventProvenance],
    acquisition_slots: list[AcquisitionSlot],
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance],
    occurrence_scope: tuple[str, ...],
) -> PulseInstruction:
    if isinstance(node, Sequence):
        return PulseSequence(
            tuple(
                _lower_node(
                    child,
                    source_program_id=source_program_id,
                    bindings=bindings,
                    event_provenance=event_provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                    occurrence_scope=occurrence_scope,
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
                    bindings=bindings,
                    event_provenance=event_provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                    occurrence_scope=occurrence_scope,
                )
                for child in node.branches
            )
        )
    if isinstance(node, Repeat):
        return PulseSequence(
            tuple(
                _lower_node(
                    node.operation,
                    source_program_id=source_program_id,
                    bindings=bindings,
                    event_provenance=event_provenance,
                    acquisition_slots=acquisition_slots,
                    acquisition_provenance=acquisition_provenance,
                    occurrence_scope=(*occurrence_scope, f"repeat[{index}]"),
                )
                for index in range(node.count)
            )
        )
    if isinstance(node, Conditional):
        raise RealtimeControlFlowUnsupportedError(
            "measurement-conditioned programs require a realtime target backend"
        )
    if isinstance(
        node,
        RealtimeBitStateInit
        | RealtimeBitStateRead
        | RealtimeBitStateWrite
        | RealtimeBitXor
        | RealtimeResultEmit,
    ):
        raise RealtimeControlFlowUnsupportedError(
            "realtime classical operations require a realtime target backend"
        )

    return _lower_leaf(
        node,
        source_program_id=source_program_id,
        bindings=bindings,
        event_provenance=event_provenance,
        acquisition_slots=acquisition_slots,
        acquisition_provenance=acquisition_provenance,
        occurrence_scope=occurrence_scope,
    )


def _lower_leaf(
    node: QuantumOperation,
    *,
    source_program_id: QuantumProgramId,
    bindings: PulseImplementationBindings,
    event_provenance: list[QuantumPulseEventProvenance],
    acquisition_slots: list[AcquisitionSlot],
    acquisition_provenance: list[QuantumPulseAcquisitionProvenance],
    occurrence_scope: tuple[str, ...],
) -> PulseInstruction:
    source_id = _operation_id(node)
    prefix = (
        "programs",
        source_program_id.value,
        *occurrence_scope,
        "operations",
        source_id.value,
    )
    if isinstance(node, PulseBlock):
        substitutions = {
            template: (
                output.prefixed(*occurrence_scope) if occurrence_scope else output
            )
            for template, output in node.acquisition_slot_bindings
        }
        instantiated = _instantiate_template(
            node.pulse_template,
            prefix=prefix,
            slot_substitutions=substitutions,
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

    binding = bindings.binding_for(node.id)
    if isinstance(node, GateCall):
        assert isinstance(binding, GatePulseImplementationBinding)  # noqa: S101
        instantiated = _instantiate_template(binding.pulse_template, prefix=prefix)
        event_provenance.extend(
            CircuitPulseEventProvenance(
                event_id=event.event_id,
                operation_id=node.id,
                implementation_id=binding.implementation_id,
                implementation_fingerprint=binding.implementation_fingerprint,
                template_program_id=binding.pulse_template.id,
                template_event_id=event.template_event_id,
                template_path=event.template_path,
            )
            for event in instantiated.events
        )
        return instantiated.body

    assert isinstance(node, Measure)  # noqa: S101
    assert isinstance(binding, MeasurementPulseImplementationBinding)  # noqa: S101
    template_slot = binding.pulse_template.acquisition_slots[0]
    output_slot_id = (
        node.acquisition_slot_id.prefixed(*occurrence_scope)
        if occurrence_scope
        else node.acquisition_slot_id
    )
    instantiated = _instantiate_template(
        binding.pulse_template,
        prefix=prefix,
        slot_substitutions={template_slot.id: output_slot_id},
    )
    [output_slot] = instantiated.acquisition_slots
    acquisition_slots.append(output_slot)
    event_provenance.extend(
        CircuitPulseEventProvenance(
            event_id=event.event_id,
            operation_id=node.id,
            implementation_id=binding.implementation_id,
            implementation_fingerprint=binding.implementation_fingerprint,
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
            acquisition_slot_id=output_slot_id,
            measurement_id=node.id,
            implementation_id=binding.implementation_id,
            implementation_fingerprint=binding.implementation_fingerprint,
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
