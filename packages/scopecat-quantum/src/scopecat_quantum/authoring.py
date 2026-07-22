"""Opaque authoring handles for unified logical and physical programs.

Gate, measurement, and pulse statements share one composition, binding, and
domain-integration surface. Pure logical programs remain a verified subset and
project to Circuit IR internally when calibration or target passes require it.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from collections.abc import Sequence as SequenceCollection
from dataclasses import dataclass, replace
from typing import (
    Annotated,
    Literal,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
    override,
)

from scopecat import Quantity
from scopecat.authoring import (
    ComputeInput,
    DomainExecution,
    DomainProgramDef,
    EntityType,
    FloatType,
    IntType,
    ModuleBuilder,
    ModuleInvocation,
    ProductOutputs,
    ProductRef,
    QuantityType,
    ScalarType,
    shot_axis,
)
from scopecat.authoring import (
    domain_execution as _core_domain_execution,
)
from scopecat.authoring import (
    domain_program as _core_domain_program,
)
from scopecat.authoring import input as core_input
from scopecat.authoring.value_types import (
    Bool as BoolType,
)
from scopecat.authoring.value_types import (
    Entity as EntityAtomType,
)
from scopecat.authoring.value_types import (
    Float as FloatAtomType,
)
from scopecat.authoring.value_types import (
    Payload as PayloadType,
)
from scopecat.authoring.value_types import (
    Quantity as QuantityAtomType,
)
from scopecat.authoring.value_types import (
    Record as RecordType,
)
from scopecat.authoring.value_types import (
    String as StringType,
)
from scopecat.authoring.value_types import ValueValidationError, coerce_literal
from scopecat.records.entity import EntityRef

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    CouplerId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import CircuitNode, Measure
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
from scopecat_quantum.programs import (
    ImplementedGate,
    PulseBlock,
    QuantumNode,
    QuantumProgramIR,
    VerifiedQuantumProgram,
    verify_quantum_program,
)
from scopecat_quantum.programs import Parallel as IrQuantumParallel
from scopecat_quantum.programs import Sequence as IrQuantumSequence
from scopecat_quantum.pulses import (
    DRAG,
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    AnalyticEnvelope,
    Barrier,
    Constant,
    Delay,
    DriveSignal,
    FluxSignal,
    FrameSignal,
    Gaussian,
    LogicalSignal,
    Play,
    PlaySignal,
    PulseInstruction,
    PulseProgram,
    ReadoutSignal,
    ShiftPhase,
)
from scopecat_quantum.pulses import Parallel as IrPulseParallel
from scopecat_quantum.pulses import Sequence as IrPulseSequence


@dataclass(frozen=True, slots=True, repr=False)
class Qubit:
    """A logical qubit handle, independent of physical target wiring."""

    ir_id: QubitId

    @property
    def id(self) -> str:
        """Return the logical qubit port identity."""

        return self.ir_id.value


@dataclass(frozen=True, slots=True, repr=False)
class Coupler:
    """A logical coupler handle, independent of physical target wiring."""

    ir_id: CouplerId

    @property
    def id(self) -> str:
        """Return the logical coupler port identity."""

        return self.ir_id.value


@dataclass(frozen=True, slots=True, repr=False)
class QuantumInput:
    """One core-typed scalar input consumed by a mixed quantum program."""

    _id: str
    value_type: ScalarType

    @property
    def id(self) -> str:
        """Return the stable input-port identity."""

        return self._id


@dataclass(frozen=True, slots=True, repr=False)
class CircuitInput:
    """One typed scalar input consumed by a symbolic circuit."""

    _id: str
    kind: GateParameterKind

    @property
    def id(self) -> str:
        """Return the stable input-port identity."""

        return self._id


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class MeasurementResult:
    """One typed result produced by logical measurement or pulse acquisition."""

    _id: str
    _qubit: Qubit
    acquisition_kind: AcquisitionKind

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


@dataclass(frozen=True, slots=True, repr=False)
class ProgramResults(Sequence[MeasurementResult]):
    """Source-ordered quantum results with stable name lookup."""

    _values: tuple[MeasurementResult, ...]

    @overload
    def __getitem__(self, index: int) -> MeasurementResult: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[MeasurementResult, ...]: ...

    @overload
    def __getitem__(self, index: str) -> MeasurementResult: ...

    @override
    def __getitem__(
        self,
        index: int | slice | str,
    ) -> MeasurementResult | tuple[MeasurementResult, ...]:
        if isinstance(index, str):
            for result in self._values:
                if result.id == index:
                    return result
            raise KeyError(index)
        return self._values[index]

    @override
    def __len__(self) -> int:
        return len(self._values)

    @override
    def __iter__(self) -> Iterator[MeasurementResult]:
        return iter(self._values)

    def __getattr__(self, result_id: str) -> MeasurementResult:
        try:
            return self[result_id]
        except KeyError:
            msg = f"quantum program has no result {result_id!r}"
            raise AttributeError(msg) from None

    @override
    def __dir__(self) -> list[str]:
        return sorted((*super().__dir__(), *(result.id for result in self._values)))


@dataclass(frozen=True, slots=True, repr=False)
class QuantumProgramCall:
    """One program invocation with automatically owned result products."""

    program: Program
    module_invocation: ModuleInvocation
    results: ProductOutputs


class QuantumFragment:
    """Opaque base type accepted by unified quantum composition factories."""

    __slots__ = ()

    def __init__(self) -> None:
        raise TypeError(
            "QuantumFragment has no standalone state; construct a concrete fragment"
        )


class CircuitFragment(QuantumFragment):
    """Opaque logical-only fragment that can be closed as a circuit."""

    __slots__ = ()


class PulseFragment(QuantumFragment):
    """Opaque pulse statement that composes beside gates and measurements."""

    __slots__ = ()


type CircuitArgument = GateArgumentValue | CircuitInput
type QuantumQuantity = Quantity | QuantumInput
type ProgramInput = CircuitInput | QuantumInput
type ProgramPort = PulseElement | ProgramInput
type ProgramFunction = Callable[..., QuantumFragment]
type ElementBindings = Mapping[QubitId | CouplerId, QubitId | CouplerId]

_SHOTS_INPUT_ID = "__shots__"
_RESERVED_PROGRAM_PORT_IDS = frozenset({_SHOTS_INPUT_ID, "shots"})
_RESERVED_RESULT_IDS = frozenset({"count", "index"})
type RepeatCount = int | CircuitInput | QuantumInput
type PulseTemplateArgument = Quantity | int | float | QuantumInput
type PulseElement = Qubit | Coupler
type Gate = SingleQubitGate | TwoQubitGate

QUANTUM_PROGRAM_DIALECT_ID = "scopecat.quantum.program"
QUANTUM_PROGRAM_DIALECT_VERSION = "2"


@dataclass(frozen=True, slots=True, repr=False)
class SingleQubitGate:
    """A reusable symbolic gate with exactly one logical-qubit operand."""

    definition: GateDefinition

    @property
    def id(self) -> str:
        """Return the gate semantic identity."""

        return self.definition.id.value

    @property
    def parameters(self) -> tuple[GateParameterDefinition, ...]:
        """Return the ordered scalar parameter contract."""

        return self.definition.parameters

    def __call__(
        self,
        qubit: Qubit,
        /,
        **arguments: CircuitArgument,
    ) -> CircuitFragment:
        """Author one occurrence of this gate on ``qubit``."""

        return _author_gate_call(self, (qubit,), arguments)


@dataclass(frozen=True, slots=True, repr=False)
class TwoQubitGate:
    """A reusable symbolic gate with exactly two logical-qubit operands."""

    definition: GateDefinition

    @property
    def id(self) -> str:
        """Return the gate semantic identity."""

        return self.definition.id.value

    @property
    def parameters(self) -> tuple[GateParameterDefinition, ...]:
        """Return the ordered scalar parameter contract."""

        return self.definition.parameters

    def __call__(
        self,
        first: Qubit,
        second: Qubit,
        /,
        **arguments: CircuitArgument,
    ) -> CircuitFragment:
        """Author one occurrence of this gate on two ordered qubits."""

        return _author_gate_call(self, (first, second), arguments)


def _author_gate_call(
    gate_handle: Gate,
    qubits: tuple[Qubit, ...],
    arguments: Mapping[str, CircuitArgument],
) -> CircuitFragment:
    definition = gate_handle.definition
    if len(qubits) != definition.qubit_arity:
        msg = (
            f"gate {gate_handle.id!r} requires {definition.qubit_arity} qubits, "
            f"got {len(qubits)}"
        )
        raise ValueError(msg)
    qubit_ids = tuple(qubit.ir_id for qubit in qubits)
    if len(set(qubit_ids)) != len(qubit_ids):
        msg = f"gate {gate_handle.id!r} operands must be unique"
        raise ValueError(msg)

    expected = {parameter.id: parameter for parameter in gate_handle.parameters}
    supplied = set(arguments)
    missing = sorted(set(expected) - supplied)
    unknown = sorted(supplied - set(expected))
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        msg = f"gate {gate_handle.id!r} arguments are invalid: " + "; ".join(details)
        raise ValueError(msg)
    ordered_arguments: list[tuple[str, CircuitArgument]] = []
    for parameter in gate_handle.parameters:
        value = arguments[parameter.id]
        if isinstance(value, CircuitInput):
            if value.kind is not parameter.kind:
                msg = (
                    f"gate {gate_handle.id!r} parameter {parameter.id!r} requires "
                    f"{parameter.kind.value!r}, but input {value.id!r} declares "
                    f"{value.kind.value!r}"
                )
                raise TypeError(msg)
        elif not _argument_matches_kind(value, parameter.kind):
            msg = (
                f"gate {gate_handle.id!r} parameter {parameter.id!r} requires "
                f"{parameter.kind.value!r}"
            )
            raise TypeError(msg)
        ordered_arguments.append((parameter.id, value))
    return _GateFragment(
        gate=gate_handle,
        qubits=qubits,
        arguments=tuple(ordered_arguments),
    )


@dataclass(frozen=True, slots=True, repr=False)
class Measurement(CircuitFragment):
    """A measurement statement and its first-class acquisition result."""

    result: MeasurementResult


@dataclass(frozen=True, slots=True, repr=False)
class PulseEnvelope:
    """A symbolic analytic envelope whose quantities bind with the program."""

    kind: str
    duration: QuantumQuantity
    amplitude: QuantumQuantity
    sigma: QuantumQuantity | None
    beta: QuantumQuantity | None
    phase: QuantumQuantity


@dataclass(frozen=True, slots=True, repr=False)
class Acquisition(PulseFragment):
    """A physical acquisition statement and its first-class result port."""

    signal: AcquireSignal
    duration: QuantumQuantity
    result: MeasurementResult


@dataclass(frozen=True, slots=True, repr=False)
class PulseTemplate:
    """A reusable, result-free pulse fragment with typed formal ports."""

    ir_id: PulseProgramId
    body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[QuantumInput, ...]

    @property
    def id(self) -> str:
        """Return the stable pulse-template identity."""

        return self.ir_id.value

    def __call__(
        self,
        *elements: PulseElement,
        **inputs: PulseTemplateArgument,
    ) -> PulseFragment:
        """Instantiate this template over logical elements and typed values."""

        return _instantiate_pulse_template(self, elements, inputs)


@dataclass(frozen=True, slots=True)
class _GateFragment(CircuitFragment):
    gate: Gate
    qubits: tuple[Qubit, ...]
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
    count: int | CircuitInput


@dataclass(frozen=True, slots=True)
class _PlayFragment(PulseFragment):
    signal: PlaySignal
    envelope: PulseEnvelope | AnalyticEnvelope


@dataclass(frozen=True, slots=True)
class _DelayFragment(PulseFragment):
    signal: PlaySignal
    duration: QuantumQuantity


@dataclass(frozen=True, slots=True)
class _BarrierFragment(PulseFragment):
    signals: tuple[PlaySignal, ...]


@dataclass(frozen=True, slots=True)
class _ShiftPhaseFragment(PulseFragment):
    signal: FrameSignal
    phase: QuantumQuantity


@dataclass(frozen=True, slots=True)
class _PulseTemplateCallFragment(PulseFragment):
    template: PulseTemplate
    body: QuantumFragment


@dataclass(frozen=True, slots=True)
class _QuantumSequenceFragment(QuantumFragment):
    operations: tuple[QuantumFragment, ...]


@dataclass(frozen=True, slots=True)
class _QuantumParallelFragment(QuantumFragment):
    branches: tuple[QuantumFragment, ...]


@dataclass(frozen=True, slots=True)
class _QuantumRepeatFragment(QuantumFragment):
    operation: QuantumFragment
    count: RepeatCount


@dataclass(frozen=True, slots=True)
class _ImplementedGateFragment(QuantumFragment):
    gate: _GateFragment
    pulse: QuantumFragment
    candidate_id: str | None


@dataclass(frozen=True, slots=True, repr=False)
class Program:
    """A closed symbolic program containing logical and physical statements."""

    ir_id: QuantumProgramId
    body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[ProgramInput, ...]
    results: ProgramResults
    _gate_definitions: tuple[GateDefinition, ...]
    description: str | None = None

    @property
    def id(self) -> str:
        """Return the stable program identity."""

        return self.ir_id.value

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the exact logical gate catalog captured by this declaration."""

        return self._gate_definitions

    @property
    def ports(self) -> tuple[ProgramPort, ...]:
        """Return bindable logical elements followed by scalar inputs."""

        return (*self.elements, *self.inputs)

    def __call__(
        self,
        *,
        shots: ComputeInput = 1,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Create the ordinary single call of this closed program."""

        return _program_call(
            self,
            self.id.rsplit(".", maxsplit=1)[-1],
            inputs=inputs,
            shots=shots,
        )

    def call(
        self,
        instance_id: str,
        /,
        *,
        shots: ComputeInput = 1,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Create an explicitly named call for repeated composition."""

        return _program_call(
            self,
            instance_id,
            inputs=inputs,
            shots=shots,
        )


class ProgramDefinition(Program):
    """A function-authored program with an inspectable call signature."""

    __slots__ = ("_definition",)

    _definition: ProgramFunction

    def __init__(self, declaration: Program, definition: ProgramFunction) -> None:
        super().__init__(
            ir_id=declaration.ir_id,
            body=declaration.body,
            elements=declaration.elements,
            inputs=declaration.inputs,
            results=declaration.results,
            _gate_definitions=declaration.gate_definitions,
            description=declaration.description,
        )
        self._definition = definition

    @property
    def __wrapped__(self) -> ProgramFunction:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        source = inspect.signature(self._definition)
        parameters = tuple(
            parameter.replace(annotation=ComputeInput)
            for parameter in source.parameters.values()
        )
        shots = inspect.Parameter(
            "shots",
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=1,
            annotation=ComputeInput,
        )
        return source.replace(
            parameters=(*parameters, shots),
            return_annotation=QuantumProgramCall,
        )

    @override
    def __call__(
        self,
        *args: ComputeInput,
        shots: ComputeInput = 1,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind ports in their declared Python order."""

        bound = inspect.signature(self._definition).bind(*args, **inputs)
        return _program_call(
            self,
            self.id.rsplit(".", maxsplit=1)[-1],
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            shots=shots,
        )

    @override
    def call(
        self,
        instance_id: str,
        /,
        *args: ComputeInput,
        shots: ComputeInput = 1,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind an explicitly named call in declared port order."""

        bound = inspect.signature(self._definition).bind(*args, **inputs)
        return _program_call(
            self,
            instance_id,
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            shots=shots,
        )


@dataclass(frozen=True, slots=True, repr=False)
class BoundProgram:
    """A declaration bound to concrete values and verified source IR."""

    declaration: Program
    verified: VerifiedQuantumProgram

    @property
    def program(self) -> QuantumProgramIR:
        """Return the concrete unified IR accepted by pulse refinement."""

        return self.verified.program

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the verified logical gate catalog."""

        return self.verified.gate_definitions

    @property
    def results(self) -> ProgramResults:
        """Return declared measurement and acquisition results in source order."""

        return self.declaration.results


class ProgramBindingError(ValueError):
    """Raised when concrete bindings cannot close a symbolic program."""


def _element_ir_id(value: PulseElement) -> QubitId | CouplerId:
    return value.ir_id


def _pulse_envelope_parts(
    value: PulseEnvelope,
) -> tuple[
    str,
    QuantumQuantity,
    QuantumQuantity,
    QuantumQuantity | None,
    QuantumQuantity | None,
    QuantumQuantity,
]:
    return (
        value.kind,
        value.duration,
        value.amplitude,
        value.sigma,
        value.beta,
        value.phase,
    )


def qubit(id: str) -> Qubit:  # noqa: A002
    """Declare one logical qubit handle."""

    return Qubit(ir_id=QubitId(id))


def coupler(id: str) -> Coupler:  # noqa: A002
    """Declare one logical coupler handle."""

    return Coupler(ir_id=CouplerId(id))


def scalar_input(id: str, kind: GateParameterKind) -> CircuitInput:  # noqa: A002
    """Declare one typed scalar input port for a symbolic circuit."""

    if not id.strip():
        msg = "circuit input id must be a non-empty string"
        raise ValueError(msg)
    return CircuitInput(_id=id, kind=kind)


def input(id: str, value_type: ScalarType) -> QuantumInput:  # noqa: A001, A002
    """Declare one core-typed scalar input for gate-and-pulse authoring."""

    if not id.strip():
        msg = "quantum input id must be a non-empty string"
        raise ValueError(msg)
    if value_type.nullable:
        msg = "quantum program inputs cannot be nullable"
        raise ValueError(msg)
    return QuantumInput(
        _id=id,
        value_type=value_type,
    )


def single_qubit_gate(
    id: str,  # noqa: A002
    *,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> SingleQubitGate:
    """Declare one hardware-independent single-qubit gate semantic."""

    selected = gate(id, arity=1, parameters=parameters)
    assert isinstance(selected, SingleQubitGate)  # noqa: S101
    return selected


def two_qubit_gate(
    id: str,  # noqa: A002
    *,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> TwoQubitGate:
    """Declare one hardware-independent two-qubit gate semantic."""

    selected = gate(id, arity=2, parameters=parameters)
    assert isinstance(selected, TwoQubitGate)  # noqa: S101
    return selected


@overload
def gate(
    id: str,
    *,
    arity: Literal[1],
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> SingleQubitGate: ...


@overload
def gate(
    id: str,
    *,
    arity: Literal[2],
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> TwoQubitGate: ...


def gate(
    id: str,  # noqa: A002
    *,
    arity: Literal[1, 2],
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> Gate:
    """Declare one hardware-independent one- or two-qubit gate semantic."""

    selected: Mapping[str, GateParameterKind] = {} if parameters is None else parameters
    if any(not name.strip() for name in selected):
        msg = "gate parameter ids must be non-empty strings"
        raise ValueError(msg)
    definition = GateDefinition(
        id=GateId(id),
        qubit_arity=arity,
        parameters=tuple(
            GateParameterDefinition(name, kind) for name, kind in selected.items()
        ),
    )
    handle_type = SingleQubitGate if arity == 1 else TwoQubitGate
    return handle_type(definition=definition)


def measure(
    qubit: Qubit,
    /,
    *,
    result: str,
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
) -> Measurement:
    """Author one single-qubit measurement and its result port."""

    if not result.strip():
        msg = "measurement result id must be a non-empty string"
        raise ValueError(msg)
    result_handle = MeasurementResult(
        _id=result,
        _qubit=qubit,
        acquisition_kind=acquisition_kind,
    )
    return Measurement(result=result_handle)


def acquire(
    qubit: Qubit,
    /,
    *,
    duration: QuantumQuantity,
    result: str,
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
) -> Acquisition:
    """Acquire one physical signal and expose its typed result port."""

    _require_quantity_expression(duration, field="duration", kind="time")
    if not result.strip():
        msg = "acquisition result id must be a non-empty string"
        raise ValueError(msg)
    result_handle = MeasurementResult(
        _id=result,
        _qubit=qubit,
        acquisition_kind=acquisition_kind,
    )
    return Acquisition(
        signal=AcquireSignal(qubit.ir_id),
        duration=duration,
        result=result_handle,
    )


def drive(qubit: Qubit, /) -> DriveSignal:
    """Select the logical drive signal for one authored qubit."""

    return DriveSignal(qubit.ir_id)


def flux(element: PulseElement, /) -> FluxSignal:
    """Select the logical flux signal for one authored qubit or coupler."""

    return FluxSignal(_element_ir_id(element))


def readout(qubit: Qubit, /) -> ReadoutSignal:
    """Select the logical readout-stimulus signal for one authored qubit."""

    return ReadoutSignal(qubit.ir_id)


def shift_phase(signal: FrameSignal, phase: QuantumQuantity, /) -> PulseFragment:
    """Advance a drive or readout frame without consuming timeline duration."""

    _require_quantity_expression(phase, field="phase shift", kind="phase")
    return _ShiftPhaseFragment(
        signal=signal,
        phase=phase,
    )


def pulse_template(
    id: str,  # noqa: A002
    body: QuantumFragment,
    /,
    *,
    elements: SequenceCollection[PulseElement],
) -> PulseTemplate:
    """Close a result-free symbolic pulse fragment as a reusable template."""

    facts = _summarize_fragment(body)
    if not facts.pulse_only:
        msg = "pulse_template body must contain only pulse statements"
        raise TypeError(msg)
    if facts.results:
        msg = "pulse templates cannot capture acquisition results"
        raise ValueError(msg)
    raw_elements = tuple(elements)
    element_ids = tuple(_element_ir_id(item) for item in raw_elements)
    if len(set(element_ids)) != len(element_ids):
        msg = "pulse template elements must be unique"
        raise ValueError(msg)

    inputs_by_id: dict[str, QuantumInput] = {}
    for input_handle in facts.inputs:
        if not isinstance(input_handle, QuantumInput):
            msg = "pulse templates require QuantumInput rather than CircuitInput ports"
            raise TypeError(msg)
        existing = inputs_by_id.get(input_handle.id)
        if existing is not None and existing is not input_handle:
            msg = (
                f"pulse template input {input_handle.id!r} is declared by multiple "
                "distinct handles"
            )
            raise ValueError(msg)
        inputs_by_id.setdefault(input_handle.id, input_handle)

    formal_ids = set(element_ids)
    foreign_owners = {owner for owner in facts.pulse_owners if owner not in formal_ids}
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"pulse template contains undeclared formal elements: {rendered}"
        raise ValueError(msg)

    return PulseTemplate(
        ir_id=PulseProgramId(id),
        body=body,
        elements=raw_elements,
        inputs=tuple(inputs_by_id.values()),
    )


def constant(
    *,
    duration: QuantumQuantity,
    amplitude: QuantumQuantity,
    phase: QuantumQuantity | None = None,
) -> PulseEnvelope:
    """Author a constant analytic envelope with bindable quantities."""

    return _pulse_envelope(
        "constant",
        duration=duration,
        amplitude=amplitude,
        phase=phase,
    )


def gaussian(
    *,
    duration: QuantumQuantity,
    amplitude: QuantumQuantity,
    sigma: QuantumQuantity,
    phase: QuantumQuantity | None = None,
) -> PulseEnvelope:
    """Author a truncated Gaussian envelope with bindable quantities."""

    return _pulse_envelope(
        "gaussian",
        duration=duration,
        amplitude=amplitude,
        sigma=sigma,
        phase=phase,
    )


def drag(
    *,
    duration: QuantumQuantity,
    amplitude: QuantumQuantity,
    sigma: QuantumQuantity,
    beta: QuantumQuantity,
    phase: QuantumQuantity | None = None,
) -> PulseEnvelope:
    """Author a DRAG envelope with a bindable derivative coefficient."""

    return _pulse_envelope(
        "drag",
        duration=duration,
        amplitude=amplitude,
        sigma=sigma,
        beta=beta,
        phase=phase,
    )


def play(
    signal: PlaySignal,
    envelope: PulseEnvelope | AnalyticEnvelope,
    /,
) -> PulseFragment:
    """Play one concrete or symbolic envelope on a logical signal."""

    return _PlayFragment(
        signal=signal,
        envelope=envelope,
    )


def delay(signal: PlaySignal, duration: QuantumQuantity, /) -> PulseFragment:
    """Reserve time on one logical signal."""

    _require_quantity_expression(duration, field="duration", kind="time")
    return _DelayFragment(signal=signal, duration=duration)


def barrier(*signals: PlaySignal) -> PulseFragment:
    """Synchronize one or more logical signals without advancing time."""

    if not signals:
        msg = "barrier requires at least one logical signal"
        raise ValueError(msg)
    return _BarrierFragment(signals=signals)


def implements(
    gate_call: CircuitFragment,
    pulse: QuantumFragment,
    /,
    *,
    resources: SequenceCollection[Coupler] = (),
    candidate: str | None = None,
) -> QuantumFragment:
    """Attach one explicit pulse implementation to a logical gate occurrence."""

    if not isinstance(gate_call, _GateFragment):
        msg = "implements requires one authored gate call"
        raise TypeError(msg)
    facts = _summarize_fragment(pulse)
    if not facts.pulse_only:
        msg = "implements pulse must contain only pulse statements"
        raise TypeError(msg)
    if facts.results:
        msg = "implements pulse cannot acquire results"
        raise ValueError(msg)
    selected_resources = tuple(resources)
    resource_ids = tuple(resource.ir_id for resource in selected_resources)
    if len(set(resource_ids)) != len(resource_ids):
        msg = "implements resources must be unique"
        raise ValueError(msg)
    operand_ids = {qubit.ir_id for qubit in gate_call.qubits}
    allowed_owners = {*operand_ids, *resource_ids}
    pulse_owners = set(facts.pulse_owners)
    foreign_owners = pulse_owners - allowed_owners
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"implements pulse contains unauthorized signal owners: {rendered}"
        raise ValueError(msg)
    used_resources = {owner for owner in pulse_owners if isinstance(owner, CouplerId)}
    unused_resources = set(resource_ids) - used_resources
    if unused_resources:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(unused_resources, key=lambda item: item.value)
        )
        msg = f"implements declares unused coupler resources: {rendered}"
        raise ValueError(msg)
    if candidate is not None and not candidate.strip():
        msg = "implements candidate must be a non-empty string"
        raise ValueError(msg)
    return _ImplementedGateFragment(
        gate=gate_call,
        pulse=pulse,
        candidate_id=candidate,
    )


@overload
def sequence(*operations: CircuitFragment) -> CircuitFragment: ...


@overload
def sequence(*operations: QuantumFragment) -> QuantumFragment: ...


def sequence(*operations: QuantumFragment) -> QuantumFragment:
    """Compose gate, measurement, and pulse fragments in order."""

    if not operations:
        msg = "sequence requires at least one quantum fragment"
        raise ValueError(msg)
    if all(isinstance(operation, CircuitFragment) for operation in operations):
        return _SequenceFragment(
            operations=cast("tuple[CircuitFragment, ...]", operations),
        )
    return _QuantumSequenceFragment(operations=operations)


@overload
def parallel(*branches: CircuitFragment) -> CircuitFragment: ...


@overload
def parallel(*branches: QuantumFragment) -> QuantumFragment: ...


def parallel(*branches: QuantumFragment) -> QuantumFragment:
    """Compose two or more gate, measurement, or pulse branches concurrently."""

    if len(branches) < 2:
        msg = "parallel requires at least two quantum branches"
        raise ValueError(msg)
    if all(isinstance(branch, CircuitFragment) for branch in branches):
        return _ParallelFragment(
            branches=cast("tuple[CircuitFragment, ...]", branches),
        )
    return _QuantumParallelFragment(branches=branches)


@overload
def repeat(
    operation: CircuitFragment,
    count: int | CircuitInput,
) -> CircuitFragment: ...


@overload
def repeat(operation: QuantumFragment, count: RepeatCount) -> QuantumFragment: ...


def repeat(operation: QuantumFragment, count: RepeatCount) -> QuantumFragment:
    """Repeat a result-free fragment a literal or symbolic number of times.

    A zero count lowers to an empty sequence.  Measurements are deliberately
    excluded because a single result handle cannot represent repeated slots.
    """

    if _summarize_fragment(operation).results:
        msg = (
            "repeat does not support fragments that produce measurement results "
            "or physical acquisition results"
        )
        raise ValueError(msg)
    if isinstance(count, CircuitInput | QuantumInput):
        if not _is_integer_input(count):
            msg = "repeat count inputs must have integer kind"
            raise TypeError(msg)
    elif isinstance(count, bool) or count < 0:
        msg = "repeat count must be a non-negative integer or integer input"
        raise ValueError(msg)
    if isinstance(operation, CircuitFragment) and isinstance(count, int | CircuitInput):
        return _RepeatFragment(
            operation=operation,
            count=count,
        )
    return _QuantumRepeatFragment(
        operation=operation,
        count=count,
    )


@overload
def program(
    definition: ProgramFunction,
    /,
    *,
    id: str | None = None,
) -> ProgramDefinition: ...


@overload
def program(
    definition: None = None,
    /,
    *,
    id: str | None = None,
) -> Callable[[ProgramFunction], ProgramDefinition]: ...


def program(
    definition: ProgramFunction | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
) -> ProgramDefinition | Callable[[ProgramFunction], ProgramDefinition]:
    """Define a quantum program from a symbolic Python function."""

    def decorate(fn: ProgramFunction) -> ProgramDefinition:
        return _program_from_function(fn, id=id)

    return decorate(definition) if definition is not None else decorate


def _close_program(
    id: str,  # noqa: A002
    body: QuantumFragment,
    *,
    elements: SequenceCollection[PulseElement] = (),
    description: str | None = None,
) -> Program:
    ir_id = QuantumProgramId(id)
    facts = _summarize_fragment(body)
    formal_elements = tuple(elements)
    element_ids = tuple(element.id for element in formal_elements)
    if len(element_ids) != len(set(element_ids)):
        raise ValueError("quantum program element ids must be unique")
    used_elements = {(type(element), element.id) for element in facts.element_uses}
    unused_elements = tuple(
        element.id
        for element in formal_elements
        if (type(element), element.id) not in used_elements
    )
    if unused_elements:
        rendered = ", ".join(repr(item) for item in unused_elements)
        raise ValueError(f"quantum program has unused formal elements: {rendered}")
    collected_inputs = facts.inputs
    inputs_by_id: dict[str, ProgramInput] = {}
    contracts_by_id: dict[str, ScalarType] = {}
    repeat_input_ids = {input_handle.id for input_handle in facts.repeat_inputs}
    for input_handle in collected_inputs:
        existing_handle = inputs_by_id.get(input_handle.id)
        if existing_handle is not None and existing_handle is not input_handle:
            msg = (
                f"quantum input {input_handle.id!r} is declared by multiple "
                "distinct handles"
            )
            raise ValueError(msg)
        contract = _program_input_type(
            input_handle,
            non_negative=input_handle.id in repeat_input_ids,
        )
        existing_contract = contracts_by_id.get(input_handle.id)
        if existing_contract is not None and existing_contract != contract:
            msg = f"quantum input {input_handle.id!r} has conflicting value types"
            raise ValueError(msg)
        inputs_by_id.setdefault(input_handle.id, input_handle)
        contracts_by_id.setdefault(input_handle.id, contract)

    conflicting_ports = sorted(set(element_ids) & set(inputs_by_id))
    if conflicting_ports:
        rendered = ", ".join(repr(item) for item in conflicting_ports)
        raise ValueError(f"quantum program has conflicting port ids: {rendered}")
    reserved_ports = sorted(
        (set(element_ids) | set(inputs_by_id)) & _RESERVED_PROGRAM_PORT_IDS
    )
    if reserved_ports:
        rendered = ", ".join(repr(item) for item in reserved_ports)
        raise ValueError(f"quantum program uses reserved port ids: {rendered}")

    results = facts.results
    duplicate_results = _duplicates(result.id for result in results)
    if duplicate_results:
        rendered = ", ".join(repr(item) for item in duplicate_results)
        msg = f"quantum program has duplicate result ids: {rendered}"
        raise ValueError(msg)
    reserved_results = sorted({result.id for result in results} & _RESERVED_RESULT_IDS)
    if reserved_results:
        rendered = ", ".join(repr(item) for item in reserved_results)
        raise ValueError(f"quantum program uses reserved result ids: {rendered}")

    definitions_by_id: dict[str, GateDefinition] = {}
    for definition in facts.gate_definitions:
        existing = definitions_by_id.get(definition.id.value)
        if existing is not None and existing != definition:
            msg = (
                f"quantum program gate {definition.id.value!r} has "
                "conflicting definitions"
            )
            raise ValueError(msg)
        definitions_by_id.setdefault(definition.id.value, definition)

    return Program(
        ir_id=ir_id,
        body=body,
        elements=formal_elements,
        inputs=tuple(inputs_by_id.values()),
        results=ProgramResults(results),
        _gate_definitions=tuple(definitions_by_id.values()),
        description=description,
    )


def _program_from_function(
    fn: ProgramFunction,
    *,
    id: str | None,  # noqa: A002
) -> ProgramDefinition:
    signature = inspect.signature(fn)
    hints = cast("Mapping[str, object]", get_type_hints(fn, include_extras=True))
    arguments: dict[str, PulseElement | ProgramInput] = {}
    elements: list[PulseElement] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TypeError("quantum program functions require named parameters")
        if cast("object", parameter.default) is not inspect.Parameter.empty:
            raise TypeError("quantum program ports cannot declare Python defaults")
        annotation = hints.get(
            parameter.name,
            cast("object", parameter.annotation),
        )
        argument = _program_function_argument(parameter.name, annotation)
        arguments[parameter.name] = argument
        if isinstance(argument, Qubit | Coupler):
            elements.append(argument)
    result = fn(**arguments)
    declaration = _close_program(
        id or f"{fn.__module__}.{fn.__qualname__}",
        result,
        elements=elements,
        description=inspect.getdoc(fn),
    )
    formal_inputs = tuple(
        argument
        for argument in arguments.values()
        if isinstance(argument, CircuitInput | QuantumInput)
    )
    unused_inputs = tuple(
        name
        for name, argument in arguments.items()
        if isinstance(argument, CircuitInput | QuantumInput)
        and all(argument is not used for used in declaration.inputs)
    )
    if unused_inputs:
        rendered = ", ".join(repr(name) for name in unused_inputs)
        raise ValueError(f"quantum program has unused scalar ports: {rendered}")
    return ProgramDefinition(
        replace(declaration, inputs=formal_inputs),
        fn,
    )


def bind(
    declaration: Program,
    bindings: Mapping[str, object] | None = None,
) -> BoundProgram:
    """Bind all inputs and return verified unified quantum IR."""

    selected_bindings: Mapping[str, object] = {} if bindings is None else bindings
    expected = {port.id for port in declaration.ports}
    supplied = set(selected_bindings)
    missing = sorted(expected - supplied)
    unknown = sorted(supplied - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        raise ProgramBindingError("invalid program bindings: " + "; ".join(details))

    repeat_input_ids = {
        input_handle.id
        for input_handle in _summarize_fragment(declaration.body).repeat_inputs
    }
    concrete_bindings: dict[str, object] = {}
    element_bindings: dict[QubitId | CouplerId, QubitId | CouplerId] = {}
    for element in declaration.elements:
        value_type = program_port_type(element)
        try:
            selected = coerce_literal(
                value_type,
                selected_bindings[element.id],
                path=("bindings", element.id),
            )
        except ValueValidationError as error:
            raise ProgramBindingError(str(error)) from error
        if not isinstance(selected, EntityRef):
            raise AssertionError("entity program ports normalize to EntityRef")
        concrete_bindings[element.id] = selected
        element_bindings[element.ir_id] = (
            QubitId(selected.id)
            if isinstance(element, Qubit)
            else CouplerId(selected.id)
        )
    for input_handle in declaration.inputs:
        value_type = _program_input_type(
            input_handle,
            non_negative=input_handle.id in repeat_input_ids,
        )
        try:
            concrete_bindings[input_handle.id] = coerce_literal(
                value_type,
                selected_bindings[input_handle.id],
                path=("bindings", input_handle.id),
            )
        except ValueValidationError as error:
            raise ProgramBindingError(str(error)) from error

    concrete = QuantumProgramIR(
        id=declaration.ir_id,
        body=_bind_quantum_fragment(
            declaration.body,
            concrete_bindings,
            element_bindings=element_bindings,
            path=("body",),
        ),
    )
    verified = verify_quantum_program(concrete, declaration.gate_definitions)
    return BoundProgram(
        declaration=declaration,
        verified=verified,
    )


def _domain_program(declaration: Program) -> DomainProgramDef:
    """Project a unified declaration into core's domain program seam."""

    repeat_input_ids = {
        input_handle.id
        for input_handle in _summarize_fragment(declaration.body).repeat_inputs
    }
    return _core_domain_program(
        declaration.id,
        dialect_id=QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=QUANTUM_PROGRAM_DIALECT_VERSION,
        body=declaration,
        inputs={
            port.id: program_port_type(
                port,
                non_negative=port.id in repeat_input_ids,
            )
            for port in declaration.ports
        },
        results={result.id: result for result in declaration.results},
    )


def _domain_execution(
    program: DomainProgramDef,
    *,
    id: str | None = None,  # noqa: A002
    inputs: Mapping[ProgramPort, ComputeInput] | None = None,
    results: Mapping[MeasurementResult, ProductRef] | None = None,
) -> DomainExecution:
    """Bind one template's quantum program to core values and products."""

    if (
        program.dialect_id != QUANTUM_PROGRAM_DIALECT_ID
        or program.dialect_version != QUANTUM_PROGRAM_DIALECT_VERSION
        or not isinstance(program.body, Program)
    ):
        msg = "quantum domain execution requires a quantum program"
        raise TypeError(msg)
    declaration = program.body
    expected_program = _domain_program(declaration)
    if (
        program.id != expected_program.id
        or program.input_ports != expected_program.input_ports
        or program.result_ports != expected_program.result_ports
    ):
        msg = "quantum program domain ports do not match its Program body"
        raise ValueError(msg)
    selected_inputs: Mapping[ProgramPort, ComputeInput] = (
        {} if inputs is None else inputs
    )
    selected_results: Mapping[MeasurementResult, ProductRef] = (
        {} if results is None else results
    )
    if set(selected_inputs) != set(declaration.ports):
        msg = "quantum domain execution inputs must bind every declared port"
        raise ValueError(msg)
    if set(selected_results) != set(declaration.results):
        msg = "quantum domain execution results must bind every declared result"
        raise ValueError(msg)
    normalized_inputs = {
        handle.id: (
            float(value)
            if isinstance(handle, CircuitInput)
            and handle.kind is GateParameterKind.NUMBER
            and isinstance(value, int)
            and not isinstance(value, bool)
            else value
        )
        for handle, value in selected_inputs.items()
    }
    return _core_domain_execution(
        program,
        id=id,
        inputs=normalized_inputs,
        results={handle.id: value for handle, value in selected_results.items()},
    )


def _program_call(
    program: Program,
    instance_id: str,
    /,
    *,
    inputs: Mapping[str, ComputeInput],
    shots: ComputeInput,
) -> QuantumProgramCall:
    """Lift one program use into a module-owned domain execution and products."""

    expected = {port.id for port in program.ports}
    supplied = set(inputs)
    missing = sorted(expected - supplied)
    unknown = sorted(supplied - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        raise ValueError("invalid quantum program call inputs: " + "; ".join(details))
    if _SHOTS_INPUT_ID in expected:
        raise ValueError(f"quantum program port {_SHOTS_INPUT_ID!r} is reserved")

    domain = _domain_program(program)
    local_inputs = {
        port.id: core_input(port.id, port.value_type) for port in domain.input_ports
    }
    shots_input = core_input(
        _SHOTS_INPUT_ID,
        ScalarType(IntType(minimum=1)),
    )
    builder = ModuleBuilder(id=f"{program.id}.call").inputs(
        *local_inputs.values(),
        shots_input,
    )
    for result in program.results:
        if result.acquisition_kind is not AcquisitionKind.INTEGRATED_IQ:
            raise NotImplementedError(
                "automatic program calls currently support integrated-IQ results"
            )
        builder = builder.product(
            result.id,
            unit="ratio",
            dtype="complex128",
            axes=(shot_axis(shots_input),),
        )
    execution = _domain_execution(
        domain,
        inputs={port: local_inputs[port.id] for port in program.ports},
        results={result: builder.products[result.id] for result in program.results},
    )
    module = builder.domain(execution).build()
    invocation = module.instantiate(
        instance_id,
        {
            **inputs,
            _SHOTS_INPUT_ID: shots,
        },
    )
    return QuantumProgramCall(
        program=program,
        module_invocation=invocation,
        results=ProductOutputs(
            {result.id: invocation.products[result.id] for result in program.results}
        ),
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
        return ScalarType(QuantityType(dimension="phase", unit="rad"))
    raise AssertionError(f"unsupported gate parameter kind {kind!r}")


def program_port_type(
    value: ProgramPort,
    *,
    non_negative: bool = False,
) -> ScalarType:
    """Return the core value contract for one quantum program port."""

    if isinstance(value, Qubit):
        return ScalarType(EntityType(entity_kind="logical_qubit"))
    if isinstance(value, Coupler):
        return ScalarType(EntityType(entity_kind="logical_coupler"))
    return _program_input_type(value, non_negative=non_negative)


def _bind_fragment(
    fragment: CircuitFragment,
    bindings: Mapping[str, GateArgumentValue],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
) -> CircuitNode:
    if isinstance(fragment, _GateFragment):
        return GateCall(
            id=CircuitOperationId(_operation_id(path, "gate")),
            gate_id=fragment.gate.definition.id,
            qubits=tuple(
                _bound_qubit_id(qubit, element_bindings) for qubit in fragment.qubits
            ),
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
            qubit=_bound_qubit_id(result.qubit, element_bindings),
            acquisition_slot_id=result.acquisition_slot_id,
            acquisition_kind=result.acquisition_kind,
        )
    if isinstance(fragment, _SequenceFragment):
        return IrSequence(
            tuple(
                _bind_fragment(
                    operation,
                    bindings,
                    element_bindings=element_bindings,
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
                    element_bindings=element_bindings,
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
        raise ProgramBindingError(msg)
    return IrSequence(
        tuple(
            _bind_fragment(
                fragment.operation,
                bindings,
                element_bindings=element_bindings,
                path=(*path, f"repeat[{index}]"),
            )
            for index in range(count)
        )
    )


def _bind_quantum_fragment(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
) -> QuantumNode:
    if isinstance(fragment, _GateFragment | Measurement):
        return cast(
            "GateCall | Measure",
            _bind_fragment(
                fragment,
                cast("Mapping[str, GateArgumentValue]", bindings),
                element_bindings=element_bindings,
                path=path,
            ),
        )
    if isinstance(fragment, _ImplementedGateFragment):
        call = _bind_fragment(
            fragment.gate,
            cast("Mapping[str, GateArgumentValue]", bindings),
            element_bindings=element_bindings,
            path=(*path, "logical"),
        )
        if not isinstance(call, GateCall):
            raise AssertionError("implemented gate binding must produce a GateCall")
        pulse_template_id = (
            fragment.pulse.template.ir_id
            if isinstance(fragment.pulse, _PulseTemplateCallFragment)
            else PulseProgramId(_operation_id(path, "implementation-template"))
        )
        pulse_body = (
            fragment.pulse.body
            if isinstance(fragment.pulse, _PulseTemplateCallFragment)
            else fragment.pulse
        )
        return ImplementedGate(
            call=call,
            pulse_template=PulseProgram(
                id=pulse_template_id,
                body=_bind_pulse_fragment(
                    pulse_body,
                    bindings,
                    element_bindings=element_bindings,
                    path=("implementation",),
                ),
            ),
            candidate_id=fragment.candidate_id,
        )
    if isinstance(fragment, Acquisition):
        slot_id = fragment.result.acquisition_slot_id
        bound_acquire = _bind_pulse_fragment(
            fragment,
            bindings,
            element_bindings=element_bindings,
            path=(),
        )
        if not isinstance(bound_acquire, Acquire):
            raise AssertionError("acquisition binding must produce Acquire")
        template = PulseProgram(
            id=PulseProgramId(_operation_id(path, "acquire-template")),
            body=bound_acquire,
            acquisition_slots=(
                AcquisitionSlot(
                    id=slot_id,
                    kind=fragment.result.acquisition_kind,
                    signal=bound_acquire.signal,
                ),
            ),
        )
        return PulseBlock(
            id=CircuitOperationId(_operation_id(path, "acquire")),
            pulse_template=template,
            acquisition_slot_bindings=((slot_id, slot_id),),
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return PulseBlock(
            id=CircuitOperationId(_operation_id(path, "pulse-template-call")),
            pulse_template=PulseProgram(
                id=fragment.template.ir_id,
                body=_bind_pulse_fragment(
                    fragment.body,
                    bindings,
                    element_bindings=element_bindings,
                    path=(),
                ),
            ),
        )
    if isinstance(
        fragment,
        _PlayFragment | _DelayFragment | _ShiftPhaseFragment | _BarrierFragment,
    ):
        return PulseBlock(
            id=CircuitOperationId(_operation_id(path, "pulse")),
            pulse_template=PulseProgram(
                id=PulseProgramId(_operation_id(path, "pulse-template")),
                body=_bind_pulse_fragment(
                    fragment,
                    bindings,
                    element_bindings=element_bindings,
                    path=(),
                ),
            ),
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        return IrQuantumSequence(
            tuple(
                _bind_quantum_fragment(
                    operation,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"sequence[{index}]"),
                )
                for index, operation in enumerate(fragment.operations)
            )
        )
    if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        return IrQuantumParallel(
            tuple(
                _bind_quantum_fragment(
                    branch,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"parallel[{index}]"),
                )
                for index, branch in enumerate(fragment.branches)
            )
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        count = _bound_repeat_count(fragment.count, bindings)
        return IrQuantumSequence(
            tuple(
                _bind_quantum_fragment(
                    fragment.operation,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"repeat[{index}]"),
                )
                for index in range(count)
            )
        )
    msg = f"unsupported quantum fragment {type(fragment).__name__}"
    raise TypeError(msg)


def _bind_pulse_fragment(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
) -> PulseInstruction:
    if isinstance(fragment, _PlayFragment):
        return Play(
            id=PulseEventId("play", scope=path),
            signal=cast(
                "PlaySignal",
                _substitute_signal(fragment.signal, element_bindings),
            ),
            envelope=_bind_envelope(fragment.envelope, bindings),
        )
    if isinstance(fragment, _DelayFragment):
        return Delay(
            id=PulseEventId("delay", scope=path),
            signal=cast(
                "PlaySignal",
                _substitute_signal(fragment.signal, element_bindings),
            ),
            duration=_bound_quantity(fragment.duration, bindings),
        )
    if isinstance(fragment, Acquisition):
        return Acquire(
            id=PulseEventId("acquire", scope=path),
            signal=cast(
                "AcquireSignal",
                _substitute_signal(fragment.signal, element_bindings),
            ),
            slot_id=fragment.result.acquisition_slot_id,
            duration=_bound_quantity(fragment.duration, bindings),
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return ShiftPhase(
            id=PulseEventId("shift-phase", scope=path),
            signal=cast(
                "FrameSignal",
                _substitute_signal(fragment.signal, element_bindings),
            ),
            phase=_bound_quantity(fragment.phase, bindings),
        )
    if isinstance(fragment, _BarrierFragment):
        return Barrier(
            id=PulseEventId("barrier", scope=path),
            signals=tuple(
                cast("PlaySignal", _substitute_signal(signal, element_bindings))
                for signal in fragment.signals
            ),
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _bind_pulse_fragment(
            fragment.body,
            bindings,
            element_bindings=element_bindings,
            path=path,
        )
    if isinstance(fragment, _QuantumSequenceFragment):
        return IrPulseSequence(
            tuple(
                _bind_pulse_fragment(
                    operation,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"sequence[{index}]"),
                )
                for index, operation in enumerate(fragment.operations)
            )
        )
    if isinstance(fragment, _QuantumParallelFragment):
        return IrPulseParallel(
            tuple(
                _bind_pulse_fragment(
                    branch,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"parallel[{index}]"),
                )
                for index, branch in enumerate(fragment.branches)
            )
        )
    if isinstance(fragment, _QuantumRepeatFragment):
        count = _bound_repeat_count(fragment.count, bindings)
        return IrPulseSequence(
            tuple(
                _bind_pulse_fragment(
                    fragment.operation,
                    bindings,
                    element_bindings=element_bindings,
                    path=(*path, f"repeat[{index}]"),
                )
                for index in range(count)
            )
        )
    msg = f"unsupported pulse fragment {type(fragment).__name__}"
    raise TypeError(msg)


def _bind_envelope(
    envelope: PulseEnvelope | AnalyticEnvelope,
    bindings: Mapping[str, object],
) -> AnalyticEnvelope:
    if isinstance(envelope, Constant | Gaussian | DRAG):
        return envelope
    kind, raw_duration, raw_amplitude, raw_sigma, raw_beta, raw_phase = (
        _pulse_envelope_parts(envelope)
    )
    duration = _bound_quantity(raw_duration, bindings)
    amplitude = _bound_quantity(raw_amplitude, bindings)
    phase = _bound_quantity(raw_phase, bindings)
    if kind == "constant":
        return Constant(duration=duration, amplitude=amplitude, phase=phase)
    sigma = _bound_quantity(cast("QuantumQuantity", raw_sigma), bindings)
    if kind == "gaussian":
        return Gaussian(
            duration=duration,
            amplitude=amplitude,
            sigma=sigma,
            phase=phase,
        )
    beta = _bound_quantity(cast("QuantumQuantity", raw_beta), bindings)
    return DRAG(
        duration=duration,
        amplitude=amplitude,
        sigma=sigma,
        beta=beta,
        phase=phase,
    )


def _bound_quantity(
    value: QuantumQuantity,
    bindings: Mapping[str, object],
) -> Quantity:
    selected = bindings[value.id] if isinstance(value, QuantumInput) else value
    if not isinstance(selected, Quantity):
        raise AssertionError("verified quantity input must bind to Quantity")
    return selected


def _bound_repeat_count(
    count: RepeatCount,
    bindings: Mapping[str, object],
) -> int:
    selected = (
        bindings[count.id] if isinstance(count, CircuitInput | QuantumInput) else count
    )
    if not isinstance(selected, int) or isinstance(selected, bool) or selected < 0:
        input_id = count.id if isinstance(count, CircuitInput | QuantumInput) else None
        qualifier = f" input {input_id!r}" if input_id is not None else ""
        msg = f"repeat count{qualifier} must bind to a non-negative integer"
        raise ProgramBindingError(msg)
    return selected


def _instantiate_pulse_template(
    template: PulseTemplate,
    elements: tuple[PulseElement, ...],
    inputs: Mapping[str, PulseTemplateArgument],
) -> PulseFragment:
    if len(elements) != len(template.elements):
        msg = (
            f"pulse template {template.id!r} requires {len(template.elements)} "
            f"elements, got {len(elements)}"
        )
        raise ValueError(msg)
    for index, (formal, actual) in enumerate(
        zip(template.elements, elements, strict=True)
    ):
        if type(formal) is not type(actual):
            msg = (
                f"pulse template {template.id!r} element {index} requires "
                f"{type(formal).__name__}, got {type(actual).__name__}"
            )
            raise TypeError(msg)
    actual_ids = tuple(_element_ir_id(element) for element in elements)
    if len(set(actual_ids)) != len(actual_ids):
        msg = f"pulse template {template.id!r} elements must be unique"
        raise ValueError(msg)

    expected = {input_handle.id: input_handle for input_handle in template.inputs}
    missing = sorted(set(expected) - set(inputs))
    unknown = sorted(set(inputs) - set(expected))
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(repr(item) for item in missing))
        if unknown:
            details.append("unknown " + ", ".join(repr(item) for item in unknown))
        msg = f"pulse template {template.id!r} inputs are invalid: " + "; ".join(
            details
        )
        raise ValueError(msg)

    input_bindings: dict[QuantumInput, Quantity | int | float | QuantumInput] = {}
    for input_id, formal in expected.items():
        selected = inputs[input_id]
        if isinstance(selected, QuantumInput):
            if selected.value_type != formal.value_type:
                msg = (
                    f"pulse template input {input_id!r} requires "
                    f"{formal.value_type!r}, but outer input {selected.id!r} "
                    "declares an incompatible type"
                )
                raise TypeError(msg)
            input_bindings[formal] = selected
            continue
        try:
            coerced = coerce_literal(formal.value_type, selected)
        except ValueValidationError as error:
            msg = f"invalid pulse template input {input_id!r}: {error}"
            raise TypeError(msg) from error
        if not isinstance(coerced, Quantity | int | float):
            msg = f"pulse template input {input_id!r} is not a scalar pulse value"
            raise TypeError(msg)
        input_bindings[formal] = coerced

    element_bindings = {
        _element_ir_id(formal): _element_ir_id(actual)
        for formal, actual in zip(template.elements, elements, strict=True)
    }
    instantiated = _substitute_pulse_fragment(
        template.body,
        element_bindings=element_bindings,
        input_bindings=input_bindings,
    )
    return _PulseTemplateCallFragment(
        template=template,
        body=instantiated,
    )


def _substitute_pulse_fragment(
    fragment: QuantumFragment,
    *,
    element_bindings: Mapping[QubitId | CouplerId, QubitId | CouplerId],
    input_bindings: Mapping[QuantumInput, Quantity | int | float | QuantumInput],
) -> QuantumFragment:
    if isinstance(fragment, _PlayFragment):
        return play(
            cast("PlaySignal", _substitute_signal(fragment.signal, element_bindings)),
            _substitute_envelope(fragment.envelope, input_bindings),
        )
    if isinstance(fragment, _DelayFragment):
        return delay(
            cast("PlaySignal", _substitute_signal(fragment.signal, element_bindings)),
            cast(
                "QuantumQuantity",
                _substitute_template_value(fragment.duration, input_bindings),
            ),
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return shift_phase(
            cast("FrameSignal", _substitute_signal(fragment.signal, element_bindings)),
            cast(
                "QuantumQuantity",
                _substitute_template_value(fragment.phase, input_bindings),
            ),
        )
    if isinstance(fragment, _BarrierFragment):
        return barrier(
            *(
                cast("PlaySignal", _substitute_signal(signal, element_bindings))
                for signal in fragment.signals
            )
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _PulseTemplateCallFragment(
            template=fragment.template,
            body=_substitute_pulse_fragment(
                fragment.body,
                element_bindings=element_bindings,
                input_bindings=input_bindings,
            ),
        )
    if isinstance(fragment, _QuantumSequenceFragment):
        return sequence(
            *(
                _substitute_pulse_fragment(
                    child,
                    element_bindings=element_bindings,
                    input_bindings=input_bindings,
                )
                for child in fragment.operations
            )
        )
    if isinstance(fragment, _QuantumParallelFragment):
        return parallel(
            *(
                _substitute_pulse_fragment(
                    child,
                    element_bindings=element_bindings,
                    input_bindings=input_bindings,
                )
                for child in fragment.branches
            )
        )
    if isinstance(fragment, _QuantumRepeatFragment):
        count = _substitute_template_value(fragment.count, input_bindings)
        return repeat(
            _substitute_pulse_fragment(
                fragment.operation,
                element_bindings=element_bindings,
                input_bindings=input_bindings,
            ),
            cast("RepeatCount", count),
        )
    raise AssertionError("verified pulse templates contain only pulse fragments")


def _substitute_envelope(
    envelope: PulseEnvelope | AnalyticEnvelope,
    bindings: Mapping[QuantumInput, Quantity | int | float | QuantumInput],
) -> PulseEnvelope | AnalyticEnvelope:
    if not isinstance(envelope, PulseEnvelope):
        return envelope
    kind, duration, amplitude, sigma, beta, phase = _pulse_envelope_parts(envelope)
    return _pulse_envelope(
        kind,
        duration=cast(
            "QuantumQuantity",
            _substitute_template_value(duration, bindings),
        ),
        amplitude=cast(
            "QuantumQuantity",
            _substitute_template_value(amplitude, bindings),
        ),
        sigma=(
            cast("QuantumQuantity", _substitute_template_value(sigma, bindings))
            if sigma is not None
            else None
        ),
        beta=(
            cast("QuantumQuantity", _substitute_template_value(beta, bindings))
            if beta is not None
            else None
        ),
        phase=cast(
            "QuantumQuantity",
            _substitute_template_value(phase, bindings),
        ),
    )


def _substitute_template_value(
    value: object,
    bindings: Mapping[QuantumInput, Quantity | int | float | QuantumInput],
) -> object:
    return bindings[value] if isinstance(value, QuantumInput) else value


def _substitute_signal(
    signal: LogicalSignal,
    bindings: Mapping[QubitId | CouplerId, QubitId | CouplerId],
) -> LogicalSignal:
    if isinstance(signal, DriveSignal):
        owner = bindings.get(signal.qubit, signal.qubit)
        assert isinstance(owner, QubitId)  # noqa: S101
        return DriveSignal(owner)
    if isinstance(signal, ReadoutSignal):
        owner = bindings.get(signal.qubit, signal.qubit)
        assert isinstance(owner, QubitId)  # noqa: S101
        return ReadoutSignal(owner)
    if isinstance(signal, AcquireSignal):
        owner = bindings.get(signal.qubit, signal.qubit)
        assert isinstance(owner, QubitId)  # noqa: S101
        return AcquireSignal(owner)
    owner = signal.owner
    return FluxSignal(bindings.get(owner, owner))


def _bound_qubit_id(qubit: Qubit, bindings: ElementBindings) -> QubitId:
    selected = bindings.get(qubit.ir_id, qubit.ir_id)
    if not isinstance(selected, QubitId):
        raise AssertionError("qubit ports must bind to logical qubits")
    return selected


def _pulse_envelope(
    kind: str,
    *,
    duration: QuantumQuantity,
    amplitude: QuantumQuantity,
    sigma: QuantumQuantity | None = None,
    beta: QuantumQuantity | None = None,
    phase: QuantumQuantity | None = None,
) -> PulseEnvelope:
    selected_phase = Quantity(0, "rad") if phase is None else phase
    _require_quantity_expression(duration, field="duration", kind="time")
    _require_quantity_expression(amplitude, field="amplitude", kind="amplitude")
    _require_quantity_expression(selected_phase, field="phase", kind="phase")
    if sigma is not None:
        _require_quantity_expression(sigma, field="sigma", kind="time")
    if beta is not None:
        _require_quantity_expression(beta, field="beta", kind="time")
    return PulseEnvelope(
        kind=kind,
        duration=duration,
        amplitude=amplitude,
        sigma=sigma,
        beta=beta,
        phase=selected_phase,
    )


def _require_quantity_expression(
    value: QuantumQuantity,
    *,
    field: str,
    kind: str,
) -> None:
    if isinstance(value, Quantity):
        accepted = False
        if kind == "time":
            accepted = _quantity_converts_to(value, "s")
        elif kind == "phase":
            accepted = _quantity_converts_to(value, "rad")
        else:
            accepted = any(
                _quantity_converts_to(value, unit) for unit in ("arb", "ratio", "V")
            )
        if accepted:
            return
        msg = f"pulse {field} must use a {kind} quantity"
        raise TypeError(msg)
    atom = value.value_type.atom
    if not isinstance(atom, QuantityType):
        msg = f"pulse {field} input {value.id!r} must declare a quantity type"
        raise TypeError(msg)
    declared_kind = atom.dimension
    if declared_kind is None and atom.unit is not None:
        probe = Quantity(1, atom.unit)
        if _quantity_converts_to(probe, "s"):
            declared_kind = "time"
        elif _quantity_converts_to(probe, "rad"):
            declared_kind = "phase"
        elif any(_quantity_converts_to(probe, unit) for unit in ("arb", "ratio", "V")):
            declared_kind = "amplitude"
    accepted_kinds = (
        {"amplitude", "ratio", "voltage"} if kind == "amplitude" else {kind}
    )
    if declared_kind not in accepted_kinds:
        msg = f"pulse {field} input {value.id!r} must declare {kind!r} quantity units"
        raise TypeError(msg)


def _quantity_converts_to(value: Quantity, unit: str) -> bool:
    try:
        value.to(unit)
    except ValueError:
        return False
    return True


def _is_integer_input(value: CircuitInput | QuantumInput) -> bool:
    if isinstance(value, CircuitInput):
        return value.kind is GateParameterKind.INTEGER
    return isinstance(value.value_type.atom, IntType)


def _program_input_type(
    value: ProgramInput,
    *,
    non_negative: bool,
) -> ScalarType:
    if isinstance(value, CircuitInput):
        return _core_input_type(value.kind, non_negative=non_negative)
    if not non_negative:
        return value.value_type
    atom = value.value_type.atom
    if not isinstance(atom, IntType):
        raise AssertionError("repeat input must have an integer type")
    minimum = 0 if atom.minimum is None else max(0, atom.minimum)
    return ScalarType(IntType(minimum=minimum, maximum=atom.maximum))


def _program_function_argument(
    name: str,
    annotation: object,
) -> PulseElement | ProgramInput:
    if annotation is Qubit:
        return qubit(name)
    if annotation is Coupler:
        return coupler(name)
    if get_origin(annotation) is Annotated:
        python_type, *metadata = cast("tuple[object, ...]", get_args(annotation))
        gate_kinds = tuple(
            item for item in metadata if isinstance(item, GateParameterKind)
        )
        scalar_types = tuple(item for item in metadata if _is_quantum_scalar_type(item))
        if len(gate_kinds) + len(scalar_types) != 1:
            raise TypeError(
                f"quantum program port {name!r} requires one scalar type annotation"
            )
        if gate_kinds:
            if not _program_python_type_matches_gate_kind(python_type, gate_kinds[0]):
                raise TypeError(
                    f"quantum program port {name!r} Python annotation is "
                    f"incompatible with {gate_kinds[0].value!r}"
                )
            return scalar_input(name, gate_kinds[0])
        value_type = _quantum_scalar_type(scalar_types[0])
        if not _program_python_type_matches_scalar(python_type, value_type):
            raise TypeError(
                f"quantum program port {name!r} Python annotation is "
                f"incompatible with {value_type!r}"
            )
        return input(name, value_type)
    if annotation is int:
        return scalar_input(name, GateParameterKind.INTEGER)
    if annotation is float:
        return scalar_input(name, GateParameterKind.NUMBER)
    raise TypeError(
        f"quantum program port {name!r} needs Qubit, Coupler, or Annotated scalar type"
    )


def _program_python_type_matches_gate_kind(
    annotation: object,
    kind: GateParameterKind,
) -> bool:
    expected: dict[GateParameterKind, tuple[object, ...]] = {
        GateParameterKind.INTEGER: (int,),
        GateParameterKind.NUMBER: (int, float),
        GateParameterKind.ANGLE: (Quantity,),
    }
    return annotation is object or annotation in expected[kind]


def _program_python_type_matches_scalar(
    annotation: object,
    value_type: ScalarType,
) -> bool:
    if annotation is object:
        return True
    atom = value_type.atom
    expected: dict[type[object], tuple[object, ...]] = {
        BoolType: (bool,),
        EntityAtomType: (str, EntityRef),
        FloatAtomType: (float,),
        IntType: (int,),
        PayloadType: (dict, Mapping),
        QuantityAtomType: (Quantity,),
        RecordType: (dict, Mapping),
        StringType: (str,),
    }
    return annotation in expected[type(atom)]


def _is_quantum_scalar_type(value: object) -> bool:
    return isinstance(
        value,
        ScalarType
        | BoolType
        | EntityAtomType
        | FloatAtomType
        | IntType
        | PayloadType
        | QuantityAtomType
        | RecordType
        | StringType,
    )


def _quantum_scalar_type(value: object) -> ScalarType:
    if isinstance(value, ScalarType):
        return value
    if isinstance(
        value,
        BoolType
        | EntityAtomType
        | FloatAtomType
        | IntType
        | PayloadType
        | QuantityAtomType
        | RecordType
        | StringType,
    ):
        return ScalarType(value)
    raise AssertionError("quantum scalar metadata was checked before normalization")


@dataclass(frozen=True, slots=True)
class _FragmentFacts:
    """One structural summary shared by quantum authoring closure checks."""

    pulse_only: bool = False
    pulse_owners: tuple[QubitId | CouplerId, ...] = ()
    element_uses: tuple[PulseElement, ...] = ()
    inputs: tuple[ProgramInput, ...] = ()
    repeat_inputs: tuple[ProgramInput, ...] = ()
    results: tuple[MeasurementResult, ...] = ()
    gate_definitions: tuple[GateDefinition, ...] = ()


def _summarize_fragment(fragment: QuantumFragment) -> _FragmentFacts:
    """Collect every closure fact in one structural fragment traversal."""

    if isinstance(fragment, _GateFragment):
        return _FragmentFacts(
            element_uses=fragment.qubits,
            inputs=tuple(
                value
                for _argument_id, value in fragment.arguments
                if isinstance(value, CircuitInput)
            ),
            gate_definitions=(fragment.gate.definition,),
        )
    if isinstance(fragment, Measurement):
        return _FragmentFacts(
            element_uses=(fragment.result.qubit,),
            results=(fragment.result,),
        )
    if isinstance(fragment, Acquisition):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(fragment.result.qubit,),
            inputs=(
                (fragment.duration,)
                if isinstance(fragment.duration, QuantumInput)
                else ()
            ),
            results=(fragment.result,),
        )
    if isinstance(fragment, _PlayFragment):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(_signal_element(fragment.signal),),
            inputs=_envelope_inputs(fragment.envelope),
        )
    if isinstance(fragment, _DelayFragment):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(_signal_element(fragment.signal),),
            inputs=(
                (fragment.duration,)
                if isinstance(fragment.duration, QuantumInput)
                else ()
            ),
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(_signal_element(fragment.signal),),
            inputs=(
                (fragment.phase,) if isinstance(fragment.phase, QuantumInput) else ()
            ),
        )
    if isinstance(fragment, _BarrierFragment):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=tuple(_signal_owner(signal) for signal in fragment.signals),
            element_uses=tuple(_signal_element(signal) for signal in fragment.signals),
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        body = _summarize_fragment(fragment.body)
        return _FragmentFacts(
            # The template factory already proves this independently of its
            # instantiated-body facts.
            pulse_only=True,
            pulse_owners=body.pulse_owners,
            element_uses=body.element_uses,
            inputs=body.inputs,
            repeat_inputs=body.repeat_inputs,
            results=body.results,
            gate_definitions=body.gate_definitions,
        )
    if isinstance(fragment, _ImplementedGateFragment):
        gate = _summarize_fragment(fragment.gate)
        pulse = _summarize_fragment(fragment.pulse)
        return _FragmentFacts(
            element_uses=(*gate.element_uses, *pulse.element_uses),
            inputs=(*gate.inputs, *pulse.inputs),
            # Gate arguments are ordinary inputs; only repeat counts inside
            # the attached pulse acquire the non-negative contract.
            repeat_inputs=pulse.repeat_inputs,
            gate_definitions=(fragment.gate.gate.definition,),
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        operation = _summarize_fragment(fragment.operation)
        carries_pulse_structure = isinstance(fragment, _QuantumRepeatFragment)
        pulse_only = operation.pulse_only if carries_pulse_structure else False
        pulse_owners = operation.pulse_owners if carries_pulse_structure else ()
        if fragment.count == 0:
            # A zero repeat elides executable declarations but remains a pulse
            # fragment with the same authorized signal-owner surface.
            return _FragmentFacts(
                pulse_only=pulse_only,
                pulse_owners=pulse_owners,
            )
        count_inputs: tuple[ProgramInput, ...] = (
            (fragment.count,)
            if isinstance(fragment.count, CircuitInput | QuantumInput)
            else ()
        )
        return _FragmentFacts(
            pulse_only=pulse_only,
            pulse_owners=pulse_owners,
            element_uses=operation.element_uses,
            inputs=(*count_inputs, *operation.inputs),
            repeat_inputs=(*count_inputs, *operation.repeat_inputs),
            results=operation.results,
            gate_definitions=operation.gate_definitions,
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        children = fragment.operations
    elif isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        children = fragment.branches
    else:
        raise AssertionError(f"unsupported quantum fragment {type(fragment).__name__}")
    return _merge_fragment_facts(
        tuple(_summarize_fragment(child) for child in children),
        carries_pulse_structure=isinstance(
            fragment,
            _QuantumSequenceFragment | _QuantumParallelFragment,
        ),
    )


def _merge_fragment_facts(
    children: tuple[_FragmentFacts, ...],
    *,
    carries_pulse_structure: bool,
) -> _FragmentFacts:
    return _FragmentFacts(
        pulse_only=(
            carries_pulse_structure and all(child.pulse_only for child in children)
        ),
        pulse_owners=(
            tuple(owner for child in children for owner in child.pulse_owners)
            if carries_pulse_structure
            else ()
        ),
        element_uses=tuple(
            element for child in children for element in child.element_uses
        ),
        inputs=tuple(value for child in children for value in child.inputs),
        repeat_inputs=tuple(
            value for child in children for value in child.repeat_inputs
        ),
        results=tuple(result for child in children for result in child.results),
        gate_definitions=tuple(
            definition for child in children for definition in child.gate_definitions
        ),
    )


def _signal_owner(signal: LogicalSignal) -> QubitId | CouplerId:
    if isinstance(signal, FluxSignal):
        return signal.owner
    return signal.qubit


def _signal_element(signal: LogicalSignal) -> PulseElement:
    owner = _signal_owner(signal)
    if isinstance(owner, CouplerId):
        return Coupler(owner)
    return Qubit(owner)


def _operation_id(path: tuple[str, ...], kind: str) -> str:
    return "/".join((*path, kind))


def _envelope_inputs(
    envelope: PulseEnvelope | AnalyticEnvelope,
) -> tuple[QuantumInput, ...]:
    if not isinstance(envelope, PulseEnvelope):
        return ()
    _kind, duration, amplitude, sigma, beta, phase = _pulse_envelope_parts(envelope)
    return tuple(
        value
        for value in (
            duration,
            amplitude,
            sigma,
            beta,
            phase,
        )
        if isinstance(value, QuantumInput)
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
    "QUANTUM_PROGRAM_DIALECT_ID",
    "QUANTUM_PROGRAM_DIALECT_VERSION",
    "Acquisition",
    "BoundProgram",
    "CircuitArgument",
    "CircuitFragment",
    "CircuitInput",
    "Coupler",
    "Gate",
    "Measurement",
    "MeasurementResult",
    "Program",
    "ProgramBindingError",
    "ProgramDefinition",
    "ProgramInput",
    "ProgramPort",
    "ProgramResults",
    "PulseElement",
    "PulseEnvelope",
    "PulseFragment",
    "PulseTemplate",
    "PulseTemplateArgument",
    "QuantumFragment",
    "QuantumInput",
    "QuantumProgramCall",
    "QuantumQuantity",
    "Qubit",
    "RepeatCount",
    "SingleQubitGate",
    "TwoQubitGate",
    "acquire",
    "barrier",
    "bind",
    "constant",
    "coupler",
    "delay",
    "drag",
    "drive",
    "flux",
    "gate",
    "gaussian",
    "implements",
    "input",
    "measure",
    "parallel",
    "play",
    "program",
    "program_port_type",
    "pulse_template",
    "qubit",
    "readout",
    "repeat",
    "scalar_input",
    "sequence",
    "shift_phase",
    "single_qubit_gate",
    "two_qubit_gate",
]
