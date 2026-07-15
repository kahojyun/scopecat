"""Circuit composition and config-free structural verification.

Circuit IR contains logical operands, typed gate calls, measurement
declarations, and sequence or parallel composition. It contains no physical
channels, waveforms, sample rates, products, or record policy. A measurement
is an acquisition declaration with its own result slot, not a unitary gate.
Physical meaning enters only through later calibration and target passes.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterator
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, replace

from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    GateId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.gates import (
    GateArgument,
    GateCall,
    GateDefinition,
    GateParameterDefinition,
    GateParameterKind,
    canonical_angle_value,
)


@dataclass(frozen=True, slots=True)
class Measure:
    """A logical single-qubit measurement producing one acquisition slot."""

    id: CircuitOperationId
    qubit: QubitId
    acquisition_slot_id: AcquisitionSlotId
    acquisition_kind: AcquisitionKind


@dataclass(frozen=True, slots=True)
class Sequence:
    """Circuit nodes executed in order."""

    operations: tuple[CircuitNode, ...]


@dataclass(frozen=True, slots=True)
class Parallel:
    """Circuit branches that may execute concurrently."""

    branches: tuple[CircuitNode, ...]


type CircuitOperation = GateCall | Measure
type CircuitNode = CircuitOperation | Sequence | Parallel


@dataclass(frozen=True, slots=True)
class CircuitProgram:
    """One closed hardware-independent circuit tree."""

    id: CircuitId
    body: CircuitNode


type CircuitIssuePathItem = str | int


@dataclass(frozen=True, slots=True)
class CircuitIssue:
    """One stable, machine-readable circuit verification issue."""

    code: str
    message: str
    path: tuple[CircuitIssuePathItem, ...] = ()


class CircuitVerificationError(ValueError):
    """Aggregate failure raised after all independent checks have run."""

    def __init__(self, issues: SequenceCollection[CircuitIssue]) -> None:
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(summary)


@dataclass(frozen=True, slots=True, init=False)
class VerifiedCircuitProgram:
    """Circuit and catalog facts safe for later domain lowering.

    ``operations`` is flattened in circuit order. Arguments of verified gate
    calls are canonicalized into their definition order, so downstream
    calibration matching does not depend on authoring argument order.
    """

    program: CircuitProgram
    gate_definitions: tuple[GateDefinition, ...]
    operations: tuple[CircuitOperation, ...]

    def __init__(
        self,
        program: CircuitProgram,
        gate_definitions: tuple[GateDefinition, ...],
        operations: tuple[CircuitOperation, ...],
    ) -> None:
        object.__setattr__(self, "program", program)
        object.__setattr__(self, "gate_definitions", gate_definitions)
        object.__setattr__(self, "operations", operations)

    def gate_definition(self, gate_id: GateId) -> GateDefinition:
        """Return the proven unique definition for ``gate_id``."""

        for definition in self.gate_definitions:
            if definition.id == gate_id:
                return definition
        msg = f"verified circuit has no gate definition {gate_id.value!r}"
        raise KeyError(msg)


def iter_circuit_operations(node: CircuitNode) -> Iterator[CircuitOperation]:
    """Yield leaf operations in deterministic structural order."""

    if isinstance(node, GateCall | Measure):
        yield node
        return
    children = node.operations if isinstance(node, Sequence) else node.branches
    for child in children:
        yield from iter_circuit_operations(child)


def verify_circuit_program(
    program: CircuitProgram,
    gate_definitions: SequenceCollection[GateDefinition],
) -> VerifiedCircuitProgram:
    """Verify a circuit against an exact gate catalog and return its proof.

    Verification is deliberately config-free and exhaustive: catalog,
    identity, argument, arity, and parallel-resource checks contribute to one
    aggregate error instead of stopping at the first malformed leaf.
    """

    issues: list[CircuitIssue] = []
    catalog = _verify_gate_catalog(gate_definitions, issues)
    operation_entries_buffer: list[
        tuple[CircuitOperation, tuple[CircuitIssuePathItem, ...]]
    ] = []
    _analyze_circuit_node(
        program.body,
        ("body",),
        issues,
        operation_entries_buffer,
    )
    operation_entries = tuple(operation_entries_buffer)
    _verify_operation_identities(operation_entries, issues)

    canonical_operations: list[CircuitOperation] = []
    for operation, path in operation_entries:
        if isinstance(operation, Measure):
            canonical_operations.append(operation)
            continue
        definition = catalog.get(operation.gate_id)
        if definition is None:
            duplicate_count = sum(
                candidate.id == operation.gate_id for candidate in gate_definitions
            )
            code = (
                "circuit_gate_ambiguous"
                if duplicate_count > 1
                else "circuit_gate_unknown"
            )
            qualifier = "ambiguous" if duplicate_count > 1 else "unknown"
            issues.append(
                CircuitIssue(
                    code=code,
                    message=(
                        f"gate call {operation.id.value!r} references {qualifier} "
                        f"gate {operation.gate_id.value!r}"
                    ),
                    path=(*path, "gate_id"),
                )
            )
            canonical_operations.append(operation)
            continue
        canonical_operations.append(
            _verify_gate_call(operation, definition, path, issues)
        )

    if issues:
        raise CircuitVerificationError(sorted(issues, key=_issue_sort_key))
    return VerifiedCircuitProgram(
        program=program,
        gate_definitions=tuple(
            sorted(gate_definitions, key=lambda definition: definition.id.value)
        ),
        operations=tuple(canonical_operations),
    )


def _verify_gate_catalog(
    definitions: SequenceCollection[GateDefinition],
    issues: list[CircuitIssue],
) -> dict[GateId, GateDefinition]:
    grouped: dict[GateId, list[GateDefinition]] = defaultdict(list)
    for definition in definitions:
        grouped[definition.id].append(definition)

    catalog: dict[GateId, GateDefinition] = {}
    for gate_id in sorted(grouped, key=lambda item: item.value):
        candidates = grouped[gate_id]
        if len(candidates) > 1:
            issues.append(
                CircuitIssue(
                    code="gate_catalog_duplicate",
                    message=f"gate catalog defines {gate_id.value!r} more than once",
                    path=("gate_definitions", gate_id.value),
                )
            )
            continue
        definition = candidates[0]
        catalog[gate_id] = definition
        parameter_counts = Counter(parameter.id for parameter in definition.parameters)
        for parameter_id in sorted(parameter_counts):
            if parameter_counts[parameter_id] > 1:
                issues.append(
                    CircuitIssue(
                        code="gate_parameter_duplicate",
                        message=(
                            f"gate {gate_id.value!r} defines parameter "
                            f"{parameter_id!r} more than once"
                        ),
                        path=(
                            "gate_definitions",
                            gate_id.value,
                            "parameters",
                            parameter_id,
                        ),
                    )
                )
    return catalog


def _verify_operation_identities(
    entries: SequenceCollection[
        tuple[CircuitOperation, tuple[CircuitIssuePathItem, ...]]
    ],
    issues: list[CircuitIssue],
) -> None:
    operation_paths: dict[
        CircuitOperationId, list[tuple[CircuitIssuePathItem, ...]]
    ] = defaultdict(list)
    acquisition_paths: dict[
        AcquisitionSlotId, list[tuple[CircuitIssuePathItem, ...]]
    ] = defaultdict(list)
    for operation, path in entries:
        operation_paths[operation.id].append(path)
        if isinstance(operation, Measure):
            acquisition_paths[operation.acquisition_slot_id].append(path)

    for operation_id in sorted(operation_paths, key=lambda item: item.value):
        paths = operation_paths[operation_id]
        if len(paths) > 1:
            issues.append(
                CircuitIssue(
                    code="circuit_operation_duplicate",
                    message=(
                        f"circuit operation id {operation_id.value!r} is used "
                        "more than once"
                    ),
                    path=(*paths[0], "id"),
                )
            )
    for slot_id in sorted(
        acquisition_paths,
        key=lambda item: (item.scope, item.local_id),
    ):
        paths = acquisition_paths[slot_id]
        if len(paths) > 1:
            issues.append(
                CircuitIssue(
                    code="circuit_acquisition_slot_duplicate",
                    message=(
                        f"acquisition slot id {slot_id.value!r} is produced "
                        "more than once"
                    ),
                    path=(*paths[0], "acquisition_slot_id"),
                )
            )


def _verify_gate_call(
    call: GateCall,
    definition: GateDefinition,
    path: tuple[CircuitIssuePathItem, ...],
    issues: list[CircuitIssue],
) -> GateCall:
    if len(call.qubits) != definition.qubit_arity:
        issues.append(
            CircuitIssue(
                code="circuit_gate_arity_mismatch",
                message=(
                    f"gate call {call.id.value!r} supplies {len(call.qubits)} qubits; "
                    f"gate {definition.id.value!r} requires "
                    f"{definition.qubit_arity}"
                ),
                path=(*path, "qubits"),
            )
        )
    duplicate_qubits = _duplicates(call.qubits)
    for qubit in sorted(duplicate_qubits, key=lambda item: item.value):
        issues.append(
            CircuitIssue(
                code="circuit_gate_qubit_duplicate",
                message=(
                    f"gate call {call.id.value!r} uses qubit {qubit.value!r} "
                    "more than once"
                ),
                path=(*path, "qubits"),
            )
        )

    supplied: dict[str, GateArgument] = {}
    argument_counts = Counter(argument.id for argument in call.arguments)
    for argument in call.arguments:
        supplied.setdefault(argument.id, argument)
    for argument_id in sorted(argument_counts):
        if argument_counts[argument_id] > 1:
            issues.append(
                CircuitIssue(
                    code="circuit_gate_argument_duplicate",
                    message=(
                        f"gate call {call.id.value!r} supplies argument "
                        f"{argument_id!r} more than once"
                    ),
                    path=(*path, "arguments", argument_id),
                )
            )

    expected = {parameter.id: parameter for parameter in definition.parameters}
    for parameter_id in sorted(expected.keys() - supplied.keys()):
        issues.append(
            CircuitIssue(
                code="circuit_gate_argument_missing",
                message=(
                    f"gate call {call.id.value!r} is missing argument {parameter_id!r}"
                ),
                path=(*path, "arguments", parameter_id),
            )
        )
    for argument_id in sorted(supplied.keys() - expected.keys()):
        issues.append(
            CircuitIssue(
                code="circuit_gate_argument_unknown",
                message=(
                    f"gate call {call.id.value!r} supplies unknown argument "
                    f"{argument_id!r}"
                ),
                path=(*path, "arguments", argument_id),
            )
        )
    for parameter in definition.parameters:
        argument = supplied.get(parameter.id)
        if argument is not None and not _argument_matches(parameter, argument):
            issues.append(
                CircuitIssue(
                    code="circuit_gate_argument_type_mismatch",
                    message=(
                        f"gate call {call.id.value!r} argument {parameter.id!r} "
                        f"does not satisfy {parameter.kind.value!r}"
                    ),
                    path=(*path, "arguments", parameter.id),
                )
            )

    if set(supplied) != set(expected) or any(
        count > 1 for count in argument_counts.values()
    ):
        return call
    return replace(
        call,
        arguments=tuple(
            _canonical_gate_argument(parameter, supplied[parameter.id])
            for parameter in definition.parameters
        ),
    )


def _canonical_gate_argument(
    parameter: GateParameterDefinition,
    argument: GateArgument,
) -> GateArgument:
    """Normalize equivalent values before exact calibration matching."""

    if parameter.kind is not GateParameterKind.ANGLE:
        return argument
    if not _argument_matches(parameter, argument):
        return argument
    value = argument.value
    if not isinstance(value, Quantity):
        return argument
    try:
        return replace(argument, value=canonical_angle_value(value))
    except ValueError:
        return argument


def _argument_matches(
    parameter: GateParameterDefinition,
    argument: GateArgument,
) -> bool:
    value = argument.value
    if parameter.kind is GateParameterKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if parameter.kind is GateParameterKind.NUMBER:
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    if parameter.kind is GateParameterKind.ANGLE:
        if not isinstance(value, Quantity):
            return False
        if not math.isfinite(value.value):
            return False
        try:
            value.to("rad")
        except ValueError:
            return False
        return True
    return False


def _analyze_circuit_node(
    node: CircuitNode,
    path: tuple[CircuitIssuePathItem, ...],
    issues: list[CircuitIssue],
    entries: list[tuple[CircuitOperation, tuple[CircuitIssuePathItem, ...]]],
) -> set[QubitId]:
    if isinstance(node, GateCall):
        entries.append((node, path))
        return set(node.qubits)
    if isinstance(node, Measure):
        entries.append((node, path))
        return {node.qubit}
    if isinstance(node, Sequence):
        sequence_touched: set[QubitId] = set()
        for index, operation in enumerate(node.operations):
            sequence_touched.update(
                _analyze_circuit_node(
                    operation,
                    (*path, "operations", index),
                    issues,
                    entries,
                )
            )
        return sequence_touched
    branch_qubits: list[set[QubitId]] = []
    for index, branch in enumerate(node.branches):
        branch_qubits.append(
            _analyze_circuit_node(
                branch,
                (*path, "branches", index),
                issues,
                entries,
            )
        )
    for right_index, right_qubits in enumerate(branch_qubits):
        for left_index in range(right_index):
            overlap = branch_qubits[left_index] & right_qubits
            for qubit in sorted(overlap, key=lambda item: item.value):
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


def _duplicates[T](values: SequenceCollection[T]) -> set[T]:
    seen: set[T] = set()
    duplicates: set[T] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _issue_sort_key(issue: CircuitIssue) -> tuple[tuple[str, ...], str, str]:
    return (
        tuple(f"{type(item).__name__}:{item}" for item in issue.path),
        issue.code,
        issue.message,
    )


__all__ = [
    "CircuitIssue",
    "CircuitIssuePathItem",
    "CircuitNode",
    "CircuitOperation",
    "CircuitProgram",
    "CircuitVerificationError",
    "Measure",
    "Parallel",
    "Sequence",
    "VerifiedCircuitProgram",
    "iter_circuit_operations",
    "verify_circuit_program",
]
