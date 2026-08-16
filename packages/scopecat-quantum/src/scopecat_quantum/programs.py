"""Mixed gate-and-pulse quantum programs and their pulse refinement.

The source tree in this module is deliberately heterogeneous: logical gate and
measurement operations may be composed with authored pulse blocks, while an
``ImplementedGate`` retains both a gate's semantic identity and a local pulse
implementation. Refinement binds only the still-abstract operations to resolved
pulse implementations, then produces the canonical pulse authoring IR.

Pulse refinement expands the finite source tree into one canonical pulse
program behind the target-owned compile request.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, field, replace

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
)
from scopecat_quantum.circuits import (
    CircuitIssue,
    CircuitVerificationError,
    Measure,
    VerifiedCircuitOperations,
    verify_circuit_operations,
)
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.measurement_implementations import (
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
    AcquireSignal,
    AcquisitionSlot,
    DriveSignal,
    LogicalSignal,
    PulseInstruction,
    PulseProgram,
    PulseValidationError,
    ReadoutSignal,
    iter_pulse_leaves,
    pulse_leaf_owners,
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
class ParallelEach:
    """One retained entity-set map with a single bound body template."""

    entity_set_id: str
    item_id: QubitId
    entity_ids: tuple[QubitId, ...]
    operation: QuantumNode

    def __post_init__(self) -> None:
        if not self.entity_set_id:
            raise ValueError("quantum parallel_each entity-set id must be non-empty")
        if not self.entity_ids:
            raise ValueError("quantum parallel_each entity set must not be empty")
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("quantum parallel_each entity ids must be unique")


@dataclass(frozen=True, slots=True)
class Repeat:
    """A finite repeated subtree."""

    operation: QuantumNode
    count: int

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or self.count < 0:
            raise ValueError("quantum repeat count must be a non-negative integer")


type QuantumOperation = GateCall | Measure | PulseBlock | ImplementedGate
type QuantumNode = QuantumOperation | Sequence | Parallel | ParallelEach | Repeat


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


class QuantumProgramExpansionError(ValueError):
    """A retained program exceeds the concrete lowering budget."""

    def __init__(self, *, expanded_operation_count: int, limit: int) -> None:
        self.expanded_operation_count = expanded_operation_count
        self.limit = limit
        super().__init__(
            "quantum program requires "
            f"{expanded_operation_count} expanded operations; lowering budget "
            f"is {limit}"
        )


@dataclass(frozen=True, slots=True)
class VerifiedQuantumProgram:
    """Mixed source plus template-level logical and unresolved proofs."""

    program: QuantumProgramIR
    logical_operations: tuple[GateCall | Measure, ...]
    unresolved: VerifiedCircuitOperations
    _expanded_unresolved: VerifiedCircuitOperations | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def operations(self) -> tuple[QuantumOperation, ...]:
        return tuple(iter_quantum_operations(self.program.body))

    def expand_unresolved(
        self,
        *,
        max_expanded_operations: int | None = None,
    ) -> VerifiedCircuitOperations:
        """Materialize concrete logical leaves after a constant-memory preflight."""

        workload = estimate_quantum_program_workload(self)
        if (
            max_expanded_operations is not None
            and workload.expanded_operation_count > max_expanded_operations
        ):
            raise QuantumProgramExpansionError(
                expanded_operation_count=workload.expanded_operation_count,
                limit=max_expanded_operations,
            )
        expanded = self._expanded_unresolved
        if expanded is None:
            expanded = verify_circuit_operations(
                tuple(
                    operation
                    for operation in iter_quantum_operations(self.program.body)
                    if isinstance(operation, GateCall | Measure)
                ),
                self.unresolved.gate_definitions,
            )
            object.__setattr__(self, "_expanded_unresolved", expanded)
        return expanded


@dataclass(frozen=True, slots=True)
class QuantumProgramWorkload:
    """Logical expansion estimate without lowering pulses or rendering buffers."""

    structural_operation_count: int
    expanded_operation_count: int
    selected_entity_count: int
    max_parallel_width: int


def estimate_quantum_program_workload(
    program: VerifiedQuantumProgram,
) -> QuantumProgramWorkload:
    """Summarize retained control flow and its finite logical expansion."""

    selected_entities: set[QubitId] = set()

    def estimate(
        node: QuantumNode,
        template_items: frozenset[QubitId] | None = None,
    ) -> tuple[int, int]:
        selected_template_items: frozenset[QubitId] = (
            frozenset() if template_items is None else template_items
        )
        if isinstance(node, GateCall):
            selected_entities.update(
                qubit for qubit in node.qubits if qubit not in selected_template_items
            )
            return 1, 1
        if isinstance(node, Measure):
            if node.qubit not in selected_template_items:
                selected_entities.add(node.qubit)
            return 1, 1
        if isinstance(node, ImplementedGate):
            selected_entities.update(
                qubit
                for qubit in node.call.qubits
                if qubit not in selected_template_items
            )
            return 1, 1
        if isinstance(node, PulseBlock):
            selected_entities.update(
                owner
                for owner in pulse_leaf_owners(node.pulse_template.body)
                if isinstance(owner, QubitId) and owner not in selected_template_items
            )
            return 1, 1
        if isinstance(node, Repeat):
            structural, expanded = estimate(node.operation, selected_template_items)
            return structural, expanded * node.count
        if isinstance(node, ParallelEach):
            selected_entities.update(node.entity_ids)
            structural, expanded = estimate(
                node.operation,
                selected_template_items | {node.item_id},
            )
            return structural, expanded * len(node.entity_ids)
        children = node.operations if isinstance(node, Sequence) else node.branches
        estimates = tuple(
            estimate(child, selected_template_items) for child in children
        )
        return (
            sum(item[0] for item in estimates),
            sum(item[1] for item in estimates),
        )

    def parallel_width(node: QuantumNode) -> int:
        if isinstance(node, GateCall | Measure | ImplementedGate | PulseBlock):
            return 1
        if isinstance(node, Repeat):
            return parallel_width(node.operation)
        if isinstance(node, ParallelEach):
            return max(len(node.entity_ids), parallel_width(node.operation))
        children = node.operations if isinstance(node, Sequence) else node.branches
        own_width = len(children) if isinstance(node, Parallel) else 1
        return max((own_width, *(parallel_width(child) for child in children)))

    structural, expanded = estimate(program.program.body)
    return QuantumProgramWorkload(
        structural_operation_count=structural,
        expanded_operation_count=expanded,
        selected_entity_count=len(selected_entities),
        max_parallel_width=parallel_width(program.program.body),
    )


def iter_quantum_operations(node: QuantumNode) -> Iterator[QuantumOperation]:
    """Yield mixed leaves in deterministic structural order."""

    if isinstance(
        node,
        GateCall | Measure | PulseBlock | ImplementedGate,
    ):
        yield node
        return
    if isinstance(node, Repeat):
        if node.count:
            yield from iter_quantum_operations(node.operation)
        return
    if isinstance(node, ParallelEach):
        for entity_id in node.entity_ids:
            yield from iter_quantum_operations(
                instantiate_parallel_each_operation(node, entity_id)
            )
        return
    children = node.operations if isinstance(node, Sequence) else node.branches
    for child in children:
        yield from iter_quantum_operations(child)


def instantiate_parallel_each_operation(
    node: ParallelEach,
    entity_id: QubitId,
) -> QuantumNode:
    """Instantiate one retained map body with entity-keyed identities."""

    if entity_id not in node.entity_ids:
        raise KeyError(entity_id)
    scope = (node.entity_set_id, entity_id.value)
    return _substitute_quantum_node(
        node.operation,
        source=node.item_id,
        target=entity_id,
        scope=scope,
    )


def _scoped_operation_id(
    operation_id: CircuitOperationId,
    scope: tuple[str, ...],
) -> CircuitOperationId:
    return CircuitOperationId("/".join((*scope, operation_id.value)))


def _substitute_qubit(
    qubit: QubitId,
    *,
    source: QubitId,
    target: QubitId,
) -> QubitId:
    return target if qubit == source else qubit


def _substitute_pulse_template(
    template: PulseProgram,
    *,
    source: QubitId,
    target: QubitId,
) -> PulseProgram:
    def substitute_signal(signal: LogicalSignal) -> LogicalSignal:
        if isinstance(signal, DriveSignal | ReadoutSignal | AcquireSignal):
            return replace(
                signal,
                qubit=_substitute_qubit(
                    signal.qubit,
                    source=source,
                    target=target,
                ),
            )
        if isinstance(signal.owner, QubitId):
            return replace(
                signal,
                owner=_substitute_qubit(
                    signal.owner,
                    source=source,
                    target=target,
                ),
            )
        return signal

    def substitute_instruction(instruction: PulseInstruction) -> PulseInstruction:
        if isinstance(instruction, PulseSequence):
            return PulseSequence(
                tuple(
                    substitute_instruction(child) for child in instruction.instructions
                )
            )
        if isinstance(instruction, PulseParallel):
            return PulseParallel(
                tuple(substitute_instruction(child) for child in instruction.branches)
            )
        return replace(instruction, signal=substitute_signal(instruction.signal))

    return PulseProgram(
        id=template.id,
        body=substitute_instruction(template.body),
        acquisition_slots=tuple(
            replace(slot, signal=substitute_signal(slot.signal))
            for slot in template.acquisition_slots
        ),
    )


def _substitute_quantum_node(
    node: QuantumNode,
    *,
    source: QubitId,
    target: QubitId,
    scope: tuple[str, ...],
) -> QuantumNode:
    if isinstance(node, GateCall):
        return replace(
            node,
            id=_scoped_operation_id(node.id, scope),
            qubits=tuple(
                _substitute_qubit(qubit, source=source, target=target)
                for qubit in node.qubits
            ),
        )
    if isinstance(node, Measure):
        return replace(
            node,
            id=_scoped_operation_id(node.id, scope),
            qubit=_substitute_qubit(node.qubit, source=source, target=target),
            acquisition_slot_id=node.acquisition_slot_id.prefixed(*scope),
        )
    if isinstance(node, PulseBlock):
        return replace(
            node,
            id=_scoped_operation_id(node.id, scope),
            pulse_template=_substitute_pulse_template(
                node.pulse_template,
                source=source,
                target=target,
            ),
            acquisition_slot_bindings=tuple(
                (template_id, output_id.prefixed(*scope))
                for template_id, output_id in node.acquisition_slot_bindings
            ),
        )
    if isinstance(node, ImplementedGate):
        call = _substitute_quantum_node(
            node.call,
            source=source,
            target=target,
            scope=scope,
        )
        assert isinstance(call, GateCall)
        return replace(
            node,
            call=call,
            pulse_template=_substitute_pulse_template(
                node.pulse_template,
                source=source,
                target=target,
            ),
        )
    if isinstance(node, Sequence):
        return Sequence(
            tuple(
                _substitute_quantum_node(
                    child,
                    source=source,
                    target=target,
                    scope=scope,
                )
                for child in node.operations
            )
        )
    if isinstance(node, Parallel):
        return Parallel(
            tuple(
                _substitute_quantum_node(
                    child,
                    source=source,
                    target=target,
                    scope=scope,
                )
                for child in node.branches
            )
        )
    if isinstance(node, Repeat):
        return Repeat(
            operation=_substitute_quantum_node(
                node.operation,
                source=source,
                target=target,
                scope=scope,
            ),
            count=node.count,
        )
    return ParallelEach(
        entity_set_id=node.entity_set_id,
        item_id=_substitute_qubit(node.item_id, source=source, target=target),
        entity_ids=tuple(
            _substitute_qubit(entity, source=source, target=target)
            for entity in node.entity_ids
        ),
        operation=_substitute_quantum_node(
            node.operation,
            source=source,
            target=target,
            scope=scope,
        ),
    )


def verify_quantum_program(
    program: QuantumProgramIR,
    gate_definitions: SequenceCollection[GateDefinition],
) -> VerifiedQuantumProgram:
    """Verify the mixed source and its logical operations."""

    logical, unresolved = _verified_quantum_program_components(
        program,
        gate_definitions,
    )
    return VerifiedQuantumProgram(program, logical.operations, unresolved)


def _verified_quantum_program_components(
    program: QuantumProgramIR,
    gate_definitions: SequenceCollection[GateDefinition],
) -> tuple[
    VerifiedCircuitOperations,
    VerifiedCircuitOperations,
]:
    """Validate and canonicalize the fields stored by a verified program."""

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

    parallel_issues: list[CircuitIssue] = []
    _verify_parallel_qubits(program.body, ("body",), parallel_issues)

    definitions = tuple(gate_definitions)
    try:
        logical = verify_circuit_operations(
            tuple(
                operation.call if isinstance(operation, ImplementedGate) else operation
                for operation, _path in operation_entries
                if not isinstance(operation, PulseBlock)
            ),
            definitions,
        )
    except CircuitVerificationError as error:
        if parallel_issues:
            raise CircuitVerificationError((*parallel_issues, *error.issues)) from None
        raise
    if parallel_issues:
        raise CircuitVerificationError(parallel_issues)
    unresolved = verify_circuit_operations(
        tuple(
            operation
            for operation, _path in operation_entries
            if isinstance(operation, GateCall | Measure)
        ),
        definitions,
    )
    return logical, unresolved


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


def _iter_operations_with_paths(
    node: QuantumNode,
    path: tuple[QuantumIssuePathItem, ...],
) -> Iterator[tuple[QuantumOperation, tuple[QuantumIssuePathItem, ...]]]:
    if isinstance(
        node,
        GateCall | Measure | PulseBlock | ImplementedGate,
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
    if isinstance(node, ParallelEach):
        yield from _iter_operations_with_paths(
            node.operation,
            (*path, "operation"),
        )
        return
    if node.count:
        yield from _iter_operations_with_paths(
            node.operation,
            (*path, "operation"),
        )


def _verify_parallel_qubits(
    node: QuantumNode,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[CircuitIssue],
) -> set[QubitId]:
    if isinstance(node, GateCall):
        return set(node.qubits)
    if isinstance(node, Measure):
        return {node.qubit}
    if isinstance(node, PulseBlock):
        return set()
    if isinstance(node, ImplementedGate):
        return set(node.call.qubits)
    if isinstance(node, Sequence):
        touched: set[QubitId] = set()
        for index, child in enumerate(node.operations):
            touched.update(
                _verify_parallel_qubits(
                    child,
                    (*path, "operations", index),
                    issues,
                )
            )
        return touched
    if isinstance(node, Parallel):
        branch_qubits = tuple(
            _verify_parallel_qubits(
                branch,
                (*path, "branches", index),
                issues,
            )
            for index, branch in enumerate(node.branches)
        )
        for right_index, right_qubits in enumerate(branch_qubits):
            for left_index in range(right_index):
                for qubit in sorted(
                    branch_qubits[left_index] & right_qubits,
                    key=lambda item: item.value,
                ):
                    issues.append(
                        CircuitIssue(
                            code="parallel_qubit_conflict",
                            message=(
                                f"parallel branches {left_index} and {right_index} "
                                f"both use qubit {qubit.value!r}"
                            ),
                            path=(*path, "branches", right_index),
                        )
                    )
        parallel_touched: set[QubitId] = set()
        for branch in branch_qubits:
            parallel_touched.update(branch)
        return parallel_touched
    if isinstance(node, ParallelEach):
        template_qubits = _verify_parallel_qubits(
            node.operation,
            (*path, "operation"),
            issues,
        )
        _verify_parallel_each_gate_substitutions(node, path, issues)
        owners: dict[QubitId, int] = {}
        for right_index, entity_id in enumerate(node.entity_ids):
            right_qubits = {
                entity_id if qubit == node.item_id else qubit
                for qubit in template_qubits
            }
            for qubit in sorted(right_qubits, key=lambda item: item.value):
                left_index = owners.get(qubit)
                if left_index is not None:
                    issues.append(
                        CircuitIssue(
                            code="parallel_qubit_conflict",
                            message=(
                                f"parallel_each entities {left_index} and "
                                f"{right_index} both use qubit {qubit.value!r}"
                            ),
                            path=(
                                *path,
                                "entities",
                                node.entity_ids[right_index].value,
                            ),
                        )
                    )
                else:
                    owners[qubit] = right_index
        return set(owners)
    if node.count == 0:
        return set()
    return _verify_parallel_qubits(
        node.operation,
        (*path, "operation"),
        issues,
    )


def _verify_parallel_each_gate_substitutions(
    node: ParallelEach,
    path: tuple[QuantumIssuePathItem, ...],
    issues: list[CircuitIssue],
) -> None:
    """Reject entity substitutions that collapse distinct gate operands."""

    for operation, operation_path in _iter_operations_with_paths(
        node.operation,
        (*path, "operation"),
    ):
        call = operation.call if isinstance(operation, ImplementedGate) else operation
        if not isinstance(call, GateCall) or node.item_id not in call.qubits:
            continue
        fixed_qubits = set(call.qubits) - {node.item_id}
        for entity_id in node.entity_ids:
            if entity_id not in fixed_qubits:
                continue
            issues.append(
                CircuitIssue(
                    code="circuit_gate_qubit_duplicate",
                    message=(
                        f"gate call {call.id.value!r} uses qubit "
                        f"{entity_id.value!r} more than once after parallel_each "
                        "substitution"
                    ),
                    path=(*operation_path, "entities", entity_id.value, "qubits"),
                )
            )


@dataclass(frozen=True, slots=True)
class LoweredQuantumPulseProgram:
    """Canonical pulse program produced by quantum lowering."""

    program: PulseProgram


@dataclass(frozen=True, slots=True)
class _InstantiatedTemplate:
    body: PulseInstruction
    acquisition_slots: tuple[AcquisitionSlot, ...]


def lower_quantum_program_to_pulses(
    program: VerifiedQuantumProgram,
    implementations: ResolvedPulseImplementations,
    *,
    output_id: PulseProgramId,
    max_expanded_operations: int | None = None,
) -> LoweredQuantumPulseProgram:
    """Resolve abstract leaves and lower one mixed program within its budget."""

    bindings = bind_pulse_implementations(
        program.expand_unresolved(
            max_expanded_operations=max_expanded_operations,
        ),
        implementations,
    )
    acquisition_slots: list[AcquisitionSlot] = []
    body = _lower_node(
        program.program.body,
        source_program_id=program.program.id,
        bindings=bindings,
        acquisition_slots=acquisition_slots,
        occurrence_scope=(),
    )
    return LoweredQuantumPulseProgram(
        program=PulseProgram(
            id=output_id,
            body=body,
            acquisition_slots=tuple(acquisition_slots),
        ),
    )


def _lower_node(
    node: QuantumNode,
    *,
    source_program_id: QuantumProgramId,
    bindings: PulseImplementationBindings,
    acquisition_slots: list[AcquisitionSlot],
    occurrence_scope: tuple[str, ...],
) -> PulseInstruction:
    if isinstance(node, Sequence):
        return PulseSequence(
            tuple(
                _lower_node(
                    child,
                    source_program_id=source_program_id,
                    bindings=bindings,
                    acquisition_slots=acquisition_slots,
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
                    acquisition_slots=acquisition_slots,
                    occurrence_scope=occurrence_scope,
                )
                for child in node.branches
            )
        )
    if isinstance(node, ParallelEach):
        return PulseParallel(
            tuple(
                _lower_node(
                    instantiate_parallel_each_operation(node, entity_id),
                    source_program_id=source_program_id,
                    bindings=bindings,
                    acquisition_slots=acquisition_slots,
                    occurrence_scope=occurrence_scope,
                )
                for entity_id in node.entity_ids
            )
        )
    if isinstance(node, Repeat):
        return PulseSequence(
            tuple(
                _lower_node(
                    node.operation,
                    source_program_id=source_program_id,
                    bindings=bindings,
                    acquisition_slots=acquisition_slots,
                    occurrence_scope=(*occurrence_scope, f"repeat[{index}]"),
                )
                for index in range(node.count)
            )
        )
    return _lower_leaf(
        node,
        source_program_id=source_program_id,
        bindings=bindings,
        acquisition_slots=acquisition_slots,
        occurrence_scope=occurrence_scope,
    )


def _lower_leaf(
    node: QuantumOperation,
    *,
    source_program_id: QuantumProgramId,
    bindings: PulseImplementationBindings,
    acquisition_slots: list[AcquisitionSlot],
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
        return instantiated.body

    if isinstance(node, ImplementedGate):
        return _instantiate_template(node.pulse_template, prefix=prefix).body

    binding = bindings.binding_for(node.id)
    if isinstance(node, GateCall):
        assert isinstance(binding, GatePulseImplementationBinding)
        return _instantiate_template(binding.pulse_template, prefix=prefix).body

    assert isinstance(node, Measure)
    assert isinstance(binding, MeasurementPulseImplementationBinding)
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

    def instantiate(instruction: PulseInstruction) -> PulseInstruction:
        if isinstance(instruction, PulseSequence):
            return PulseSequence(
                tuple(instantiate(child) for child in instruction.instructions)
            )
        if isinstance(instruction, PulseParallel):
            return PulseParallel(
                tuple(instantiate(child) for child in instruction.branches)
            )
        event_id = instruction.id.prefixed(*prefix)
        selected = replace(instruction, id=event_id)
        if isinstance(selected, Acquire):
            selected = replace(selected, slot_id=slot_ids[selected.slot_id])
        return selected

    body = instantiate(template.body)
    return _InstantiatedTemplate(
        body=body,
        acquisition_slots=tuple(
            replace(slot, id=slot_ids[slot.id]) for slot in template.acquisition_slots
        ),
    )
