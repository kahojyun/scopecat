"""Opaque authoring handles for unified logical and physical programs.

Gate, measurement, and pulse statements share one composition, binding, and
domain-integration surface. Pure logical programs remain a verified subset and
project to Circuit IR internally when calibration or target passes require it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Sequence as SequenceCollection
from dataclasses import MISSING, dataclass, fields
from typing import Literal, cast, overload

from scopecat import Quantity
from scopecat.authoring import (
    ComputeInput,
    DomainCall,
    DomainProgramDef,
    FloatType,
    IntType,
    QuantityType,
    ScalarType,
)
from scopecat.authoring import (
    domain_call as _core_domain_call,
)
from scopecat.authoring import (
    domain_program as _core_domain_program,
)
from scopecat.authoring.value_types import ValueValidationError, coerce_literal

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
class Coupler:
    """A logical coupler handle, independent of physical target wiring."""

    _ir_id: CouplerId

    def __init__(self) -> None:
        raise _opaque_handle_error("Coupler", "scopecat_quantum.authoring.coupler")

    @property
    def id(self) -> str:
        """Return the logical coupler port identity."""

        return self._ir_id.value


@dataclass(frozen=True, slots=True, init=False, repr=False)
class QuantumInput:
    """One core-typed scalar input consumed by a mixed quantum program."""

    _id: str
    value_type: ScalarType

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "QuantumInput",
            "scopecat_quantum.authoring.input",
        )

    @property
    def id(self) -> str:
        """Return the stable input-port identity."""

        return self._id


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


@dataclass(frozen=True, slots=True, init=False, repr=False, eq=False)
class MeasurementResult:
    """One typed result produced by logical measurement or pulse acquisition."""

    _id: str
    _qubit: Qubit
    acquisition_kind: AcquisitionKind

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "MeasurementResult",
            "scopecat_quantum.authoring.measure(...).result or acquire(...).result",
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


class QuantumFragment:
    """Opaque base type accepted by unified quantum composition factories."""

    __slots__ = ()

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "QuantumFragment",
            "gate calls, pulse statements, measure, sequence, parallel, or repeat",
        )


class CircuitFragment(QuantumFragment):
    """Opaque logical-only fragment that can be closed as a circuit."""

    __slots__ = ()

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "CircuitFragment",
            "gate calls, measure, sequence, parallel, or repeat",
        )


class PulseFragment(QuantumFragment):
    """Opaque pulse statement that composes beside gates and measurements."""

    __slots__ = ()

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "PulseFragment",
            (
                "pulse-template calls, play, acquire, shift_phase, delay, "
                "barrier, sequence, parallel, or repeat"
            ),
        )


type CircuitArgument = GateArgumentValue | CircuitInput
type QuantumQuantity = Quantity | QuantumInput
type ProgramInput = CircuitInput | QuantumInput
type RepeatCount = int | CircuitInput | QuantumInput
type PulseTemplateArgument = Quantity | int | float | QuantumInput
type PulseElement = Qubit | Coupler
type Gate = SingleQubitGate | TwoQubitGate

QUANTUM_PROGRAM_DIALECT_ID = "scopecat.quantum.program"
QUANTUM_PROGRAM_DIALECT_VERSION = "1"


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

        return _author_gate_call(self, (qubit,), arguments)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class TwoQubitGate:
    """A reusable symbolic gate with exactly two logical-qubit operands."""

    _definition: GateDefinition

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "TwoQubitGate",
            "scopecat_quantum.authoring.two_qubit_gate",
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
    raw_qubits = tuple(_runtime_object(qubit) for qubit in qubits)
    definition = _gate_definition(gate_handle)
    if len(raw_qubits) != definition.qubit_arity:
        msg = (
            f"gate {gate_handle.id!r} requires {definition.qubit_arity} qubits, "
            f"got {len(raw_qubits)}"
        )
        raise ValueError(msg)
    if not all(isinstance(qubit, Qubit) for qubit in raw_qubits):
        msg = f"gate {gate_handle.id!r} calls require Qubit handles"
        raise TypeError(msg)
    selected_qubits = cast("tuple[Qubit, ...]", raw_qubits)
    qubit_ids = tuple(_qubit_ir_id(qubit) for qubit in selected_qubits)
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
    return _create_handle(
        _GateFragment,
        gate=gate_handle,
        qubits=selected_qubits,
        arguments=tuple(ordered_arguments),
    )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Measurement(CircuitFragment):
    """A measurement statement and its first-class acquisition result."""

    result: MeasurementResult

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "Measurement",
            "scopecat_quantum.authoring.measure",
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class PulseEnvelope:
    """A symbolic analytic envelope whose quantities bind with the program."""

    _kind: str
    _duration: QuantumQuantity
    _amplitude: QuantumQuantity
    _sigma: QuantumQuantity | None
    _beta: QuantumQuantity | None
    _phase: QuantumQuantity

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "PulseEnvelope",
            "constant, gaussian, or drag",
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Acquisition(PulseFragment):
    """A physical acquisition statement and its first-class result port."""

    signal: AcquireSignal
    duration: QuantumQuantity
    result: MeasurementResult

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "Acquisition",
            "scopecat_quantum.authoring.acquire",
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class PulseTemplate:
    """A reusable, result-free pulse fragment with typed formal ports."""

    _ir_id: PulseProgramId
    _body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[QuantumInput, ...]

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "PulseTemplate",
            "scopecat_quantum.authoring.pulse_template",
        )

    @property
    def id(self) -> str:
        """Return the stable pulse-template identity."""

        return self._ir_id.value

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
    signal: LogicalSignal
    duration: QuantumQuantity


@dataclass(frozen=True, slots=True)
class _BarrierFragment(PulseFragment):
    signals: tuple[LogicalSignal, ...]


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


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Program:
    """A closed symbolic program containing logical and physical statements."""

    _ir_id: QuantumProgramId
    _body: QuantumFragment
    inputs: tuple[ProgramInput, ...]
    results: tuple[MeasurementResult, ...]
    _gate_definitions: tuple[GateDefinition, ...]

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "Program",
            "scopecat_quantum.authoring.program",
        )

    @property
    def id(self) -> str:
        """Return the stable program identity."""

        return self._ir_id.value

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the exact logical gate catalog captured by this declaration."""

        return self._gate_definitions


@dataclass(frozen=True, slots=True, init=False, repr=False)
class BoundProgram:
    """A declaration bound to concrete values and verified source IR."""

    declaration: Program
    verified: VerifiedQuantumProgram

    def __init__(self) -> None:
        raise _opaque_handle_error(
            "BoundProgram",
            "scopecat_quantum.authoring.bind",
        )

    @property
    def program(self) -> QuantumProgramIR:
        """Return the concrete unified IR accepted by pulse refinement."""

        return self.verified.program

    @property
    def gate_definitions(self) -> tuple[GateDefinition, ...]:
        """Return the verified logical gate catalog."""

        return self.verified.gate_definitions

    @property
    def results(self) -> tuple[MeasurementResult, ...]:
        """Return declared measurement and acquisition results in source order."""

        return self.declaration.results


class ProgramBindingError(ValueError):
    """Raised when concrete bindings cannot close a symbolic program."""


def _qubit_ir_id(value: Qubit) -> QubitId:
    return cast("QubitId", object.__getattribute__(value, "_ir_id"))


def _coupler_ir_id(value: Coupler) -> CouplerId:
    return cast("CouplerId", object.__getattribute__(value, "_ir_id"))


def _element_ir_id(value: PulseElement) -> QubitId | CouplerId:
    return _qubit_ir_id(value) if isinstance(value, Qubit) else _coupler_ir_id(value)


def _gate_definition(value: Gate) -> GateDefinition:
    return cast("GateDefinition", object.__getattribute__(value, "_definition"))


def _program_ir_id(value: Program) -> QuantumProgramId:
    return cast("QuantumProgramId", object.__getattribute__(value, "_ir_id"))


def _program_body(value: Program) -> QuantumFragment:
    return cast("QuantumFragment", object.__getattribute__(value, "_body"))


def _pulse_template_ir_id(value: PulseTemplate) -> PulseProgramId:
    return cast("PulseProgramId", object.__getattribute__(value, "_ir_id"))


def _pulse_template_body(value: PulseTemplate) -> QuantumFragment:
    return cast("QuantumFragment", object.__getattribute__(value, "_body"))


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
        cast("str", object.__getattribute__(value, "_kind")),
        cast("QuantumQuantity", object.__getattribute__(value, "_duration")),
        cast("QuantumQuantity", object.__getattribute__(value, "_amplitude")),
        cast(
            "QuantumQuantity | None",
            object.__getattribute__(value, "_sigma"),
        ),
        cast(
            "QuantumQuantity | None",
            object.__getattribute__(value, "_beta"),
        ),
        cast("QuantumQuantity", object.__getattribute__(value, "_phase")),
    )


def qubit(id: str) -> Qubit:  # noqa: A002
    """Declare one logical qubit handle."""

    return _create_handle(Qubit, _ir_id=QubitId(id))


def coupler(id: str) -> Coupler:  # noqa: A002
    """Declare one logical coupler handle."""

    return _create_handle(Coupler, _ir_id=CouplerId(id))


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


def input(id: str, value_type: ScalarType) -> QuantumInput:  # noqa: A001, A002
    """Declare one core-typed scalar input for gate-and-pulse authoring."""

    raw_id = _runtime_object(id)
    raw_value_type = _runtime_object(value_type)
    if not isinstance(raw_id, str) or not raw_id.strip():
        msg = "quantum input id must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(raw_value_type, ScalarType):
        msg = "quantum input value_type must be a ScalarType"
        raise TypeError(msg)
    if raw_value_type.nullable:
        msg = "quantum program inputs cannot be nullable"
        raise ValueError(msg)
    return _create_handle(
        QuantumInput,
        _id=raw_id,
        value_type=raw_value_type,
    )


def single_qubit_gate(
    id: str,  # noqa: A002
    *,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> SingleQubitGate:
    """Declare one hardware-independent single-qubit gate semantic."""

    selected = gate(id, arity=1, parameters=parameters)
    assert isinstance(selected, SingleQubitGate)
    return selected


def two_qubit_gate(
    id: str,  # noqa: A002
    *,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> TwoQubitGate:
    """Declare one hardware-independent two-qubit gate semantic."""

    selected = gate(id, arity=2, parameters=parameters)
    assert isinstance(selected, TwoQubitGate)
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
    arity: int,
    parameters: Mapping[str, GateParameterKind] | None = None,
) -> Gate:
    """Declare one hardware-independent one- or two-qubit gate semantic."""

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
    raw_arity = _runtime_object(arity)
    if not isinstance(raw_arity, int) or isinstance(raw_arity, bool):
        msg = "gate arity must be 1 or 2"
        raise TypeError(msg)
    if raw_arity not in (1, 2):
        msg = "gate arity must be 1 or 2"
        raise ValueError(msg)
    definition = GateDefinition(
        id=GateId(id),
        qubit_arity=raw_arity,
        parameters=tuple(
            GateParameterDefinition(name, kind)
            for name, kind in cast("Mapping[str, GateParameterKind]", selected).items()
        ),
    )
    handle_type = SingleQubitGate if raw_arity == 1 else TwoQubitGate
    return _create_handle(handle_type, _definition=definition)


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
        MeasurementResult,
        _id=raw_result,
        _qubit=raw_qubit,
        acquisition_kind=raw_acquisition_kind,
    )
    return _create_handle(Measurement, result=result_handle)


def acquire(
    qubit: Qubit,
    /,
    *,
    duration: QuantumQuantity,
    result: str,
    acquisition_kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
) -> Acquisition:
    """Acquire one physical signal and expose its typed result port."""

    raw_qubit = _runtime_object(qubit)
    raw_result = _runtime_object(result)
    raw_acquisition_kind = _runtime_object(acquisition_kind)
    if not isinstance(raw_qubit, Qubit):
        msg = "acquire requires a Qubit handle"
        raise TypeError(msg)
    _require_quantity_expression(duration, field="duration", kind="time")
    if not isinstance(raw_result, str) or not raw_result.strip():
        msg = "acquisition result id must be a non-empty string"
        raise ValueError(msg)
    if not isinstance(raw_acquisition_kind, AcquisitionKind):
        msg = "acquire acquisition_kind must be an AcquisitionKind"
        raise TypeError(msg)
    result_handle = _create_handle(
        MeasurementResult,
        _id=raw_result,
        _qubit=raw_qubit,
        acquisition_kind=raw_acquisition_kind,
    )
    return _create_handle(
        Acquisition,
        signal=AcquireSignal(_qubit_ir_id(raw_qubit)),
        duration=duration,
        result=result_handle,
    )


def drive(qubit: Qubit, /) -> DriveSignal:
    """Select the logical drive signal for one authored qubit."""

    raw_qubit = _runtime_object(qubit)
    if not isinstance(raw_qubit, Qubit):
        msg = "drive requires a Qubit handle"
        raise TypeError(msg)
    return DriveSignal(_qubit_ir_id(raw_qubit))


def flux(element: PulseElement, /) -> FluxSignal:
    """Select the logical flux signal for one authored qubit or coupler."""

    raw_element = _runtime_object(element)
    if not isinstance(raw_element, Qubit | Coupler):
        msg = "flux requires a Qubit or Coupler handle"
        raise TypeError(msg)
    return FluxSignal(_element_ir_id(raw_element))


def readout(qubit: Qubit, /) -> ReadoutSignal:
    """Select the logical readout-stimulus signal for one authored qubit."""

    raw_qubit = _runtime_object(qubit)
    if not isinstance(raw_qubit, Qubit):
        msg = "readout requires a Qubit handle"
        raise TypeError(msg)
    return ReadoutSignal(_qubit_ir_id(raw_qubit))


def shift_phase(signal: FrameSignal, phase: QuantumQuantity, /) -> PulseFragment:
    """Advance a drive or readout frame without consuming timeline duration."""

    raw_signal = _runtime_object(signal)
    if not isinstance(raw_signal, DriveSignal | ReadoutSignal):
        msg = "shift_phase requires a drive or readout logical signal"
        raise TypeError(msg)
    _require_quantity_expression(phase, field="phase shift", kind="phase")
    return _create_handle(
        _ShiftPhaseFragment,
        signal=raw_signal,
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

    raw_body = _runtime_object(body)
    if not isinstance(raw_body, QuantumFragment) or not _is_pulse_only(raw_body):
        msg = "pulse_template body must contain only pulse statements"
        raise TypeError(msg)
    if _quantum_fragment_results(raw_body):
        msg = "pulse templates cannot capture acquisition results"
        raise ValueError(msg)
    raw_elements = tuple(elements)
    if not all(
        isinstance(_runtime_object(item), Qubit | Coupler) for item in raw_elements
    ):
        msg = "pulse template elements must contain only Qubit or Coupler handles"
        raise TypeError(msg)
    element_ids = tuple(_element_ir_id(item) for item in raw_elements)
    if len(set(element_ids)) != len(element_ids):
        msg = "pulse template elements must be unique"
        raise ValueError(msg)

    inputs_by_id: dict[str, QuantumInput] = {}
    for input_handle in _quantum_fragment_inputs(raw_body):
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
    foreign_owners = {
        owner for owner in _pulse_fragment_owners(raw_body) if owner not in formal_ids
    }
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"pulse template contains undeclared formal elements: {rendered}"
        raise ValueError(msg)

    return _create_handle(
        PulseTemplate,
        _ir_id=PulseProgramId(id),
        _body=raw_body,
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

    raw_signal = _runtime_object(signal)
    raw_envelope = _runtime_object(envelope)
    if not isinstance(raw_signal, DriveSignal | FluxSignal | ReadoutSignal):
        msg = "play requires a drive, flux, or readout logical signal"
        raise TypeError(msg)
    if not isinstance(raw_envelope, PulseEnvelope | Constant | Gaussian | DRAG):
        msg = "play requires an analytic pulse envelope"
        raise TypeError(msg)
    return _create_handle(
        _PlayFragment,
        signal=raw_signal,
        envelope=raw_envelope,
    )


def delay(signal: LogicalSignal, duration: QuantumQuantity, /) -> PulseFragment:
    """Reserve time on one logical signal."""

    raw_signal = _runtime_object(signal)
    if not isinstance(raw_signal, DriveSignal | FluxSignal | ReadoutSignal):
        msg = "delay requires a drive, flux, or readout logical signal"
        raise TypeError(msg)
    _require_quantity_expression(duration, field="duration", kind="time")
    return _create_handle(_DelayFragment, signal=raw_signal, duration=duration)


def barrier(*signals: LogicalSignal) -> PulseFragment:
    """Synchronize one or more logical signals without advancing time."""

    if not signals:
        msg = "barrier requires at least one logical signal"
        raise ValueError(msg)
    if not all(
        isinstance(
            _runtime_object(signal),
            DriveSignal | FluxSignal | ReadoutSignal,
        )
        for signal in signals
    ):
        msg = "barrier accepts only logical signals"
        raise TypeError(msg)
    return _create_handle(_BarrierFragment, signals=signals)


def implements(
    gate_call: CircuitFragment,
    pulse: QuantumFragment,
    /,
    *,
    resources: SequenceCollection[Coupler] = (),
    candidate: str | None = None,
) -> QuantumFragment:
    """Attach one explicit pulse implementation to a logical gate occurrence."""

    raw_gate_call = _runtime_object(gate_call)
    raw_pulse = _runtime_object(pulse)
    if not isinstance(raw_gate_call, _GateFragment):
        msg = "implements requires one authored gate call"
        raise TypeError(msg)
    if not isinstance(raw_pulse, QuantumFragment) or not _is_pulse_only(raw_pulse):
        msg = "implements pulse must contain only pulse statements"
        raise TypeError(msg)
    if _quantum_fragment_results(raw_pulse):
        msg = "implements pulse cannot acquire results"
        raise ValueError(msg)
    raw_resources = tuple(_runtime_object(resource) for resource in resources)
    if not all(isinstance(resource, Coupler) for resource in raw_resources):
        msg = "implements resources must contain only Coupler handles"
        raise TypeError(msg)
    selected_resources = cast("tuple[Coupler, ...]", raw_resources)
    resource_ids = tuple(_coupler_ir_id(resource) for resource in selected_resources)
    if len(set(resource_ids)) != len(resource_ids):
        msg = "implements resources must be unique"
        raise ValueError(msg)
    operand_ids = {_qubit_ir_id(qubit) for qubit in raw_gate_call.qubits}
    allowed_owners = {*operand_ids, *resource_ids}
    pulse_owners = set(_pulse_fragment_owners(raw_pulse))
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
    return _create_handle(
        _ImplementedGateFragment,
        gate=raw_gate_call,
        pulse=raw_pulse,
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
    _require_fragments(operations, composition="sequence")
    if all(isinstance(operation, CircuitFragment) for operation in operations):
        return _create_handle(
            _SequenceFragment,
            operations=cast("tuple[CircuitFragment, ...]", operations),
        )
    return _create_handle(_QuantumSequenceFragment, operations=operations)


@overload
def parallel(*branches: CircuitFragment) -> CircuitFragment: ...


@overload
def parallel(*branches: QuantumFragment) -> QuantumFragment: ...


def parallel(*branches: QuantumFragment) -> QuantumFragment:
    """Compose two or more gate, measurement, or pulse branches concurrently."""

    if len(branches) < 2:
        msg = "parallel requires at least two quantum branches"
        raise ValueError(msg)
    _require_fragments(branches, composition="parallel")
    if all(isinstance(branch, CircuitFragment) for branch in branches):
        return _create_handle(
            _ParallelFragment,
            branches=cast("tuple[CircuitFragment, ...]", branches),
        )
    return _create_handle(_QuantumParallelFragment, branches=branches)


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

    _require_fragments((operation,), composition="repeat")
    if _quantum_fragment_results(operation):
        msg = (
            "repeat does not support fragments that produce measurement results "
            "or physical acquisition results"
        )
        raise ValueError(msg)
    raw_count = _runtime_object(count)
    if isinstance(raw_count, CircuitInput | QuantumInput):
        if not _is_integer_input(raw_count):
            msg = "repeat count inputs must have integer kind"
            raise TypeError(msg)
    elif not isinstance(raw_count, int) or isinstance(raw_count, bool) or raw_count < 0:
        msg = "repeat count must be a non-negative integer or integer input"
        raise ValueError(msg)
    if isinstance(operation, CircuitFragment) and isinstance(
        raw_count, int | CircuitInput
    ):
        return _create_handle(
            _RepeatFragment,
            operation=operation,
            count=raw_count,
        )
    return _create_handle(
        _QuantumRepeatFragment,
        operation=operation,
        count=raw_count,
    )


def program(id: str, body: QuantumFragment) -> Program:  # noqa: A002
    """Close one unified gate-and-pulse fragment into a symbolic program."""

    _require_fragments((body,), composition="program")
    ir_id = QuantumProgramId(id)
    collected_inputs = _quantum_fragment_inputs(body)
    inputs_by_id: dict[str, ProgramInput] = {}
    contracts_by_id: dict[str, ScalarType] = {}
    repeat_input_ids = {
        input_handle.id for input_handle in _quantum_fragment_repeat_inputs(body)
    }
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

    results = _quantum_fragment_results(body)
    duplicate_results = _duplicates(result.id for result in results)
    if duplicate_results:
        rendered = ", ".join(repr(item) for item in duplicate_results)
        msg = f"quantum program has duplicate result ids: {rendered}"
        raise ValueError(msg)

    definitions_by_id: dict[str, GateDefinition] = {}
    for definition in _quantum_fragment_gate_definitions(body):
        existing = definitions_by_id.get(definition.id.value)
        if existing is not None and existing != definition:
            msg = (
                f"quantum program gate {definition.id.value!r} has "
                "conflicting definitions"
            )
            raise ValueError(msg)
        definitions_by_id.setdefault(definition.id.value, definition)

    return _create_handle(
        Program,
        _ir_id=ir_id,
        _body=body,
        inputs=tuple(inputs_by_id.values()),
        results=results,
        _gate_definitions=tuple(definitions_by_id.values()),
    )


def bind(
    declaration: Program,
    bindings: Mapping[str, object] | None = None,
) -> BoundProgram:
    """Bind all inputs and return verified unified quantum IR."""

    raw_declaration = _runtime_object(declaration)
    if not isinstance(raw_declaration, Program):
        msg = "bind requires a Program handle"
        raise TypeError(msg)
    raw_selected = _runtime_object(bindings)
    if raw_selected is not None and not isinstance(raw_selected, Mapping):
        msg = "quantum program bindings must be a mapping"
        raise TypeError(msg)
    raw_bindings: Mapping[object, object] = (
        {} if raw_selected is None else cast("Mapping[object, object]", raw_selected)
    )
    if not all(isinstance(name, str) for name in raw_bindings):
        msg = "quantum program binding ids must be strings"
        raise ProgramBindingError(msg)
    selected_bindings = cast("Mapping[str, object]", raw_bindings)
    expected = {input_handle.id for input_handle in raw_declaration.inputs}
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
        for input_handle in _quantum_fragment_repeat_inputs(
            _program_body(raw_declaration)
        )
    }
    concrete_bindings: dict[str, object] = {}
    for input_handle in raw_declaration.inputs:
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
        id=_program_ir_id(raw_declaration),
        body=_bind_quantum_fragment(
            _program_body(raw_declaration),
            concrete_bindings,
            path=("body",),
        ),
    )
    verified = verify_quantum_program(concrete, raw_declaration.gate_definitions)
    return _create_handle(
        BoundProgram,
        declaration=raw_declaration,
        verified=verified,
    )


def domain_program(declaration: Program) -> DomainProgramDef:
    """Project a unified declaration into core's domain program seam."""

    raw_declaration = _runtime_object(declaration)
    if not isinstance(raw_declaration, Program):
        msg = "domain_program requires a Program handle"
        raise TypeError(msg)
    repeat_input_ids = {
        input_handle.id
        for input_handle in _quantum_fragment_repeat_inputs(
            _program_body(raw_declaration)
        )
    }
    return _core_domain_program(
        raw_declaration.id,
        dialect_id=QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=QUANTUM_PROGRAM_DIALECT_VERSION,
        body=raw_declaration,
        inputs={
            input_handle.id: _program_input_type(
                input_handle,
                non_negative=input_handle.id in repeat_input_ids,
            )
            for input_handle in raw_declaration.inputs
        },
        results={result.id: result for result in raw_declaration.results},
    )


def domain_call(
    id: str,  # noqa: A002
    program: DomainProgramDef,
    *,
    inputs: Mapping[ProgramInput, ComputeInput] | None = None,
    results: Mapping[MeasurementResult, str] | None = None,
) -> DomainCall:
    """Bind program handles to core values and logical products."""

    raw_program = _runtime_object(program)
    if not isinstance(raw_program, DomainProgramDef):
        msg = "domain_call requires a quantum program domain program"
        raise TypeError(msg)
    if (
        raw_program.dialect_id != QUANTUM_PROGRAM_DIALECT_ID
        or raw_program.dialect_version != QUANTUM_PROGRAM_DIALECT_VERSION
        or not isinstance(raw_program.body, Program)
    ):
        msg = "domain_call requires a quantum program domain program"
        raise TypeError(msg)
    declaration = raw_program.body
    expected_program = domain_program(declaration)
    if (
        raw_program.id != expected_program.id
        or raw_program.input_ports != expected_program.input_ports
        or raw_program.result_ports != expected_program.result_ports
    ):
        msg = "quantum program domain ports do not match its Program body"
        raise ValueError(msg)
    raw_inputs = _runtime_object(inputs)
    raw_results = _runtime_object(results)
    if raw_inputs is not None and not isinstance(raw_inputs, Mapping):
        raise TypeError("quantum program domain call inputs must be a mapping")
    if raw_results is not None and not isinstance(raw_results, Mapping):
        raise TypeError("quantum program domain call results must be a mapping")
    selected_inputs: Mapping[ProgramInput, ComputeInput] = cast(
        "Mapping[ProgramInput, ComputeInput]",
        {} if raw_inputs is None else raw_inputs,
    )
    selected_results: Mapping[MeasurementResult, str] = cast(
        "Mapping[MeasurementResult, str]",
        {} if raw_results is None else raw_results,
    )
    if set(selected_inputs) != set(declaration.inputs):
        msg = "quantum program domain call inputs must bind every declared input"
        raise ValueError(msg)
    if set(selected_results) != set(declaration.results):
        msg = "quantum program domain call results must bind every declared result"
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
    return _core_domain_call(
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
        return ScalarType(QuantityType(dimension="phase", unit="rad"))
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
            qubits=tuple(_qubit_ir_id(qubit) for qubit in fragment.qubits),
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
        raise ProgramBindingError(msg)
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


def _bind_quantum_fragment(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    path: tuple[str, ...],
) -> QuantumNode:
    if isinstance(fragment, _GateFragment | Measurement):
        return cast(
            "GateCall | Measure",
            _bind_fragment(
                fragment,
                cast("Mapping[str, GateArgumentValue]", bindings),
                path=path,
            ),
        )
    if isinstance(fragment, _ImplementedGateFragment):
        call = _bind_fragment(
            fragment.gate,
            cast("Mapping[str, GateArgumentValue]", bindings),
            path=(*path, "logical"),
        )
        if not isinstance(call, GateCall):
            raise AssertionError("implemented gate binding must produce a GateCall")
        pulse_template_id = (
            _pulse_template_ir_id(fragment.pulse.template)
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
                    path=("implementation",),
                ),
            ),
            candidate_id=fragment.candidate_id,
        )
    if isinstance(fragment, Acquisition):
        slot_id = fragment.result.acquisition_slot_id
        template = PulseProgram(
            id=PulseProgramId(_operation_id(path, "acquire-template")),
            body=_bind_pulse_fragment(fragment, bindings, path=()),
            acquisition_slots=(
                AcquisitionSlot(
                    id=slot_id,
                    kind=fragment.result.acquisition_kind,
                    signal=fragment.signal,
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
                id=_pulse_template_ir_id(fragment.template),
                body=_bind_pulse_fragment(fragment.body, bindings, path=()),
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
                body=_bind_pulse_fragment(fragment, bindings, path=()),
            ),
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        return IrQuantumSequence(
            tuple(
                _bind_quantum_fragment(
                    operation,
                    bindings,
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
    path: tuple[str, ...],
) -> PulseInstruction:
    if isinstance(fragment, _PlayFragment):
        return Play(
            id=PulseEventId("play", scope=path),
            signal=fragment.signal,
            envelope=_bind_envelope(fragment.envelope, bindings),
        )
    if isinstance(fragment, _DelayFragment):
        return Delay(
            id=PulseEventId("delay", scope=path),
            signal=fragment.signal,
            duration=_bound_quantity(fragment.duration, bindings),
        )
    if isinstance(fragment, Acquisition):
        return Acquire(
            id=PulseEventId("acquire", scope=path),
            signal=fragment.signal,
            slot_id=fragment.result.acquisition_slot_id,
            duration=_bound_quantity(fragment.duration, bindings),
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return ShiftPhase(
            id=PulseEventId("shift-phase", scope=path),
            signal=fragment.signal,
            phase=_bound_quantity(fragment.phase, bindings),
        )
    if isinstance(fragment, _BarrierFragment):
        return Barrier(
            id=PulseEventId("barrier", scope=path),
            signals=fragment.signals,
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _bind_pulse_fragment(fragment.body, bindings, path=path)
    if isinstance(fragment, _QuantumSequenceFragment):
        return IrPulseSequence(
            tuple(
                _bind_pulse_fragment(
                    operation,
                    bindings,
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
    raw_elements = tuple(_runtime_object(element) for element in elements)
    if len(raw_elements) != len(template.elements):
        msg = (
            f"pulse template {template.id!r} requires {len(template.elements)} "
            f"elements, got {len(raw_elements)}"
        )
        raise ValueError(msg)
    if not all(isinstance(element, Qubit | Coupler) for element in raw_elements):
        msg = "pulse template calls require Qubit or Coupler handles"
        raise TypeError(msg)
    for index, (formal, actual) in enumerate(
        zip(template.elements, raw_elements, strict=True)
    ):
        if type(formal) is not type(actual):
            msg = (
                f"pulse template {template.id!r} element {index} requires "
                f"{type(formal).__name__}, got {type(actual).__name__}"
            )
            raise TypeError(msg)
    selected_elements = cast("tuple[PulseElement, ...]", raw_elements)
    actual_ids = tuple(_element_ir_id(element) for element in selected_elements)
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
        selected = _runtime_object(inputs[input_id])
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
        for formal, actual in zip(template.elements, selected_elements, strict=True)
    }
    instantiated = _substitute_pulse_fragment(
        _pulse_template_body(template),
        element_bindings=element_bindings,
        input_bindings=input_bindings,
    )
    return _create_handle(
        _PulseTemplateCallFragment,
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
            _substitute_signal(fragment.signal, element_bindings),
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
                _substitute_signal(signal, element_bindings)
                for signal in fragment.signals
            )
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _create_handle(
            _PulseTemplateCallFragment,
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
        assert isinstance(owner, QubitId)
        return DriveSignal(owner)
    if isinstance(signal, ReadoutSignal):
        owner = bindings.get(signal.qubit, signal.qubit)
        assert isinstance(owner, QubitId)
        return ReadoutSignal(owner)
    if isinstance(signal, AcquireSignal):
        owner = bindings.get(signal.qubit, signal.qubit)
        assert isinstance(owner, QubitId)
        return AcquireSignal(owner)
    owner = signal.owner
    return FluxSignal(bindings.get(owner, owner))


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
    return _create_handle(
        PulseEnvelope,
        _kind=kind,
        _duration=duration,
        _amplitude=amplitude,
        _sigma=sigma,
        _beta=beta,
        _phase=selected_phase,
    )


def _require_quantity_expression(
    value: object,
    *,
    field: str,
    kind: str,
) -> None:
    raw_value = _runtime_object(value)
    if isinstance(raw_value, Quantity):
        accepted = False
        if kind == "time":
            accepted = _quantity_converts_to(raw_value, "s")
        elif kind == "phase":
            accepted = _quantity_converts_to(raw_value, "rad")
        else:
            accepted = any(
                _quantity_converts_to(raw_value, unit) for unit in ("arb", "ratio", "V")
            )
        if accepted:
            return
        msg = f"pulse {field} must use a {kind} quantity"
        raise TypeError(msg)
    if not isinstance(raw_value, QuantumInput):
        msg = f"pulse {field} must be a Quantity or QuantumInput"
        raise TypeError(msg)
    atom = raw_value.value_type.atom
    if not isinstance(atom, QuantityType):
        msg = f"pulse {field} input {raw_value.id!r} must declare a quantity type"
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
        msg = (
            f"pulse {field} input {raw_value.id!r} must declare {kind!r} quantity units"
        )
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


def _is_pulse_only(fragment: QuantumFragment) -> bool:
    if isinstance(
        fragment,
        Acquisition
        | _PlayFragment
        | _DelayFragment
        | _ShiftPhaseFragment
        | _BarrierFragment
        | _PulseTemplateCallFragment,
    ):
        return True
    if isinstance(fragment, _QuantumSequenceFragment):
        return all(_is_pulse_only(child) for child in fragment.operations)
    if isinstance(fragment, _QuantumParallelFragment):
        return all(_is_pulse_only(child) for child in fragment.branches)
    if isinstance(fragment, _QuantumRepeatFragment):
        return _is_pulse_only(fragment.operation)
    return False


def _pulse_fragment_owners(
    fragment: QuantumFragment,
) -> tuple[QubitId | CouplerId, ...]:
    if isinstance(
        fragment,
        Acquisition | _PlayFragment | _DelayFragment | _ShiftPhaseFragment,
    ):
        return (_signal_owner(fragment.signal),)
    if isinstance(fragment, _BarrierFragment):
        return tuple(_signal_owner(signal) for signal in fragment.signals)
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _pulse_fragment_owners(fragment.body)
    if isinstance(fragment, _QuantumSequenceFragment):
        children = fragment.operations
    elif isinstance(fragment, _QuantumParallelFragment):
        children = fragment.branches
    elif isinstance(fragment, _QuantumRepeatFragment):
        return _pulse_fragment_owners(fragment.operation)
    else:
        return ()
    return tuple(owner for child in children for owner in _pulse_fragment_owners(child))


def _signal_owner(signal: LogicalSignal) -> QubitId | CouplerId:
    if isinstance(signal, FluxSignal):
        return signal.owner
    return signal.qubit


def _operation_id(path: tuple[str, ...], kind: str) -> str:
    return "/".join((*path, kind))


def _require_fragments(
    values: tuple[QuantumFragment, ...],
    *,
    composition: str,
) -> None:
    if not all(isinstance(_runtime_object(value), QuantumFragment) for value in values):
        msg = f"{composition} accepts only QuantumFragment handles"
        raise TypeError(msg)


def _quantum_fragment_inputs(
    fragment: QuantumFragment,
) -> tuple[ProgramInput, ...]:
    if isinstance(fragment, _GateFragment):
        return tuple(
            value
            for _argument_id, value in fragment.arguments
            if isinstance(value, CircuitInput)
        )
    if isinstance(fragment, Measurement | _BarrierFragment):
        return ()
    if isinstance(fragment, Acquisition):
        return (
            (fragment.duration,) if isinstance(fragment.duration, QuantumInput) else ()
        )
    if isinstance(fragment, _PlayFragment):
        return _envelope_inputs(fragment.envelope)
    if isinstance(fragment, _DelayFragment):
        return (
            (fragment.duration,) if isinstance(fragment.duration, QuantumInput) else ()
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return (fragment.phase,) if isinstance(fragment.phase, QuantumInput) else ()
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _quantum_fragment_inputs(fragment.body)
    if isinstance(fragment, _ImplementedGateFragment):
        return (
            *_quantum_fragment_inputs(fragment.gate),
            *_quantum_fragment_inputs(fragment.pulse),
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if fragment.count == 0:
            return ()
        count_inputs: tuple[ProgramInput, ...] = (
            (fragment.count,)
            if isinstance(fragment.count, CircuitInput | QuantumInput)
            else ()
        )
        return (*count_inputs, *_quantum_fragment_inputs(fragment.operation))
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment)
        else ()
    )
    return tuple(
        input_handle
        for child in children
        for input_handle in _quantum_fragment_inputs(child)
    )


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


def _quantum_fragment_results(
    fragment: QuantumFragment,
) -> tuple[MeasurementResult, ...]:
    if isinstance(fragment, Measurement | Acquisition):
        return (fragment.result,)
    if isinstance(
        fragment,
        _GateFragment
        | _PlayFragment
        | _DelayFragment
        | _ShiftPhaseFragment
        | _BarrierFragment
        | _ImplementedGateFragment,
    ):
        return ()
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _quantum_fragment_results(fragment.body)
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if fragment.count == 0:
            return ()
        return _quantum_fragment_results(fragment.operation)
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment)
        else ()
    )
    return tuple(
        result for child in children for result in _quantum_fragment_results(child)
    )


def _quantum_fragment_gate_definitions(
    fragment: QuantumFragment,
) -> tuple[GateDefinition, ...]:
    if isinstance(fragment, _GateFragment):
        return (_gate_definition(fragment.gate),)
    if isinstance(fragment, _ImplementedGateFragment):
        return (_gate_definition(fragment.gate.gate),)
    if isinstance(
        fragment,
        Measurement
        | Acquisition
        | _PlayFragment
        | _DelayFragment
        | _ShiftPhaseFragment
        | _BarrierFragment,
    ):
        return ()
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _quantum_fragment_gate_definitions(fragment.body)
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if fragment.count == 0:
            return ()
        return _quantum_fragment_gate_definitions(fragment.operation)
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment)
        else ()
    )
    return tuple(
        definition
        for child in children
        for definition in _quantum_fragment_gate_definitions(child)
    )


def _quantum_fragment_repeat_inputs(
    fragment: QuantumFragment,
) -> tuple[ProgramInput, ...]:
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if fragment.count == 0:
            return ()
        count_inputs: tuple[ProgramInput, ...] = (
            (fragment.count,)
            if isinstance(fragment.count, CircuitInput | QuantumInput)
            else ()
        )
        return (
            *count_inputs,
            *_quantum_fragment_repeat_inputs(fragment.operation),
        )
    if isinstance(
        fragment,
        _GateFragment
        | Measurement
        | Acquisition
        | _PlayFragment
        | _DelayFragment
        | _ShiftPhaseFragment
        | _BarrierFragment,
    ):
        return ()
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _quantum_fragment_repeat_inputs(fragment.body)
    if isinstance(fragment, _ImplementedGateFragment):
        return _quantum_fragment_repeat_inputs(fragment.pulse)
    children = (
        fragment.operations
        if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment)
        else fragment.branches
        if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment)
        else ()
    )
    return tuple(
        input_handle
        for child in children
        for input_handle in _quantum_fragment_repeat_inputs(child)
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
    "ProgramInput",
    "PulseElement",
    "PulseEnvelope",
    "PulseFragment",
    "PulseTemplate",
    "PulseTemplateArgument",
    "QuantumFragment",
    "QuantumInput",
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
    "domain_call",
    "domain_program",
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
