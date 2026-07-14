"""Opaque authoring handles for hardware-independent quantum circuits.

The public handles in this module describe a symbolic circuit.  Binding the
declared scalar inputs produces the existing verified circuit IR, so target
compilers and calibration passes do not need a second authoring-specific
pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import MISSING, dataclass, fields
from typing import cast

from scopecat import Quantity
from scopecat.authoring import (
    ComputeInput,
    DomainCall,
    DomainProgramDef,
    FloatType,
    IntType,
    QuantityType,
    ScalarType,
    domain_call,
    domain_program,
)

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitId,
    CircuitOperationId,
    GateId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import (
    CircuitNode,
    CircuitProgram,
    Measure,
    VerifiedCircuitProgram,
    verify_circuit_program,
)
from scopecat_quantum.circuits import Parallel as IrParallel
from scopecat_quantum.circuits import Sequence as IrSequence
from scopecat_quantum.gates import (
    GateArgument,
    GateArgumentValue,
    GateCall,
    GateDefinition,
    GateParameterDefinition,
    GateParameterKind,
)


def _runtime_object(value: object) -> object:
    """Erase a static authoring type before enforcing its runtime invariant."""

    return value


def _create_handle[HandleT](
    handle_type: type[HandleT],
    /,
    **values: object,
) -> HandleT:
    """Initialize one frozen opaque handle without exposing its constructor."""

    descriptors = {
        descriptor.name: descriptor
        for descriptor in fields(handle_type)  # pyright: ignore[reportArgumentType]
    }
    unknown = sorted(set(values) - set(descriptors))
    if unknown:
        msg = "unknown opaque handle fields: " + ", ".join(unknown)
        raise TypeError(msg)
    result = object.__new__(handle_type)
    for name, descriptor in descriptors.items():
        if name in values:
            selected = values[name]
        elif descriptor.default is not MISSING:
            selected = descriptor.default
        elif descriptor.default_factory is not MISSING:
            factory = cast("Callable[[], object]", descriptor.default_factory)
            selected = factory()
        else:
            msg = f"missing opaque handle field: {name}"
            raise TypeError(msg)
        object.__setattr__(result, name, selected)
    return result


def _opaque_handle_error(name: str, factory: str) -> TypeError:
    return TypeError(f"{name} is an opaque handle; create it with {factory}")


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Qubit:
    """A logical qubit handle, independent of physical target wiring."""

    _ir_id: QubitId

    def __init__(self) -> None:
        raise _opaque_handle_error("Qubit", "scopecat_quantum.authoring.qubit")

    @property
    def id(self) -> str:
        """Return the logical qubit port identity."""

        return self._ir_id.value


@dataclass(frozen=True, slots=True, init=False, repr=False)
class CircuitInput:
    """One typed scalar input consumed by a symbolic circuit."""

    _id: str
    kind: GateParameterKind

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "CircuitInput",
            "scopecat_quantum.authoring.scalar_input",
        )

    @property
    def id(self) -> str:
        """Return the stable input-port identity."""

        return self._id


@dataclass(frozen=True, slots=True, init=False, repr=False)
class CircuitResult:
    """One typed acquisition result produced by a measurement statement."""

    _id: str
    _qubit: Qubit
    acquisition_kind: AcquisitionKind

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "CircuitResult",
            "scopecat_quantum.authoring.measure(...).result",
        )

    @property
    def id(self) -> str:
        """Return the stable result-port identity."""

        return self._id

    @property
    def qubit(self) -> Qubit:
        """Return the logical qubit measured for this result."""

        return self._qubit

    @property
    def acquisition_slot_id(self) -> AcquisitionSlotId:
        """Return the acquisition identity used by materialized circuit IR."""

        return AcquisitionSlotId(self._id)


class CircuitFragment:
    """Opaque base type accepted by circuit composition factories."""

    __slots__ = ()

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "CircuitFragment",
            "gate calls, measure, sequence, parallel, or repeat",
        )


type CircuitArgument = GateArgumentValue | CircuitInput
type RepeatCount = int | CircuitInput

QUANTUM_CIRCUIT_DIALECT_ID = "scopecat.quantum.circuit"
QUANTUM_CIRCUIT_DIALECT_VERSION = "1"


@dataclass(frozen=True, slots=True, init=False, repr=False)
class SingleQubitGate:
    """A reusable symbolic gate with exactly one logical-qubit operand."""

    _definition: GateDefinition

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "SingleQubitGate",
            "scopecat_quantum.authoring.single_qubit_gate",
        )

    @property
    def id(self) -> str:
        """Return the gate semantic identity."""

        return self._definition.id.value

    @property
    def parameters(self) -> tuple[GateParameterDefinition, ...]:
        """Return the ordered scalar parameter contract."""

        return self._definition.parameters

    def __call__(
        self,
        qubit: Qubit,
        /,
        **arguments: CircuitArgument,
    ) -> CircuitFragment:
        """Author one occurrence of this gate on ``qubit``."""

        raw_qubit = _runtime_object(qubit)
        if not isinstance(raw_qubit, Qubit):
            msg = "single-qubit gate calls require a Qubit handle"
            raise TypeError(msg)
        expected = {parameter.id: parameter for parameter in self.parameters}
        supplied = set(arguments)
        missing = sorted(set(expected) - supplied)
        unknown = sorted(supplied - set(expected))
        if missing or unknown:
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(repr(item) for item in missing))
            if unknown:
                details.append("unknown " + ", ".join(repr(item) for item in unknown))
            msg = f"gate {self.id!r} arguments are invalid: " + "; ".join(details)
            raise ValueError(msg)
        ordered_arguments: list[tuple[str, CircuitArgument]] = []
        for parameter in self.parameters:
            value = arguments[parameter.id]
            if isinstance(value, CircuitInput):
                if value.kind is not parameter.kind:
                    msg = (
                        f"gate {self.id!r} parameter {parameter.id!r} requires "
                        f"{parameter.kind.value!r}, but input {value.id!r} declares "
                        f"{value.kind.value!r}"
                    )
                    raise TypeError(msg)
            elif not _argument_matches_kind(value, parameter.kind):
                msg = (
                    f"gate {self.id!r} parameter {parameter.id!r} requires "
                    f"{parameter.kind.value!r}"
                )
                raise TypeError(msg)
            ordered_arguments.append((parameter.id, value))
        return _create_handle(
            _GateFragment,
            gate=self,
            qubit=raw_qubit,
            arguments=tuple(ordered_arguments),
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Measurement(CircuitFragment):
    """A measurement statement and its first-class acquisition result."""

    result: CircuitResult

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "Measurement",
            "scopecat_quantum.authoring.measure",
        )


@dataclass(frozen=True, slots=True)
class _GateFragment(CircuitFragment):
    gate: SingleQubitGate
    qubit: Qubit
    arguments: tuple[tuple[str, CircuitArgument], ...]


@dataclass(frozen=True, slots=True)
class _SequenceFragment(CircuitFragment):
    operations: tuple[CircuitFragment, ...]


@dataclass(frozen=True, slots=True)
class _ParallelFragment(CircuitFragment):
    branches: tuple[CircuitFragment, ...]


@dataclass(frozen=True, slots=True)
class _RepeatFragment(CircuitFragment):
    operation: CircuitFragment
    count: RepeatCount


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Circuit:
    """A closed symbolic circuit declaration with typed input/result ports."""

    _ir_id: CircuitId
    _body: CircuitFragment
    inputs: tuple[CircuitInput, ...]
    results: tuple[CircuitResult, ...]
    _gate_definitions: tuple[GateDefinition, ...]

    def __init__(self) -> None:
        raise _opaque_handle_error("Circuit", "scopecat_quantum.authoring.circuit")

    @property
    def id(self) -> str:
        """Return the stable circuit program identity."""

        return self._ir_id.value

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the exact gate catalog captured by this declaration."""

        return self._gate_definitions


@dataclass(frozen=True, slots=True, init=False, repr=False)
class BoundCircuit:
    """A symbolic circuit bound to concrete values and verified as circuit IR."""

    circuit: Circuit
    verified: VerifiedCircuitProgram

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "BoundCircuit",
            "scopecat_quantum.authoring.bind_circuit",
        )

    @property
    def program(self) -> CircuitProgram:
        """Return the concrete circuit program accepted by downstream passes."""

        return self.verified.program

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the verified exact gate catalog."""

        return self.verified.gate_definitions

    @property
    def results(self) -> tuple[CircuitResult, ...]:
        """Return the declared result ports in structural order."""

        return self.circuit.results


class CircuitBindingError(ValueError):
    """Raised when concrete bindings cannot close a symbolic circuit."""


def _qubit_ir_id(value: Qubit) -> QubitId:
    return cast("QubitId", object.__getattribute__(value, "_ir_id"))


def _gate_definition(value: SingleQubitGate) -> GateDefinition:
    return cast("GateDefinition", object.__getattribute__(value, "_definition"))


def _circuit_ir_id(value: Circuit) -> CircuitId:
    return cast("CircuitId", object.__getattribute__(value, "_ir_id"))


def _circuit_body(value: Circuit) -> CircuitFragment:
    return cast("CircuitFragment", object.__getattribute__(value, "_body"))


def qubit(id: str) -> Qubit:  # noqa: A002
    """Declare one logical qubit handle."""

    return _create_handle(Qubit, _ir_id=QubitId(id))


def scalar_input(id: str, kind: GateParameterKind) -> CircuitInput:  # noqa: A002
    """Declare one typed scalar input port for a symbolic circuit."""

    raw_id = _runtime_object(id)
    raw_kind = _runtime_object(kind)
    if not isinstance(raw_id, str) or not raw_id.strip():
        msg = "circuit input id must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(raw_kind, GateParameterKind):
        msg = "circuit input kind must be a GateParameterKind"
        raise TypeError(msg)
    return _create_handle(CircuitInput, _id=raw_id, kind=raw_kind)


def single_qubit_gate(
    id: str,  # noqa: A002
    *,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> SingleQubitGate:
    """Declare one hardware-independent single-qubit gate semantic."""

    raw_parameters = _runtime_object(parameters)
    if raw_parameters is not None and not isinstance(raw_parameters, Mapping):
        msg = "gate parameters must be a mapping from ids to parameter kinds"
        raise TypeError(msg)
    selected: Mapping[object, object] = (
        {}
        if raw_parameters is None
        else cast("Mapping[object, object]", raw_parameters)
    )
    if not all(
        isinstance(name, str)
        and bool(name.strip())
        and isinstance(kind, GateParameterKind)
        for name, kind in selected.items()
    ):
        msg = "gate parameters must map non-empty strings to GateParameterKind values"
        raise TypeError(msg)
    definition = GateDefinition(
        id=GateId(id),
        qubit_arity=1,
        parameters=tuple(
            GateParameterDefinition(name, kind)
            for name, kind in cast("Mapping[str, GateParameterKind]", selected).items()
        ),
    )
    return _create_handle(SingleQubitGate, _definition=definition)


def measure(
    qubit: Qubit,
    /,
    *,
    result: str,
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
) -> Measurement:
    """Author one single-qubit measurement and its result port."""

    raw_qubit = _runtime_object(qubit)
    raw_result = _runtime_object(result)
    raw_acquisition_kind = _runtime_object(acquisition_kind)
    if not isinstance(raw_qubit, Qubit):
        msg = "measure requires a Qubit handle"
        raise TypeError(msg)
    if not isinstance(raw_result, str) or not raw_result.strip():
        msg = "measurement result id must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(raw_acquisition_kind, AcquisitionKind):
        msg = "measurement acquisition_kind must be an AcquisitionKind"
        raise TypeError(msg)
    result_handle = _create_handle(
        CircuitResult,
        _id=raw_result,
        _qubit=raw_qubit,
        acquisition_kind=raw_acquisition_kind,
    )
    return _create_handle(Measurement, result=result_handle)


def sequence(*operations: CircuitFragment) -> CircuitFragment:
    """Compose one or more circuit fragments in order."""

    if not operations:
        msg = "sequence requires at least one circuit fragment"
        raise ValueError(msg)
    _require_fragments(operations, composition="sequence")
    return _create_handle(_SequenceFragment, operations=operations)


def parallel(*branches: CircuitFragment) -> CircuitFragment:
    """Compose two or more disjoint circuit branches concurrently."""

    if len(branches) < 2:
        msg = "parallel requires at least two circuit branches"
        raise ValueError(msg)
    _require_fragments(branches, composition="parallel")
    return _create_handle(_ParallelFragment, branches=branches)


def repeat(operation: CircuitFragment, count: RepeatCount) -> CircuitFragment:
    """Repeat a result-free fragment a literal or symbolic number of times.

    A zero count lowers to an empty sequence.  Measurements are deliberately
    excluded because a single result handle cannot represent repeated slots.
    """

    _require_fragments((operation,), composition="repeat")
    if _fragment_results(operation):
        msg = "repeat does not support fragments that produce measurement results"
        raise ValueError(msg)
    raw_count = _runtime_object(count)
    if isinstance(raw_count, CircuitInput):
        if raw_count.kind is not GateParameterKind.INTEGER:
            msg = "repeat count inputs must have integer kind"
            raise TypeError(msg)
    elif not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 0:
        msg = "repeat count must be a non-negative integer or integer input"
        raise ValueError(msg)
    return _create_handle(
        _RepeatFragment,
        operation=operation,
        count=raw_count,
    )


def circuit(id: str, body: CircuitFragment) -> Circuit:  # noqa: A002
    """Close a symbolic fragment into one immutable circuit declaration."""

    _require_fragments((body,), composition="circuit")
    ir_id = CircuitId(id)
    collected_inputs = _fragment_inputs(body)
    inputs_by_id: dict[str, CircuitInput] = {}
    for input_handle in collected_inputs:
        existing = inputs_by_id.get(input_handle.id)
        if existing is not None and existing.kind is not input_handle.kind:
            msg = (
                f"circuit input {input_handle.id!r} is used with both "
                f"{existing.kind.value!r} and {input_handle.kind.value!r} kinds"
            )
            raise ValueError(msg)
        inputs_by_id.setdefault(input_handle.id, input_handle)

    results = _fragment_results(body)
    duplicate_results = _duplicates(result.id for result in results)
    if duplicate_results:
        rendered = ", ".join(repr(item) for item in duplicate_results)
        msg = f"circuit has duplicate result ids: {rendered}"
        raise ValueError(msg)

    definitions_by_id: dict[str, GateDefinition] = {}
    for definition in _fragment_gate_definitions(body):
        existing = definitions_by_id.get(definition.id.value)
        if existing is not None and existing != definition:
            msg = f"circuit gate {definition.id.value!r} has conflicting definitions"
            raise ValueError(msg)
        definitions_by_id.setdefault(definition.id.value, definition)

    return _create_handle(
        Circuit,
        _ir_id=ir_id,
        _body=body,
        inputs=tuple(inputs_by_id.values()),
        results=results,
        _gate_definitions=tuple(definitions_by_id.values()),
    )


def bind_circuit(
    declaration: Circuit,
    bindings: Mapping[str, GateArgumentValue] | None = None,
) -> BoundCircuit:
    """Bind every symbolic input and return verified concrete circuit IR."""

    raw_declaration = _runtime_object(declaration)
    if not isinstance(raw_declaration, Circuit):
        msg = "bind_circuit requires a Circuit handle"
        raise TypeError(msg)
    raw_selected = _runtime_object(bindings)
    if raw_selected is not None and not isinstance(raw_selected, Mapping):
        msg = "circuit bindings must be a mapping"
        raise TypeError(msg)
    raw_bindings: Mapping[object, object] = (
        {} if raw_selected is None else cast("Mapping[object, object]", raw_selected)
    )
    if not all(isinstance(name, str) for name in raw_bindings):
        msg = "circuit binding ids must be strings"
        raise CircuitBindingError(msg)
    typed_bindings = cast("Mapping[str, GateArgumentValue]", raw_bindings)
    expected = {input_handle.id for input_handle in raw_declaration.inputs}
    supplied = set(typed_bindings)
    missing = sorted(expected - supplied)
    unknown = sorted(supplied - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        raise CircuitBindingError("invalid circuit bindings: " + "; ".join(details))

    concrete = CircuitProgram(
        id=_circuit_ir_id(raw_declaration),
        body=_bind_fragment(
            _circuit_body(raw_declaration),
            typed_bindings,
            path=("body",),
        ),
    )
    verified = verify_circuit_program(concrete, raw_declaration.gate_definitions)
    return _create_handle(BoundCircuit, circuit=raw_declaration, verified=verified)


def circuit_domain_program(declaration: Circuit) -> DomainProgramDef:
    """Project a symbolic circuit into core's domain-neutral program seam."""

    raw_declaration = _runtime_object(declaration)
    if not isinstance(raw_declaration, Circuit):
        msg = "circuit_domain_program requires a Circuit handle"
        raise TypeError(msg)
    non_negative_input_ids = {
        input_handle.id
        for input_handle in _fragment_repeat_inputs(_circuit_body(raw_declaration))
    }
    return domain_program(
        raw_declaration.id,
        dialect_id=QUANTUM_CIRCUIT_DIALECT_ID,
        dialect_version=QUANTUM_CIRCUIT_DIALECT_VERSION,
        body=raw_declaration,
        inputs={
            input_handle.id: _core_input_type(
                input_handle.kind,
                non_negative=input_handle.id in non_negative_input_ids,
            )
            for input_handle in raw_declaration.inputs
        },
        results={result.id: result for result in raw_declaration.results},
    )


def circuit_domain_call(
    id: str,  # noqa: A002
    program: DomainProgramDef,
    *,
    inputs: Mapping[CircuitInput, ComputeInput] | None = None,
    results: Mapping[CircuitResult, str] | None = None,
) -> DomainCall:
    """Bind typed circuit handles to core values and logical products."""

    raw_program = _runtime_object(program)
    if not isinstance(raw_program, DomainProgramDef):
        msg = "circuit_domain_call requires a quantum circuit domain program"
        raise TypeError(msg)
    if (
        raw_program.dialect_id != QUANTUM_CIRCUIT_DIALECT_ID
        or raw_program.dialect_version != QUANTUM_CIRCUIT_DIALECT_VERSION
        or not isinstance(raw_program.body, Circuit)
    ):
        msg = "circuit_domain_call requires a quantum circuit domain program"
        raise TypeError(msg)
    declaration = raw_program.body
    expected_program = circuit_domain_program(declaration)
    if (
        raw_program.id != expected_program.id
        or raw_program.input_ports != expected_program.input_ports
        or raw_program.result_ports != expected_program.result_ports
    ):
        msg = "quantum circuit domain program ports do not match its Circuit body"
        raise ValueError(msg)
    raw_inputs = _runtime_object(inputs)
    raw_results = _runtime_object(results)
    if raw_inputs is not None and not isinstance(raw_inputs, Mapping):
        raise TypeError("circuit domain call inputs must be a mapping")
    if raw_results is not None and not isinstance(raw_results, Mapping):
        raise TypeError("circuit domain call results must be a mapping")
    selected_inputs: Mapping[CircuitInput, ComputeInput] = cast(
        "Mapping[CircuitInput, ComputeInput]",
        {} if raw_inputs is None else raw_inputs,
    )
    selected_results: Mapping[CircuitResult, str] = cast(
        "Mapping[CircuitResult, str]",
        {} if raw_results is None else raw_results,
    )
    if set(selected_inputs) != set(declaration.inputs):
        msg = "circuit domain call inputs must bind every declared CircuitInput"
        raise ValueError(msg)
    if set(selected_results) != set(declaration.results):
        msg = "circuit domain call results must bind every declared CircuitResult"
        raise ValueError(msg)
    normalized_inputs: dict[str, ComputeInput] = {}
    for handle, value in selected_inputs.items():
        normalized_inputs[handle.id] = (
            float(value)
            if handle.kind is GateParameterKind.NUMBER
            and isinstance(value, int)
            and not isinstance(value, bool)
            else value
        )
    return domain_call(
        id,
        raw_program,
        inputs=normalized_inputs,
        results={handle.id: value for handle, value in selected_results.items()},
    )


def _core_input_type(
    kind: GateParameterKind,
    *,
    non_negative: bool = False,
) -> ScalarType:
    if kind is GateParameterKind.INTEGER:
        return ScalarType(IntType(minimum=0 if non_negative else None))
    if kind is GateParameterKind.NUMBER:
        return ScalarType(FloatType())
    if kind is GateParameterKind.ANGLE:
        return ScalarType(QuantityType(dimension="angle", unit="rad"))
    raise AssertionError(f"unsupported gate parameter kind {kind!r}")


def _bind_fragment(
    fragment: CircuitFragment,
    bindings: Mapping[str, GateArgumentValue],
    *,
    path: tuple[str, ...],
) -> CircuitNode:
    if isinstance(fragment, _GateFragment):
        return GateCall(
            id=CircuitOperationId(_operation_id(path, "gate")),
            gate_id=_gate_definition(fragment.gate).id,
            qubits=(_qubit_ir_id(fragment.qubit),),
            arguments=tuple(
                GateArgument(
                    argument_id,
                    bindings[value.id] if isinstance(value, CircuitInput) else value,
                )
                for argument_id, value in fragment.arguments
            ),
        )
    if isinstance(fragment, Measurement):
        result = fragment.result
        return Measure(
            id=CircuitOperationId(_operation_id(path, "measure")),
            qubit=_qubit_ir_id(result.qubit),
            acquisition_slot_id=result.acquisition_slot_id,
            acquisition_kind=result.acquisition_kind,
        )
    if isinstance(fragment, _SequenceFragment):
        return IrSequence(
            tuple(
                _bind_fragment(
                    operation,
                    bindings,
                    path=(*path, f"sequence[{index}]"),
                )
                for index, operation in enumerate(fragment.operations)
            )
        )
    if isinstance(fragment, _ParallelFragment):
        return IrParallel(
            tuple(
                _bind_fragment(
                    branch,
                    bindings,
                    path=(*path, f"parallel[{index}]"),
                )
                for index, branch in enumerate(fragment.branches)
            )
        )
    if not isinstance(fragment, _RepeatFragment):
        msg = f"unsupported circuit fragment {type(fragment).__name__}"
        raise TypeError(msg)
    count = (
        bindings[fragment.count.id]
        if isinstance(fragment.count, CircuitInput)
        else fragment.count
    )
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        input_id = (
            fragment.count.id if isinstance(fragment.count, CircuitInput) else None
        )
        qualifier = f" input {input_id!r}" if input_id is not None else ""
        msg = f"repeat count{qualifier} must bind to a non-negative integer"
        raise CircuitBindingError(msg)
    return IrSequence(
        tuple(
            _bind_fragment(
                fragment.operation,
                bindings,
                path=(*path, f"repeat[{index}]"),
            )
            for index in range(count)
        )
    )


def _operation_id(path: tuple[str, ...], kind: str) -> str:
    return "/".join((*path, kind))


def _require_fragments(
    values: tuple[CircuitFragment, ...],
    *,
    composition: str,
) -> None:
    if not all(isinstance(_runtime_object(value), CircuitFragment) for value in values):
        msg = f"{composition} accepts only CircuitFragment handles"
        raise TypeError(msg)


def _fragment_inputs(fragment: CircuitFragment) -> tuple[CircuitInput, ...]:
    if isinstance(fragment, _GateFragment):
        return tuple(
            value
            for _argument_id, value in fragment.arguments
            if isinstance(value, CircuitInput)
        )
    if isinstance(fragment, Measurement):
        return ()
    if isinstance(fragment, _RepeatFragment):
        if fragment.count == 0:
            return ()
        count_inputs = (
            (fragment.count,) if isinstance(fragment.count, CircuitInput) else ()
        )
        return (*count_inputs, *_fragment_inputs(fragment.operation))
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment)
        else ()
    )
    return tuple(
        input_handle for child in children for input_handle in _fragment_inputs(child)
    )


def _fragment_results(fragment: CircuitFragment) -> tuple[CircuitResult, ...]:
    if isinstance(fragment, Measurement):
        return (fragment.result,)
    if isinstance(fragment, _GateFragment):
        return ()
    if isinstance(fragment, _RepeatFragment):
        if fragment.count == 0:
            return ()
        return _fragment_results(fragment.operation)
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment)
        else ()
    )
    return tuple(result for child in children for result in _fragment_results(child))


def _fragment_gate_definitions(
    fragment: CircuitFragment,
) -> tuple[GateDefinition, ...]:
    if isinstance(fragment, _GateFragment):
        return (_gate_definition(fragment.gate),)
    if isinstance(fragment, Measurement):
        return ()
    if isinstance(fragment, _RepeatFragment):
        if fragment.count == 0:
            return ()
        return _fragment_gate_definitions(fragment.operation)
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment)
        else ()
    )
    return tuple(
        definition
        for child in children
        for definition in _fragment_gate_definitions(child)
    )


def _fragment_repeat_inputs(fragment: CircuitFragment) -> tuple[CircuitInput, ...]:
    if isinstance(fragment, _RepeatFragment):
        if fragment.count == 0:
            return ()
        count_inputs = (
            (fragment.count,) if isinstance(fragment.count, CircuitInput) else ()
        )
        return (*count_inputs, *_fragment_repeat_inputs(fragment.operation))
    if isinstance(fragment, _GateFragment | Measurement):
        return ()
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment)
        else ()
    )
    return tuple(
        input_handle
        for child in children
        for input_handle in _fragment_repeat_inputs(child)
    )


def _argument_matches_kind(value: object, kind: GateParameterKind) -> bool:
    if kind is GateParameterKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind is GateParameterKind.NUMBER:
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except OverflowError:
            return False
    if kind is not GateParameterKind.ANGLE or not isinstance(value, Quantity):
        return False
    try:
        converted = value.to("rad")
    except ValueError:
        return False
    return math.isfinite(float(converted.value))


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(values)
    return tuple(sorted(value for value in set(selected) if selected.count(value) > 1))


__all__ = [
    "QUANTUM_CIRCUIT_DIALECT_ID",
    "QUANTUM_CIRCUIT_DIALECT_VERSION",
    "BoundCircuit",
    "Circuit",
    "CircuitArgument",
    "CircuitBindingError",
    "CircuitFragment",
    "CircuitInput",
    "CircuitResult",
    "Measurement",
    "Qubit",
    "RepeatCount",
    "SingleQubitGate",
    "bind_circuit",
    "circuit",
    "circuit_domain_call",
    "circuit_domain_program",
    "measure",
    "parallel",
    "qubit",
    "repeat",
    "scalar_input",
    "sequence",
    "single_qubit_gate",
]
