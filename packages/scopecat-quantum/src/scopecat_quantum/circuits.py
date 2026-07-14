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
from typing import cast

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


def _runtime_object(value: object) -> object:
    """Erase a static IR type before enforcing its runtime shape."""

    return value


def _runtime_tuple(value: object) -> tuple[object, ...] | None:
    return cast("tuple[object, ...]", value) if isinstance(value, tuple) else None


def _has_valid_acquisition_slot_identity(value: object) -> bool:
    if not isinstance(value, AcquisitionSlotId):
        return False
    local_id = _runtime_object(value.local_id)
    scope = _runtime_tuple(_runtime_object(value.scope))
    structurally_valid = (
        isinstance(local_id, str)
        and bool(local_id.strip())
        and scope is not None
        and all(isinstance(segment, str) and bool(segment.strip()) for segment in scope)
    )
    if not structurally_valid:
        return False
    try:
        _ = value.qualified_name
    except UnicodeEncodeError:
        return False
    return True


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
    raw_program = _runtime_object(program)
    if not isinstance(raw_program, CircuitProgram):
        raise CircuitVerificationError(
            (
                CircuitIssue(
                    code="circuit_program_invalid",
                    message="circuit program must be a CircuitProgram",
                    path=("program",),
                ),
            )
        )
    raw_program_id = _runtime_object(program.id)
    if not isinstance(raw_program_id, CircuitId):
        issues.append(
            CircuitIssue(
                code="circuit_program_id_invalid",
                message="circuit program id must be a CircuitId",
                path=("id",),
            )
        )
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

    definition_values = tuple(
        _runtime_object(definition) for definition in gate_definitions
    )
    canonical_operations: list[CircuitOperation] = []
    for operation, path in operation_entries:
        if isinstance(operation, Measure):
            canonical_operations.append(operation)
            continue
        definition = catalog.get(operation.gate_id)
        if definition is None:
            duplicate_count = sum(
                _gate_definition_id(candidate) == operation.gate_id
                for candidate in definition_values
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
    definition_values = tuple(_runtime_object(definition) for definition in definitions)
    for index, definition in enumerate(definition_values):
        if (
            not isinstance(definition, GateDefinition)
            or _gate_definition_id(definition) is None
            or not _gate_definition_parameters_are_valid(definition)
        ):
            issues.append(
                CircuitIssue(
                    code="gate_definition_invalid",
                    message="gate catalog entries must be GateDefinition values",
                    path=("gate_definitions", index),
                )
            )
            continue
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


def _gate_definition_id(definition: object) -> GateId | None:
    if not isinstance(definition, GateDefinition):
        return None
    raw_id = _runtime_object(definition.id)
    return raw_id if isinstance(raw_id, GateId) else None


def _gate_definition_parameters_are_valid(definition: GateDefinition) -> bool:
    raw_parameters = _runtime_object(definition.parameters)
    parameter_values = _runtime_tuple(raw_parameters)
    if parameter_values is None:
        return False
    for parameter in parameter_values:
        if not isinstance(parameter, GateParameterDefinition):
            return False
        raw_id = _runtime_object(parameter.id)
        raw_kind = _runtime_object(parameter.kind)
        if (
            not isinstance(raw_id, str)
            or not raw_id.strip()
            or not isinstance(raw_kind, GateParameterKind)
        ):
            return False
    return True


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
        raw_value = cast("object", value.value)
        raw_unit = cast("object", value.unit)
        if (
            not isinstance(raw_value, int | float)
            or isinstance(raw_value, bool)
            or not isinstance(raw_unit, str)
        ):
            return False
        try:
            if not math.isfinite(raw_value):
                return False
        except OverflowError:
            return False
        try:
            value.to("rad")
        except ValueError:
            return False
        return True
    return False


def _analyze_circuit_node(
    node: object,
    path: tuple[CircuitIssuePathItem, ...],
    issues: list[CircuitIssue],
    entries: list[tuple[CircuitOperation, tuple[CircuitIssuePathItem, ...]]],
) -> set[QubitId]:
    if isinstance(node, GateCall):
        valid = True
        gate_operation_id_value = _runtime_object(node.id)
        raw_gate_id = _runtime_object(node.gate_id)
        raw_qubits = _runtime_object(node.qubits)
        raw_arguments = _runtime_object(node.arguments)
        qubit_values = _runtime_tuple(raw_qubits)
        argument_values = _runtime_tuple(raw_arguments)
        if not isinstance(gate_operation_id_value, CircuitOperationId):
            issues.append(
                CircuitIssue(
                    code="circuit_operation_id_invalid",
                    message="gate call id must be a CircuitOperationId",
                    path=(*path, "id"),
                )
            )
            valid = False
        if not isinstance(raw_gate_id, GateId):
            issues.append(
                CircuitIssue(
                    code="circuit_gate_id_invalid",
                    message="gate call gate_id must be a GateId",
                    path=(*path, "gate_id"),
                )
            )
            valid = False
        if qubit_values is None or not all(
            isinstance(qubit, QubitId) for qubit in qubit_values
        ):
            issues.append(
                CircuitIssue(
                    code="circuit_gate_qubits_invalid",
                    message="gate call qubits must be a tuple of QubitId values",
                    path=(*path, "qubits"),
                )
            )
            valid = False
        if argument_values is None or not all(
            isinstance(argument, GateArgument) for argument in argument_values
        ):
            issues.append(
                CircuitIssue(
                    code="circuit_gate_arguments_invalid",
                    message=(
                        "gate call arguments must be a tuple of GateArgument values"
                    ),
                    path=(*path, "arguments"),
                )
            )
            valid = False
        if valid:
            entries.append((node, path))
        if qubit_values is None:
            return set()
        return {qubit for qubit in qubit_values if isinstance(qubit, QubitId)}
    if isinstance(node, Measure):
        valid = True
        measure_operation_id_value = _runtime_object(node.id)
        raw_qubit = _runtime_object(node.qubit)
        raw_slot_id = _runtime_object(node.acquisition_slot_id)
        raw_acquisition_kind = _runtime_object(node.acquisition_kind)
        if not isinstance(measure_operation_id_value, CircuitOperationId):
            issues.append(
                CircuitIssue(
                    code="circuit_operation_id_invalid",
                    message="measure id must be a CircuitOperationId",
                    path=(*path, "id"),
                )
            )
            valid = False
        if not isinstance(raw_qubit, QubitId):
            issues.append(
                CircuitIssue(
                    code="circuit_measure_qubit_invalid",
                    message="measure qubit must be a QubitId",
                    path=(*path, "qubit"),
                )
            )
            valid = False
        if not _has_valid_acquisition_slot_identity(raw_slot_id):
            issues.append(
                CircuitIssue(
                    code="circuit_acquisition_slot_id_invalid",
                    message=(
                        "measure acquisition_slot_id must be an AcquisitionSlotId"
                    ),
                    path=(*path, "acquisition_slot_id"),
                )
            )
            valid = False
        if not isinstance(raw_acquisition_kind, AcquisitionKind):
            issues.append(
                CircuitIssue(
                    code="circuit_acquisition_kind_invalid",
                    message="measure acquisition_kind must be an AcquisitionKind",
                    path=(*path, "acquisition_kind"),
                )
            )
            valid = False
        if valid:
            entries.append((node, path))
        return {raw_qubit} if isinstance(raw_qubit, QubitId) else set()
    if isinstance(node, Sequence):
        raw_operations = _runtime_object(node.operations)
        operation_values = _runtime_tuple(raw_operations)
        if operation_values is None:
            issues.append(
                CircuitIssue(
                    code="circuit_sequence_operations_invalid",
                    message="sequence operations must be a tuple",
                    path=(*path, "operations"),
                )
            )
            return set()
        sequence_touched: set[QubitId] = set()
        for index, operation in enumerate(operation_values):
            sequence_touched.update(
                _analyze_circuit_node(
                    operation,
                    (*path, "operations", index),
                    issues,
                    entries,
                )
            )
        return sequence_touched
    if not isinstance(node, Parallel):
        issues.append(
            CircuitIssue(
                code="circuit_node_invalid",
                message=(
                    "circuit nodes must be GateCall, Measure, Sequence, or Parallel"
                ),
                path=path,
            )
        )
        return set()
    raw_branches = _runtime_object(node.branches)
    branch_values = _runtime_tuple(raw_branches)
    if branch_values is None:
        issues.append(
            CircuitIssue(
                code="circuit_parallel_branches_invalid",
                message="parallel branches must be a tuple",
                path=(*path, "branches"),
            )
        )
        return set()
    branch_qubits: list[set[QubitId]] = []
    for index, branch in enumerate(branch_values):
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
