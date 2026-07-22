"""Opaque authoring handles for unified logical and physical programs.

Gate, measurement, and pulse statements share one composition, binding, and
domain-integration surface. Pure logical programs remain a verified subset and
project to Circuit IR internally when implementation or target passes require it.
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
    ExperimentModule,
    FloatType,
    IntType,
    ModuleBuilder,
    ModuleInvocation,
    ProductOutputs,
    ProductRef,
    QuantityType,
    ScalarType,
    ValueRef,
    ValueType,
    product_axis,
    shot_axis,
)
from scopecat.authoring import (
    Input as ExperimentInput,
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
from scopecat.measurements.results import MeasurementDType
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
    RealtimeStateId,
    RealtimeValueId,
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
    Conditional as IrQuantumConditional,
)
from scopecat_quantum.programs import (
    ImplementedGate,
    PulseBlock,
    QuantumNode,
    QuantumProgramIR,
    RealtimeBitRef,
    VerifiedQuantumProgram,
    verify_quantum_program,
)
from scopecat_quantum.programs import Parallel as IrQuantumParallel
from scopecat_quantum.programs import (
    PauliFrameXor as IrPauliFrameXor,
)
from scopecat_quantum.programs import (
    RealtimeBitStateInit as IrRealtimeBitStateInit,
)
from scopecat_quantum.programs import (
    RealtimeBitStateRead as IrRealtimeBitStateRead,
)
from scopecat_quantum.programs import (
    RealtimeBitStateWrite as IrRealtimeBitStateWrite,
)
from scopecat_quantum.programs import (
    RealtimeBitXor as IrRealtimeBitXor,
)
from scopecat_quantum.programs import (
    RealtimeResultEmit as IrRealtimeResultEmit,
)
from scopecat_quantum.programs import (
    Repeat as IrQuantumRepeat,
)
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
class ProgramInput:
    """One core-typed scalar input shared by circuit and pulse authoring."""

    _id: str
    value_type: ScalarType

    @property
    def id(self) -> str:
        """Return the stable input-port identity."""

        return self._id


@dataclass(frozen=True, slots=True, repr=False)
class QuantumResultAxis:
    """One non-shot product axis declared by a quantum result contract."""

    id: str
    size: int | ProgramInput
    kind: str
    unit: str | None = "count"

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.kind.strip():
            raise ValueError("quantum result axis id and kind must be non-empty")
        if self.id == "shot":
            raise ValueError("quantum result contracts add the shot axis automatically")
        if isinstance(self.size, int):
            if isinstance(self.size, bool) or self.size <= 0:
                raise ValueError("quantum result axis size must be a positive integer")
        elif not _is_integer_input(self.size):
            raise TypeError("quantum result axis inputs must be integers")


@dataclass(frozen=True, slots=True, repr=False)
class QuantumResultContract:
    """Product schema and per-acquisition shape for one quantum result.

    ``axes`` follow the automatic shot axis. ``acquisition_shape`` identifies
    which of those axes are realized inside one physical acquisition frame;
    other axes may later index recursively repeated or composite addresses.
    """

    acquisition_kind: AcquisitionKind
    dtype: MeasurementDType
    unit: str | None
    axes: tuple[QuantumResultAxis, ...] = ()
    acquisition_shape: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        axis_ids = tuple(axis.id for axis in self.axes)
        duplicates = tuple(
            sorted(axis_id for axis_id in set(axis_ids) if axis_ids.count(axis_id) > 1)
        )
        if duplicates:
            rendered = ", ".join(repr(item) for item in duplicates)
            raise ValueError(f"quantum result has duplicate axes: {rendered}")
        unknown_shape = tuple(
            axis_id for axis_id in self.acquisition_shape if axis_id not in axis_ids
        )
        if unknown_shape:
            rendered = ", ".join(repr(item) for item in unknown_shape)
            raise ValueError(f"quantum acquisition shape uses unknown axes: {rendered}")
        if self.acquisition_kind is AcquisitionKind.INTEGRATED_IQ:
            if self.acquisition_shape:
                raise ValueError("integrated-IQ acquisitions are scalar per shot")
            return
        if self.acquisition_shape != ("sample",):
            raise ValueError("raw-trace acquisition shape must be ('sample',)")
        sample_axis = next(axis for axis in self.axes if axis.id == "sample")
        if sample_axis.kind != "sample" or sample_axis.unit != "count":
            raise ValueError("raw-trace results require a canonical sample/count axis")


@dataclass(frozen=True, slots=True, repr=False)
class RealtimeResultContract:
    """Product schema for one value emitted by target-local realtime logic."""

    dtype: MeasurementDType = "int64"
    unit: str | None = "count"
    axes: tuple[QuantumResultAxis, ...] = ()

    def __post_init__(self) -> None:
        axis_ids = tuple(axis.id for axis in self.axes)
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("realtime result axes must be unique")


REALTIME_BIT_RESULT = RealtimeResultContract()


def integrated_iq_result(
    *,
    dtype: MeasurementDType = "complex128",
    unit: str | None = "ratio",
) -> QuantumResultContract:
    """Describe one scalar integrated-IQ value per shot."""

    return QuantumResultContract(
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        dtype=dtype,
        unit=unit,
    )


INTEGRATED_IQ_RESULT = integrated_iq_result()


def raw_trace_result(
    samples: int | ProgramInput,
    /,
    *,
    dtype: MeasurementDType = "complex128",
    unit: str | None = "ratio",
) -> QuantumResultContract:
    """Describe complex raw-trace shots with one explicit sample dimension."""

    return QuantumResultContract(
        acquisition_kind=AcquisitionKind.RAW_TRACE,
        dtype=dtype,
        unit=unit,
        axes=(QuantumResultAxis("sample", samples, "sample"),),
        acquisition_shape=("sample",),
    )


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class MeasurementResult:
    """One typed result produced by logical measurement or pulse acquisition."""

    _id: str
    _qubit: Qubit
    contract: QuantumResultContract

    @property
    def id(self) -> str:
        """Return the stable result-port identity."""

        return self._id

    @property
    def qubit(self) -> Qubit:
        """Return the logical qubit measured for this result."""

        return self._qubit

    @property
    def acquisition_kind(self) -> AcquisitionKind:
        """Return the physical acquisition kind promised by the contract."""

        return self.contract.acquisition_kind

    @property
    def acquisition_slot_id(self) -> AcquisitionSlotId:
        """Return the acquisition identity used by materialized circuit IR."""

        return AcquisitionSlotId(self._id)


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class RealtimeResult:
    """One typed result emitted from target-local realtime computation."""

    _id: str
    contract: RealtimeResultContract = REALTIME_BIT_RESULT

    @property
    def id(self) -> str:
        """Return the stable result-port identity."""

        return self._id

    @property
    def result_slot_id(self) -> AcquisitionSlotId:
        """Return the target result identity used by retained control IR."""

        return AcquisitionSlotId(self._id)


type ProgramResult = MeasurementResult | RealtimeResult


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class RealtimeBit:
    """One explicitly requested target-local discriminator output."""

    _id: str

    def __post_init__(self) -> None:
        if not self._id.strip():
            raise ValueError("measurement bit id must be a non-empty string")

    @property
    def id(self) -> str:
        """Return the authored local value name used in diagnostics."""

        return self._id


@dataclass(frozen=True, slots=True, repr=False)
class ProgramResults(Sequence[ProgramResult]):
    """Source-ordered quantum results with stable name lookup."""

    _values: tuple[ProgramResult, ...]

    @overload
    def __getitem__(self, index: int) -> ProgramResult: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[ProgramResult, ...]: ...

    @overload
    def __getitem__(self, index: str) -> ProgramResult: ...

    @override
    def __getitem__(
        self,
        index: int | slice | str,
    ) -> ProgramResult | tuple[ProgramResult, ...]:
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
    def __iter__(self) -> Iterator[ProgramResult]:
        return iter(self._values)

    def __getattr__(self, result_id: str) -> ProgramResult:
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
    arguments: tuple[tuple[str, ComputeInput], ...]
    compiler_arguments: tuple[tuple[str, ValueRef], ...]
    shots: ComputeInput

    def with_shots(self, shots: ComputeInput, /) -> QuantumProgramCall:
        """Return the same program call with a different acquisition count."""

        return _program_call(
            self.program,
            self.module_invocation.instance_id,
            module=self.module_invocation.module,
            inputs=dict(self.arguments),
            compiler_inputs=dict(self.compiler_arguments),
            shots=shots,
        )

    def with_compiler_inputs(self, **inputs: ValueRef) -> QuantumProgramCall:
        """Bind typed lowering-only values without changing the Program ABI."""

        compiler_inputs = dict(inputs)
        return _program_call(
            self.program,
            self.module_invocation.instance_id,
            module=_program_call_module(
                self.program,
                compiler_input_types={
                    name: value.value_type for name, value in compiler_inputs.items()
                },
            ),
            inputs=dict(self.arguments),
            compiler_inputs=compiler_inputs,
            shots=self.shots,
        )


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


type CircuitArgument = GateArgumentValue | ProgramInput
type QuantumQuantity = Quantity | ProgramInput
type ProgramPort = PulseElement | ProgramInput
type ProgramFunction = Callable[..., QuantumFragment]
type FragmentFunction = Callable[..., QuantumFragment]
type PulseTemplateFunction = Callable[..., QuantumFragment]
type ElementBindings = Mapping[QubitId | CouplerId, QubitId | CouplerId]

_SHOTS_INPUT_ID = "__shots__"
_RESERVED_PROGRAM_PORT_IDS = frozenset({_SHOTS_INPUT_ID})
_RESERVED_RESULT_IDS = frozenset({"count", "index"})
type RepeatCount = int | ProgramInput
type _PulseTemplateArgument = Quantity | int | float | ProgramInput
type PulseElement = Qubit | Coupler
type Gate = SingleQubitGate | TwoQubitGate
type QubitInput = Annotated[
    ExperimentInput[str], EntityAtomType(entity_kind="logical_qubit")
]
type CouplerInput = Annotated[
    ExperimentInput[str], EntityAtomType(entity_kind="logical_coupler")
]


@dataclass(frozen=True, slots=True)
class _QuantumFunctionContract:
    """One decorator function's ordered symbolic port contract."""

    signature: inspect.Signature
    parameters: tuple[ProgramPort, ...]

    @property
    def arguments(self) -> dict[str, ProgramPort]:
        return {
            parameter.name: value
            for parameter, value in zip(
                self.signature.parameters.values(),
                self.parameters,
                strict=True,
            )
        }

    @property
    def elements(self) -> tuple[PulseElement, ...]:
        return tuple(
            parameter
            for parameter in self.parameters
            if isinstance(parameter, Qubit | Coupler)
        )

    @property
    def inputs(self) -> tuple[ProgramInput, ...]:
        return tuple(
            parameter
            for parameter in self.parameters
            if isinstance(parameter, ProgramInput)
        )


QUANTUM_PROGRAM_DIALECT_ID = "scopecat.quantum.program"
QUANTUM_PROGRAM_DIALECT_VERSION = "3"


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
        if isinstance(value, ProgramInput):
            if not _program_input_matches_kind(value, parameter.kind):
                msg = (
                    f"gate {gate_handle.id!r} parameter {parameter.id!r} requires "
                    f"{parameter.kind.value!r}, but input {value.id!r} declares "
                    f"{_describe_program_input(value)!r}"
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
    _bit: RealtimeBit | None = None

    @property
    def bit(self) -> RealtimeBit:
        """Return the explicitly requested realtime discriminator output."""

        if self._bit is None:
            raise ValueError(
                "measurement has no realtime bit; pass bit= when authoring it"
            )
        return self._bit

    @property
    def realtime_bit(self) -> RealtimeBit | None:
        """Return the optional realtime output without requiring one."""

        return self._bit


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class RealtimeBitState(QuantumFragment):
    """Authored target-local bit state carried explicitly across loop rounds."""

    _id: str
    initial: Literal[0, 1]

    @property
    def id(self) -> str:
        return self._id


@dataclass(frozen=True, slots=True, repr=False)
class RealtimeBitRead(QuantumFragment):
    """Read one state cell into an exact realtime value."""

    state: RealtimeBitState
    bit: RealtimeBit


@dataclass(frozen=True, slots=True, repr=False)
class RealtimeXor(QuantumFragment):
    """Define one realtime bit as the XOR of two exact values."""

    left: RealtimeBit
    right: RealtimeBit
    bit: RealtimeBit


@dataclass(frozen=True, slots=True, repr=False)
class RealtimeBitStore(QuantumFragment):
    """Store a realtime value into explicit loop-carried state."""

    state: RealtimeBitState
    source: RealtimeBit


@dataclass(frozen=True, slots=True, repr=False)
class RealtimeBitEmit(QuantumFragment):
    """Emit a realtime value under one target result id."""

    source: RealtimeBit
    result: RealtimeResult


@dataclass(frozen=True, slots=True, repr=False)
class PauliFrameUpdate(QuantumFragment):
    """XOR a realtime value into one logical Pauli-frame component."""

    qubit: Qubit
    axis: Literal["x", "z"]
    source: RealtimeBit


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
class _PulseTemplateSource:
    """Closed pulse-template source retained by a function definition."""

    ir_id: PulseProgramId
    body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[ProgramInput, ...]

    @property
    def id(self) -> str:
        """Return the stable pulse-template identity."""

        return self.ir_id.value


class PulseTemplateDefinition[**P](_PulseTemplateSource):
    """A function-authored pulse template with an inspectable call signature."""

    __slots__ = ("_contract", "_definition")

    _contract: _QuantumFunctionContract
    _definition: Callable[P, QuantumFragment]

    def __init__(
        self,
        declaration: _PulseTemplateSource,
        definition: Callable[P, QuantumFragment],
        contract: _QuantumFunctionContract,
    ) -> None:
        super().__init__(
            ir_id=declaration.ir_id,
            body=declaration.body,
            elements=declaration.elements,
            inputs=declaration.inputs,
        )
        self._definition = definition
        self._contract = contract

    @property
    def parameters(self) -> tuple[ProgramPort, ...]:
        """Return ports in their declared Python order."""

        return self._contract.parameters

    @property
    def __wrapped__(self) -> Callable[P, QuantumFragment]:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._contract.signature.replace(return_annotation=PulseFragment)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> PulseFragment:
        """Instantiate the template in its declared Python parameter order."""

        bound = self._contract.signature.bind(*args, **kwargs)
        return _instantiate_bound_pulse_template(self, bound)


@dataclass(frozen=True, slots=True)
class _GateImplementationContract:
    """Names that attach pulse parameters to their gate-level roles."""

    signature: inspect.Signature
    operands: tuple[str, ...]
    resources: tuple[str, ...]
    arguments: tuple[str, ...]


class GateImplementationDefinition[**P]:
    """A function-authored fixed gate implementation backed by pulse structure."""

    __slots__ = ("_contract", "candidate", "gate", "template")

    gate: Gate
    candidate: str | None
    template: PulseTemplateDefinition[P]
    _contract: _GateImplementationContract

    def __init__(
        self,
        template: PulseTemplateDefinition[P],
        *,
        gate: Gate,
        candidate: str | None,
        contract: _GateImplementationContract,
    ) -> None:
        self.template = template
        self.gate = gate
        self.candidate = candidate
        self._contract = contract

    @property
    def id(self) -> str:
        """Return the stable pulse implementation identity."""

        return self.template.id

    @property
    def parameters(self) -> tuple[PulseElement | ProgramInput, ...]:
        """Return the implementation's typed operands, resources, and inputs."""

        return self.template.parameters

    @property
    def __wrapped__(self) -> Callable[P, QuantumFragment]:
        return self.template.__wrapped__

    @property
    def __name__(self) -> str:
        return self.template.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._contract.signature.replace(return_annotation=QuantumFragment)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> QuantumFragment:
        """Instantiate the pulse and attach its declared gate semantics."""

        bound = self._contract.signature.bind(*args, **kwargs)
        pulse = _instantiate_bound_pulse_template(self.template, bound)
        operands = tuple(
            cast("Qubit", bound.arguments[name]) for name in self._contract.operands
        )
        resources = tuple(
            cast("Coupler", bound.arguments[name]) for name in self._contract.resources
        )
        arguments = {
            name: cast("CircuitArgument", bound.arguments[name])
            for name in self._contract.arguments
        }
        gate_call: CircuitFragment
        if isinstance(self.gate, SingleQubitGate):
            gate_call = self.gate(operands[0], **arguments)
        else:
            gate_call = self.gate(operands[0], operands[1], **arguments)
        return _implement_gate(
            gate_call,
            pulse,
            resources=resources,
            candidate=self.candidate,
        )


@dataclass(frozen=True, slots=True, repr=False)
class FragmentDefinition[**P]:
    """A typed result-free fragment expanded after point inputs bind."""

    id: str
    _definition: Callable[P, QuantumFragment]
    _contract: _QuantumFunctionContract

    @property
    def parameters(self) -> tuple[ProgramPort, ...]:
        """Return ports in their declared Python order."""

        return self._contract.parameters

    @property
    def __wrapped__(self) -> Callable[P, QuantumFragment]:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._contract.signature

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> QuantumFragment:
        """Record one typed call for expansion during program binding."""

        bound = self._contract.signature.bind(*args, **kwargs)
        arguments = tuple(bound.arguments.items())
        _validate_fragment_call_arguments(self, arguments)
        return _FragmentCall(definition=self, arguments=arguments)


@dataclass(frozen=True, slots=True)
class _GateFragment(CircuitFragment):
    gate: Gate
    qubits: tuple[Qubit, ...]
    arguments: tuple[tuple[str, CircuitArgument], ...]


@dataclass(frozen=True, slots=True)
class _SequenceFragment(CircuitFragment):
    operations: tuple[CircuitFragment, ...]
    result_axis: QuantumResultAxis | None = None


@dataclass(frozen=True, slots=True)
class _ParallelFragment(CircuitFragment):
    branches: tuple[CircuitFragment, ...]
    result_axis: QuantumResultAxis | None = None


@dataclass(frozen=True, slots=True)
class _RepeatFragment(CircuitFragment):
    operation: CircuitFragment
    count: int | ProgramInput
    result_axis: QuantumResultAxis | None = None


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
    template: PulseTemplateDefinition[...]
    body: QuantumFragment


@dataclass(frozen=True, slots=True)
class _QuantumSequenceFragment(QuantumFragment):
    operations: tuple[QuantumFragment, ...]
    result_axis: QuantumResultAxis | None = None


@dataclass(frozen=True, slots=True)
class _QuantumParallelFragment(QuantumFragment):
    branches: tuple[QuantumFragment, ...]
    result_axis: QuantumResultAxis | None = None


@dataclass(frozen=True, slots=True)
class _QuantumRepeatFragment(QuantumFragment):
    operation: QuantumFragment
    count: RepeatCount
    result_axis: QuantumResultAxis | None = None


@dataclass(frozen=True, slots=True)
class _QuantumConditionalFragment(QuantumFragment):
    condition: RealtimeBit
    equals: int
    when_true: QuantumFragment
    when_false: QuantumFragment


@dataclass(frozen=True, slots=True)
class _ImplementedGateFragment(QuantumFragment):
    gate: _GateFragment
    pulse: QuantumFragment
    candidate_id: str | None


@dataclass(frozen=True, slots=True)
class _FragmentCall(QuantumFragment):
    definition: FragmentDefinition[...]
    arguments: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class _ExpandedFragment(QuantumFragment):
    definition_id: str
    body: QuantumFragment


@dataclass(frozen=True, slots=True, repr=False)
class Program:
    """A closed symbolic program containing logical and physical statements."""

    ir_id: QuantumProgramId
    body: QuantumFragment
    elements: tuple[PulseElement, ...]
    inputs: tuple[ProgramInput, ...]
    results: ProgramResults
    description: str | None = None

    @property
    def id(self) -> str:
        """Return the stable program identity."""

        return self.ir_id.value

    @property
    def ports(self) -> tuple[ProgramPort, ...]:
        """Return bindable logical elements followed by scalar inputs."""

        return (*self.elements, *self.inputs)

    def describe(self) -> str:
        """Describe the program's typed ports and result contracts as text."""

        return describe(self)

    def draw(self) -> str:
        """Draw the program's recursive source structure as a text tree."""

        return draw(self)


class ProgramDefinition(Program):
    """A function-authored program with an inspectable call signature."""

    __slots__ = ("_call_module", "_contract", "_definition")

    _call_module: ExperimentModule
    _contract: _QuantumFunctionContract
    _definition: ProgramFunction

    def __init__(
        self,
        declaration: Program,
        definition: ProgramFunction,
        contract: _QuantumFunctionContract,
    ) -> None:
        super().__init__(
            ir_id=declaration.ir_id,
            body=declaration.body,
            elements=declaration.elements,
            inputs=declaration.inputs,
            results=declaration.results,
            description=declaration.description,
        )
        self._definition = definition
        self._contract = contract
        self._call_module = _program_call_module(self)

    @property
    def __wrapped__(self) -> ProgramFunction:
        return self._definition

    @property
    def __name__(self) -> str:
        return self._definition.__name__

    @property
    def __signature__(self) -> inspect.Signature:
        return self._contract.signature.replace(
            parameters=tuple(
                parameter.replace(annotation=ComputeInput)
                for parameter in self._contract.signature.parameters.values()
            ),
            return_annotation=QuantumProgramCall,
        )

    def __call__(
        self,
        *args: ComputeInput,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind ports in their declared Python order."""

        bound = self._contract.signature.bind(*args, **inputs)
        return _program_call(
            self,
            self.id.rsplit(".", maxsplit=1)[-1],
            module=self._call_module,
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            compiler_inputs={},
            shots=1,
        )

    def call(
        self,
        instance_id: str,
        /,
        *args: ComputeInput,
        **inputs: ComputeInput,
    ) -> QuantumProgramCall:
        """Bind an explicitly named call in declared port order."""

        bound = self._contract.signature.bind(*args, **inputs)
        return _program_call(
            self,
            instance_id,
            module=self._call_module,
            inputs=cast("Mapping[str, ComputeInput]", bound.arguments),
            compiler_inputs={},
            shots=1,
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


@dataclass(frozen=True, slots=True)
class _InspectionNode:
    label: str
    children: tuple[_InspectionNode, ...] = ()


def describe(program: Program, /) -> str:
    """Return a concise typed declaration summary for ``program``."""

    lines = [f"program {program.id}"]
    if program.description is not None:
        lines.append("description:")
        lines.extend(f"  {line}" for line in program.description.splitlines())
    lines.append("ports:")
    if not program.ports:
        lines.append("  (none)")
    for port in program.ports:
        if isinstance(port, Qubit):
            value_type = "qubit"
        elif isinstance(port, Coupler):
            value_type = "coupler"
        else:
            value_type = _describe_program_input(port)
        lines.append(f"  {port.id}: {value_type}")
    lines.append("results:")
    if not program.results:
        lines.append("  (none)")
    for result in program.results:
        lines.append(f"  {result.id}: {_describe_result(result)}")
    return "\n".join(lines)


def draw(program: Program, /) -> str:
    """Return a dependency-free text tree of ``program`` source structure."""

    root = _InspectionNode(
        label=f"program {program.id}",
        children=(_inspection_node(program.body),),
    )
    lines = [root.label]
    _draw_inspection_children(root.children, prefix="", lines=lines)
    return "\n".join(lines)


def _draw_inspection_children(
    children: tuple[_InspectionNode, ...],
    *,
    prefix: str,
    lines: list[str],
) -> None:
    for index, child in enumerate(children):
        last = index == len(children) - 1
        lines.append(f"{prefix}{'└─' if last else '├─'} {child.label}")
        _draw_inspection_children(
            child.children,
            prefix=prefix + ("   " if last else "│  "),
            lines=lines,
        )


def _inspection_node(fragment: QuantumFragment) -> _InspectionNode:
    if isinstance(fragment, _GateFragment):
        return _InspectionNode(f"gate {_inspection_gate_call(fragment)}")
    if isinstance(fragment, Measurement):
        result = fragment.result
        return _InspectionNode(f"measure {result.qubit.id} -> {result.id}")
    if isinstance(fragment, RealtimeBitState):
        return _InspectionNode(f"bit_state {fragment.id} initial={fragment.initial}")
    if isinstance(fragment, RealtimeBitRead):
        return _InspectionNode(f"read_bit {fragment.state.id} -> {fragment.bit.id}")
    if isinstance(fragment, RealtimeXor):
        return _InspectionNode(
            f"xor_bits {fragment.left.id}, {fragment.right.id} -> {fragment.bit.id}"
        )
    if isinstance(fragment, RealtimeBitStore):
        return _InspectionNode(f"store_bit {fragment.source.id} -> {fragment.state.id}")
    if isinstance(fragment, RealtimeBitEmit):
        return _InspectionNode(f"emit_bit {fragment.source.id} -> {fragment.result.id}")
    if isinstance(fragment, PauliFrameUpdate):
        return _InspectionNode(
            f"pauli_frame_{fragment.axis} {fragment.qubit.id} ^= {fragment.source.id}"
        )
    if isinstance(fragment, Acquisition):
        return _InspectionNode(
            f"acquire {fragment.result.qubit.id} "
            f"duration={_inspection_value(fragment.duration)} -> {fragment.result.id}"
        )
    if isinstance(fragment, _PlayFragment):
        return _InspectionNode(
            f"play {_inspection_signal(fragment.signal)} "
            f"{_inspection_envelope(fragment.envelope)}"
        )
    if isinstance(fragment, _DelayFragment):
        return _InspectionNode(
            f"delay {_inspection_signal(fragment.signal)} "
            f"duration={_inspection_value(fragment.duration)}"
        )
    if isinstance(fragment, _BarrierFragment):
        signals = ", ".join(_inspection_signal(item) for item in fragment.signals)
        return _InspectionNode(f"barrier {signals}")
    if isinstance(fragment, _ShiftPhaseFragment):
        return _InspectionNode(
            f"shift_phase {_inspection_signal(fragment.signal)} "
            f"phase={_inspection_value(fragment.phase)}"
        )
    if isinstance(fragment, _PulseTemplateCallFragment):
        return _InspectionNode(
            f"pulse {fragment.template.id}",
            (_inspection_node(fragment.body),),
        )
    if isinstance(fragment, _ImplementedGateFragment):
        candidate = (
            ""
            if fragment.candidate_id is None
            else f" candidate={fragment.candidate_id!r}"
        )
        return _InspectionNode(
            f"implementation {_inspection_gate_call(fragment.gate)}{candidate}",
            (_inspection_node(fragment.pulse),),
        )
    if isinstance(fragment, _FragmentCall):
        arguments = ", ".join(
            f"{name}={_inspection_value(value)}" for name, value in fragment.arguments
        )
        return _InspectionNode(f"fragment {fragment.definition.id}({arguments})")
    if isinstance(fragment, _ExpandedFragment):
        return _InspectionNode(
            f"fragment {fragment.definition_id}",
            (_inspection_node(fragment.body),),
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        return _InspectionNode(
            f"sequence{_inspection_axis(fragment.result_axis)}",
            tuple(_inspection_node(item) for item in fragment.operations),
        )
    if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        return _InspectionNode(
            f"parallel{_inspection_axis(fragment.result_axis)}",
            tuple(_inspection_node(item) for item in fragment.branches),
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        return _InspectionNode(
            f"repeat {_inspection_value(fragment.count)}"
            f"{_inspection_axis(fragment.result_axis)}",
            (_inspection_node(fragment.operation),),
        )
    if isinstance(fragment, _QuantumConditionalFragment):
        return _InspectionNode(
            f"when {fragment.condition.id} == {fragment.equals}",
            (
                _InspectionNode("true", (_inspection_node(fragment.when_true),)),
                _InspectionNode("false", (_inspection_node(fragment.when_false),)),
            ),
        )
    raise AssertionError(f"unsupported quantum fragment {type(fragment).__name__}")


def _inspection_gate_call(fragment: _GateFragment) -> str:
    arguments = [qubit.id for qubit in fragment.qubits]
    arguments.extend(
        f"{name}={_inspection_value(value)}" for name, value in fragment.arguments
    )
    return f"{fragment.gate.id}({', '.join(arguments)})"


def _inspection_signal(signal: LogicalSignal) -> str:
    if isinstance(signal, DriveSignal):
        return f"drive({signal.qubit.value})"
    if isinstance(signal, ReadoutSignal):
        return f"readout({signal.qubit.value})"
    if isinstance(signal, AcquireSignal):
        return f"acquire({signal.qubit.value})"
    return f"flux({signal.owner.value})"


def _inspection_envelope(envelope: PulseEnvelope | AnalyticEnvelope) -> str:
    if isinstance(envelope, PulseEnvelope):
        kind, duration, amplitude, sigma, beta, phase = _pulse_envelope_parts(envelope)
    elif isinstance(envelope, Constant):
        kind = "constant"
        duration, amplitude = envelope.duration, envelope.amplitude
        sigma, beta, phase = None, None, envelope.phase
    elif isinstance(envelope, Gaussian):
        kind = "gaussian"
        duration, amplitude, sigma = (
            envelope.duration,
            envelope.amplitude,
            envelope.sigma,
        )
        beta, phase = None, envelope.phase
    else:
        kind = "drag"
        duration, amplitude, sigma, beta, phase = (
            envelope.duration,
            envelope.amplitude,
            envelope.sigma,
            envelope.beta,
            envelope.phase,
        )
    fields = [
        f"duration={_inspection_value(duration)}",
        f"amplitude={_inspection_value(amplitude)}",
    ]
    if sigma is not None:
        fields.append(f"sigma={_inspection_value(sigma)}")
    if beta is not None:
        fields.append(f"beta={_inspection_value(beta)}")
    if not _is_zero_phase(phase):
        fields.append(f"phase={_inspection_value(phase)}")
    return f"{kind}({', '.join(fields)})"


def _is_zero_phase(value: QuantumQuantity) -> bool:
    return isinstance(value, Quantity) and value.to("rad").value == 0


def _inspection_axis(axis: QuantumResultAxis | None) -> str:
    if axis is None:
        return ""
    return f" axis={axis.id}:{axis.kind}[{_inspection_value(axis.size)}]"


def _inspection_value(value: object) -> str:
    if isinstance(value, Qubit | Coupler):
        return value.id
    if isinstance(value, ProgramInput):
        return f"${value.id}"
    if isinstance(value, Quantity):
        return f"{value.value:g} {value.unit}"
    return repr(value)


def _describe_program_input(value: ProgramInput) -> str:
    atom = value.value_type.atom
    detail: str | None = None
    if isinstance(atom, QuantityAtomType):
        detail = atom.unit or atom.dimension
    elif isinstance(atom, EntityAtomType):
        detail = atom.entity_kind
    elif isinstance(atom, PayloadType):
        detail = atom.schema_id
    atom_name = type(atom).__name__
    return f"{atom_name}[{detail}]" if detail is not None else atom_name


def _describe_result(result: ProgramResult) -> str:
    contract = result.contract
    axes = ["shot"]
    axes.extend(f"{axis.id}[{_inspection_value(axis.size)}]" for axis in contract.axes)
    unit = "" if contract.unit is None else f" {contract.unit}"
    if isinstance(result, RealtimeResult):
        return f"realtime {contract.dtype}{unit}; axes={' x '.join(axes)}"
    return (
        f"{result.acquisition_kind.value} {contract.dtype}{unit} "
        f"on {result.qubit.id}; axes={' x '.join(axes)}"
    )


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


def scalar_input(id: str, kind: GateParameterKind) -> ProgramInput:  # noqa: A002
    """Declare one typed scalar input port for a symbolic circuit."""

    if not id.strip():
        msg = "circuit input id must be a non-empty string"
        raise ValueError(msg)
    return ProgramInput(_id=id, value_type=_core_input_type(kind))


def input(id: str, value_type: ScalarType) -> ProgramInput:  # noqa: A001, A002
    """Declare one core-typed scalar input for gate-and-pulse authoring."""

    if not id.strip():
        msg = "quantum input id must be a non-empty string"
        raise ValueError(msg)
    if value_type.nullable:
        msg = "quantum program inputs cannot be nullable"
        raise ValueError(msg)
    return ProgramInput(
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
    bit: str | None = None,
    contract: QuantumResultContract = INTEGRATED_IQ_RESULT,
) -> Measurement:
    """Author one measurement and optionally request a realtime bit output."""

    if not result.strip():
        msg = "measurement result id must be a non-empty string"
        raise ValueError(msg)
    if bit is not None and not bit.strip():
        msg = "measurement bit id must be a non-empty string"
        raise ValueError(msg)
    result_handle = MeasurementResult(
        _id=result,
        _qubit=qubit,
        contract=contract,
    )
    return Measurement(
        result=result_handle,
        _bit=None if bit is None else RealtimeBit(bit),
    )


def bit_state(
    id: str,  # noqa: A002
    /,
    *,
    initial: Literal[0, 1] = 0,
) -> RealtimeBitState:
    """Initialize one explicit target-local bit-state cell."""

    if not id.strip():
        raise ValueError("realtime bit state id must be a non-empty string")
    return RealtimeBitState(id, initial)


def read_bit(
    state: RealtimeBitState,
    /,
    *,
    id: str,  # noqa: A002
) -> RealtimeBitRead:
    """Read explicit state into a new exact realtime bit."""

    return RealtimeBitRead(state, RealtimeBit(id))


def xor_bits(
    left: RealtimeBit,
    right: RealtimeBit,
    /,
    *,
    id: str,  # noqa: A002
) -> RealtimeXor:
    """Define one exact realtime XOR value."""

    return RealtimeXor(left, right, RealtimeBit(id))


def store_bit(
    state: RealtimeBitState,
    source: RealtimeBit,
    /,
) -> RealtimeBitStore:
    """Carry a realtime bit through an explicit state cell."""

    return RealtimeBitStore(state, source)


def emit_bit(
    source: RealtimeBit,
    /,
    *,
    result: str,
) -> RealtimeBitEmit:
    """Emit a realtime bit as a target result record."""

    if not result.strip():
        raise ValueError("realtime emitted result id must be a non-empty string")
    return RealtimeBitEmit(source, RealtimeResult(result))


def update_pauli_frame(
    qubit: Qubit,
    source: RealtimeBit,
    /,
    *,
    axis: Literal["x", "z"],
) -> PauliFrameUpdate:
    """XOR a realtime bit into one logical Pauli-frame component."""

    return PauliFrameUpdate(qubit, axis, source)


def acquire(
    qubit: Qubit,
    /,
    *,
    duration: QuantumQuantity,
    result: str,
    contract: QuantumResultContract = INTEGRATED_IQ_RESULT,
) -> Acquisition:
    """Acquire one physical signal and expose its typed result port."""

    _require_quantity_expression(duration, field="duration", kind="time")
    if not result.strip():
        msg = "acquisition result id must be a non-empty string"
        raise ValueError(msg)
    result_handle = MeasurementResult(
        _id=result,
        _qubit=qubit,
        contract=contract,
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


def _close_pulse_template(
    id: str,  # noqa: A002
    body: QuantumFragment,
    /,
    *,
    elements: SequenceCollection[PulseElement],
    formal_inputs: SequenceCollection[ProgramInput] | None = None,
) -> _PulseTemplateSource:
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

    inputs_by_id: dict[str, ProgramInput] = {}
    for input_handle in facts.inputs:
        existing = inputs_by_id.get(input_handle.id)
        if existing is not None and existing is not input_handle:
            msg = (
                f"pulse template input {input_handle.id!r} is declared by multiple "
                "distinct handles"
            )
            raise ValueError(msg)
        inputs_by_id.setdefault(input_handle.id, input_handle)

    selected_inputs = tuple(inputs_by_id.values())
    if formal_inputs is not None:
        declared_inputs = tuple(formal_inputs)
        unused_inputs = tuple(
            input_handle.id
            for input_handle in declared_inputs
            if all(input_handle is not used for used in selected_inputs)
        )
        if unused_inputs:
            rendered = ", ".join(repr(item) for item in unused_inputs)
            raise ValueError(f"pulse template has unused scalar ports: {rendered}")
        foreign_inputs = tuple(
            input_handle.id
            for input_handle in selected_inputs
            if all(input_handle is not declared for declared in declared_inputs)
        )
        if foreign_inputs:
            rendered = ", ".join(repr(item) for item in foreign_inputs)
            raise ValueError(
                f"pulse template captures undeclared scalar ports: {rendered}"
            )
        selected_inputs = declared_inputs

    formal_ids = set(element_ids)
    foreign_owners = {owner for owner in facts.pulse_owners if owner not in formal_ids}
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"pulse template contains undeclared formal elements: {rendered}"
        raise ValueError(msg)

    return _PulseTemplateSource(
        ir_id=PulseProgramId(id),
        body=body,
        elements=raw_elements,
        inputs=selected_inputs,
    )


def materialize_pulse_recipe_body(
    id: str,  # noqa: A002
    body: QuantumFragment,
    /,
    *,
    measurement: tuple[QubitId, AcquisitionKind] | None = None,
) -> PulseProgram:
    """Close one concrete recipe body with framework-owned local identities."""

    expanded = _expand_fragment_calls(body, {})
    facts = _summarize_fragment(expanded)
    if not facts.pulse_only:
        msg = "pulse recipe bodies must contain only pulse statements"
        raise TypeError(msg)
    if facts.inputs:
        rendered = ", ".join(repr(value.id) for value in facts.inputs)
        msg = f"pulse recipe captures unbound inputs: {rendered}"
        raise ValueError(msg)

    slots: tuple[AcquisitionSlot, ...] = ()
    if measurement is None:
        if facts.results:
            msg = "gate pulse recipes cannot acquire results"
            raise ValueError(msg)
    else:
        qubit_id, acquisition_kind = measurement
        if len(facts.results) != 1:
            msg = "measurement pulse recipes must acquire exactly one result"
            raise ValueError(msg)
        result = facts.results[0]
        if not isinstance(result, MeasurementResult):
            raise ValueError("measurement pulse recipes must physically acquire")
        if result.qubit.ir_id != qubit_id:
            msg = "measurement pulse recipe result must belong to its mapped qubit"
            raise ValueError(msg)
        if result.acquisition_kind is not acquisition_kind:
            msg = "measurement pulse recipe result kind must match its declaration"
            raise ValueError(msg)
        slots = (
            AcquisitionSlot(
                id=result.acquisition_slot_id,
                kind=acquisition_kind,
                signal=AcquireSignal(qubit_id),
            ),
        )

    return PulseProgram(
        id=PulseProgramId(id),
        body=_bind_pulse_fragment(
            expanded,
            {},
            element_bindings={},
            path=(),
        ),
        acquisition_slots=slots,
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


def _implement_gate(
    gate_call: CircuitFragment,
    pulse: QuantumFragment,
    /,
    *,
    resources: SequenceCollection[Coupler] = (),
    candidate: str | None = None,
) -> QuantumFragment:
    """Attach validated pulse structure to one logical gate occurrence."""

    if not isinstance(gate_call, _GateFragment):
        msg = "gate implementation requires one authored gate call"
        raise TypeError(msg)
    facts = _summarize_fragment(pulse)
    if not facts.pulse_only:
        msg = "gate implementation must contain only pulse statements"
        raise TypeError(msg)
    if facts.results:
        msg = "gate implementation cannot acquire results"
        raise ValueError(msg)
    selected_resources = tuple(resources)
    resource_ids = tuple(resource.ir_id for resource in selected_resources)
    if len(set(resource_ids)) != len(resource_ids):
        msg = "gate implementation resources must be unique"
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
        msg = f"gate implementation contains unauthorized signal owners: {rendered}"
        raise ValueError(msg)
    used_resources = {owner for owner in pulse_owners if isinstance(owner, CouplerId)}
    unused_resources = set(resource_ids) - used_resources
    if unused_resources:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(unused_resources, key=lambda item: item.value)
        )
        msg = f"gate implementation declares unused coupler resources: {rendered}"
        raise ValueError(msg)
    if candidate is not None and not candidate.strip():
        msg = "gate implementation candidate must be a non-empty string"
        raise ValueError(msg)
    return _ImplementedGateFragment(
        gate=gate_call,
        pulse=pulse,
        candidate_id=candidate,
    )


@overload
def sequence(
    *operations: CircuitFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> CircuitFragment: ...


@overload
def sequence(
    *operations: QuantumFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> QuantumFragment: ...


def sequence(
    *operations: QuantumFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> QuantumFragment:
    """Compose gate, measurement, and pulse fragments in order."""

    if not operations:
        msg = "sequence requires at least one quantum fragment"
        raise ValueError(msg)
    selected, result_axis = _collect_result_axis(
        operations,
        axis=axis,
        axis_kind=axis_kind,
    )
    if all(isinstance(operation, CircuitFragment) for operation in selected):
        return _SequenceFragment(
            operations=cast("tuple[CircuitFragment, ...]", selected),
            result_axis=result_axis,
        )
    return _QuantumSequenceFragment(operations=selected, result_axis=result_axis)


@overload
def parallel(
    *branches: CircuitFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> CircuitFragment: ...


@overload
def parallel(
    *branches: QuantumFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> QuantumFragment: ...


def parallel(
    *branches: QuantumFragment,
    axis: str | None = None,
    axis_kind: str = "collection",
) -> QuantumFragment:
    """Compose two or more gate, measurement, or pulse branches concurrently."""

    if len(branches) < 2:
        msg = "parallel requires at least two quantum branches"
        raise ValueError(msg)
    selected, result_axis = _collect_result_axis(
        branches,
        axis=axis,
        axis_kind=axis_kind,
    )
    if all(isinstance(branch, CircuitFragment) for branch in selected):
        return _ParallelFragment(
            branches=cast("tuple[CircuitFragment, ...]", selected),
            result_axis=result_axis,
        )
    return _QuantumParallelFragment(branches=selected, result_axis=result_axis)


def _collect_result_axis(
    children: tuple[QuantumFragment, ...],
    *,
    axis: str | None,
    axis_kind: str,
) -> tuple[tuple[QuantumFragment, ...], QuantumResultAxis | None]:
    if axis is None:
        return children, None
    summaries = tuple(_summarize_fragment(child) for child in children)
    signatures = tuple(
        tuple((result.id, result.contract) for result in summary.results)
        for summary in summaries
    )
    if not signatures[0] or any(signature != signatures[0] for signature in signatures):
        raise ValueError(
            "result-axis children must produce the same ordered result contracts"
        )
    result_axis = QuantumResultAxis(axis, len(children), axis_kind)
    return (
        tuple(_prepend_result_axis(child, result_axis) for child in children),
        result_axis,
    )


def _prepend_result_axis(
    fragment: QuantumFragment,
    axis: QuantumResultAxis,
) -> QuantumFragment:
    if isinstance(fragment, Measurement):
        return replace(fragment, result=_result_with_axis(fragment.result, axis))
    if isinstance(fragment, Acquisition):
        return replace(fragment, result=_result_with_axis(fragment.result, axis))
    if isinstance(fragment, RealtimeBitEmit):
        return replace(fragment, result=_result_with_axis(fragment.result, axis))
    if isinstance(fragment, _ExpandedFragment):
        return replace(fragment, body=_prepend_result_axis(fragment.body, axis))
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        return replace(
            fragment,
            operations=tuple(
                _prepend_result_axis(operation, axis)
                for operation in fragment.operations
            ),
        )
    if isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        return replace(
            fragment,
            branches=tuple(
                _prepend_result_axis(branch, axis) for branch in fragment.branches
            ),
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        return replace(
            fragment,
            operation=_prepend_result_axis(fragment.operation, axis),
        )
    if isinstance(fragment, _QuantumConditionalFragment):
        return replace(
            fragment,
            when_true=_prepend_result_axis(fragment.when_true, axis),
            when_false=_prepend_result_axis(fragment.when_false, axis),
        )
    return fragment


def _result_with_axis(
    result: ProgramResult,
    axis: QuantumResultAxis,
) -> ProgramResult:
    return replace(
        result,
        contract=replace(
            result.contract,
            axes=(axis, *result.contract.axes),
        ),
    )


@overload
def repeat(
    operation: CircuitFragment,
    count: int | ProgramInput,
    *,
    axis: str | None = None,
) -> CircuitFragment: ...


@overload
def repeat(
    operation: QuantumFragment,
    count: RepeatCount,
    *,
    axis: str | None = None,
) -> QuantumFragment: ...


def repeat(
    operation: QuantumFragment,
    count: RepeatCount,
    *,
    axis: str | None = None,
) -> QuantumFragment:
    """Repeat a fragment, collecting repeated results along a named axis."""

    results = _summarize_fragment(operation).results
    if results and axis is None:
        raise ValueError("result-producing repeats require an axis")
    if not results and axis is not None:
        raise ValueError("result-free repeats cannot declare a result axis")
    if isinstance(count, ProgramInput):
        if not _is_integer_input(count):
            msg = "repeat count inputs must have integer kind"
            raise TypeError(msg)
    elif isinstance(count, bool) or count < 0:
        msg = "repeat count must be a non-negative integer or integer input"
        raise ValueError(msg)
    if results and count == 0:
        raise ValueError("result-producing repeat counts must be positive")
    result_axis = None if axis is None else QuantumResultAxis(axis, count, "repeat")
    selected = (
        operation
        if result_axis is None
        else _prepend_result_axis(operation, result_axis)
    )
    if isinstance(operation, CircuitFragment):
        return _RepeatFragment(
            operation=cast("CircuitFragment", selected),
            count=count,
            result_axis=result_axis,
        )
    return _QuantumRepeatFragment(
        operation=selected,
        count=count,
        result_axis=result_axis,
    )


def when(
    condition: RealtimeBit,
    when_true: QuantumFragment,
    /,
    *,
    otherwise: QuantumFragment | None = None,
    equals: Literal[0, 1] = 1,
) -> QuantumFragment:
    """Execute one result-free branch from a preceding discriminated result."""

    when_false = _QuantumSequenceFragment(()) if otherwise is None else otherwise
    for branch_name, branch in (
        ("when_true", when_true),
        ("otherwise", when_false),
    ):
        if _summarize_fragment(branch).results:
            raise ValueError(
                f"realtime {branch_name} branches cannot produce host results"
            )
    return _QuantumConditionalFragment(
        condition=condition,
        equals=equals,
        when_true=when_true,
        when_false=when_false,
    )


@overload
def fragment[**P](
    definition: Callable[P, QuantumFragment],
    /,
    *,
    id: str | None = None,
) -> FragmentDefinition[P]: ...


@overload
def fragment[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
) -> Callable[[Callable[P, QuantumFragment]], FragmentDefinition[P]]: ...


def fragment[**P](
    definition: Callable[P, QuantumFragment] | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
) -> (
    FragmentDefinition[P]
    | Callable[[Callable[P, QuantumFragment]], FragmentDefinition[P]]
):
    """Define a result-free fragment expanded from concrete point inputs."""

    def decorate(fn: Callable[P, QuantumFragment]) -> FragmentDefinition[P]:
        return _fragment_from_function(fn, id=id)

    return decorate(definition) if definition is not None else decorate


@overload
def pulse_template[**P](
    definition: Callable[P, QuantumFragment],
    /,
    *,
    id: str | None = None,
) -> PulseTemplateDefinition[P]: ...


@overload
def pulse_template[**P](
    definition: None = None,
    /,
    *,
    id: str | None = None,
) -> Callable[[Callable[P, QuantumFragment]], PulseTemplateDefinition[P]]: ...


def pulse_template[**P](
    definition: Callable[P, QuantumFragment] | None = None,
    /,
    *,
    id: str | None = None,  # noqa: A002
) -> (
    PulseTemplateDefinition[P]
    | Callable[[Callable[P, QuantumFragment]], PulseTemplateDefinition[P]]
):
    """Define a reusable pulse fragment from a symbolic Python function."""

    def decorate(fn: Callable[P, QuantumFragment]) -> PulseTemplateDefinition[P]:
        return _pulse_template_from_function(fn, id=id)

    return decorate(definition) if definition is not None else decorate


def implementation[**P](
    *,
    of: Gate,
    candidate: str | None = None,
    id: str | None = None,  # noqa: A002
) -> Callable[
    [Callable[P, QuantumFragment]],
    GateImplementationDefinition[P],
]:
    """Define a fixed semantic gate and its pulse implementation together."""

    def decorate(
        fn: Callable[P, QuantumFragment],
    ) -> GateImplementationDefinition[P]:
        return _gate_implementation_from_function(
            fn,
            gate=of,
            candidate=candidate,
            id=id,
        )

    return decorate


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
    formal_inputs: SequenceCollection[ProgramInput] | None = None,
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
    if formal_inputs is not None:
        formal_element_keys = {
            (type(element), element.id) for element in formal_elements
        }
        foreign_elements = sorted(
            {
                (type(element), element.id)
                for element in facts.element_uses
                if (type(element), element.id) not in formal_element_keys
            },
            key=lambda item: (item[0].__name__, item[1]),
        )
        if foreign_elements:
            rendered = ", ".join(
                repr(element_id) for _type, element_id in foreign_elements
            )
            raise ValueError(
                f"quantum program captures undeclared formal elements: {rendered}"
            )
    collected_inputs = facts.inputs
    inputs_by_id: dict[str, ProgramInput] = {}
    contracts_by_id: dict[str, ScalarType] = {}
    repeat_input_ids = {input_handle.id for input_handle in facts.repeat_inputs}
    result_axis_input_ids = _result_axis_input_ids(facts.results)
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
            positive=input_handle.id in result_axis_input_ids,
        )
        existing_contract = contracts_by_id.get(input_handle.id)
        if existing_contract is not None and existing_contract != contract:
            msg = f"quantum input {input_handle.id!r} has conflicting value types"
            raise ValueError(msg)
        inputs_by_id.setdefault(input_handle.id, input_handle)
        contracts_by_id.setdefault(input_handle.id, contract)

    selected_inputs = tuple(inputs_by_id.values())
    if formal_inputs is not None:
        declared_inputs = tuple(formal_inputs)
        unused_inputs = tuple(
            input_handle.id
            for input_handle in declared_inputs
            if all(input_handle is not used for used in selected_inputs)
        )
        if unused_inputs:
            rendered = ", ".join(repr(item) for item in unused_inputs)
            raise ValueError(f"quantum program has unused scalar ports: {rendered}")
        foreign_inputs = tuple(
            input_handle.id
            for input_handle in selected_inputs
            if all(input_handle is not declared for declared in declared_inputs)
        )
        if foreign_inputs:
            rendered = ", ".join(repr(item) for item in foreign_inputs)
            raise ValueError(
                f"quantum program captures undeclared scalar ports: {rendered}"
            )
        selected_inputs = declared_inputs

    selected_input_ids = {input_handle.id for input_handle in selected_inputs}
    conflicting_ports = sorted(set(element_ids) & selected_input_ids)
    if conflicting_ports:
        rendered = ", ".join(repr(item) for item in conflicting_ports)
        raise ValueError(f"quantum program has conflicting port ids: {rendered}")
    reserved_ports = sorted(
        (set(element_ids) | selected_input_ids) & _RESERVED_PROGRAM_PORT_IDS
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

    _unique_gate_definitions(facts.gate_definitions)

    return Program(
        ir_id=ir_id,
        body=body,
        elements=formal_elements,
        inputs=selected_inputs,
        results=ProgramResults(results),
        description=description,
    )


def _quantum_function_contract(
    fn: Callable[..., QuantumFragment],
    *,
    kind: str,
) -> _QuantumFunctionContract:
    signature = inspect.signature(fn)
    hints = cast("Mapping[str, object]", get_type_hints(fn, include_extras=True))
    parameters: list[ProgramPort] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            raise TypeError(f"{kind} functions require named parameters")
        if cast("object", parameter.default) is not inspect.Parameter.empty:
            raise TypeError(f"{kind} ports cannot declare Python defaults")
        annotation = hints.get(
            parameter.name,
            cast("object", parameter.annotation),
        )
        parameters.append(_program_function_argument(parameter.name, annotation))
    return _QuantumFunctionContract(signature, tuple(parameters))


def _fragment_from_function[**P](
    fn: Callable[P, QuantumFragment],
    *,
    id: str | None,  # noqa: A002
) -> FragmentDefinition[P]:
    contract = _quantum_function_contract(fn, kind="quantum fragment")
    selected_id = id or f"{fn.__module__}.{fn.__qualname__}"
    if not selected_id.strip():
        raise ValueError("quantum fragment id must be non-empty")
    return FragmentDefinition(
        id=selected_id,
        _definition=fn,
        _contract=contract,
    )


def _pulse_template_from_function[**P](
    fn: Callable[P, QuantumFragment],
    *,
    id: str | None,  # noqa: A002
) -> PulseTemplateDefinition[P]:
    contract = _quantum_function_contract(fn, kind="pulse template")
    arguments = contract.arguments
    result = cast("PulseTemplateFunction", fn)(**arguments)
    selected_id = id or f"{fn.__module__}.{fn.__qualname__}"
    declaration = _close_pulse_template(
        selected_id,
        result,
        elements=contract.elements,
        formal_inputs=contract.inputs,
    )
    return PulseTemplateDefinition(
        declaration,
        fn,
        contract,
    )


def _gate_implementation_from_function[**P](
    fn: Callable[P, QuantumFragment],
    *,
    gate: Gate,
    candidate: str | None,
    id: str | None,  # noqa: A002
) -> GateImplementationDefinition[P]:
    if candidate is not None and not candidate.strip():
        raise ValueError("implementation candidate must be a non-empty string")
    template = _pulse_template_from_function(fn, id=id)
    contract = _gate_implementation_contract(template, gate)
    return GateImplementationDefinition(
        template,
        gate=gate,
        candidate=candidate,
        contract=contract,
    )


def _gate_implementation_contract[**P](
    template: PulseTemplateDefinition[P],
    gate: Gate,
) -> _GateImplementationContract:
    operand_count = 1 if isinstance(gate, SingleQubitGate) else 2
    operands = template.parameters[:operand_count]
    if len(operands) != operand_count or any(
        not isinstance(operand, Qubit) for operand in operands
    ):
        msg = (
            f"implementation for gate {gate.id!r} requires "
            f"{operand_count} leading qubits"
        )
        raise TypeError(msg)
    remaining = template.parameters[operand_count:]
    if any(isinstance(parameter, Qubit) for parameter in remaining):
        msg = "implementation resources after gate operands must be couplers"
        raise TypeError(msg)
    inputs = {
        parameter.id: parameter
        for parameter in remaining
        if isinstance(parameter, ProgramInput)
    }
    missing = tuple(
        parameter.id for parameter in gate.parameters if parameter.id not in inputs
    )
    if missing:
        rendered = ", ".join(repr(item) for item in missing)
        raise TypeError(
            f"implementation for gate {gate.id!r} is missing parameters: {rendered}"
        )
    for parameter in gate.parameters:
        input_handle = inputs[parameter.id]
        if not _program_input_matches_kind(input_handle, parameter.kind):
            raise TypeError(
                f"implementation for gate {gate.id!r} parameter "
                f"{parameter.id!r} requires {parameter.kind.value!r}"
            )
    return _GateImplementationContract(
        signature=inspect.signature(template),
        operands=tuple(cast("Qubit", operand).id for operand in operands),
        resources=tuple(
            parameter.id for parameter in remaining if isinstance(parameter, Coupler)
        ),
        arguments=tuple(parameter.id for parameter in gate.parameters),
    )


def _program_from_function(
    fn: ProgramFunction,
    *,
    id: str | None,  # noqa: A002
) -> ProgramDefinition:
    contract = _quantum_function_contract(fn, kind="quantum program")
    arguments = contract.arguments
    result = fn(**arguments)
    declaration = _close_program(
        id or f"{fn.__module__}.{fn.__qualname__}",
        result,
        elements=contract.elements,
        formal_inputs=contract.inputs,
        description=inspect.getdoc(fn),
    )
    return ProgramDefinition(
        declaration,
        fn,
        contract,
    )


def _validate_fragment_call_arguments(
    definition: FragmentDefinition[...],
    arguments: tuple[tuple[str, object], ...],
) -> None:
    if tuple(name for name, _value in arguments) != tuple(
        parameter.id for parameter in definition.parameters
    ):
        raise AssertionError("bound fragment arguments must follow declared ports")
    for (name, actual), formal in zip(
        arguments,
        definition.parameters,
        strict=True,
    ):
        if isinstance(formal, Qubit | Coupler):
            if type(actual) is not type(formal):
                msg = (
                    f"quantum fragment {definition.id!r} port {name!r} requires "
                    f"{type(formal).__name__}"
                )
                raise TypeError(msg)
            continue
        if isinstance(actual, Qubit | Coupler):
            msg = f"quantum fragment {definition.id!r} port {name!r} requires a value"
            raise TypeError(msg)
        if isinstance(actual, ProgramInput):
            expected = _program_input_type(formal, non_negative=False)
            supplied = _program_input_type(actual, non_negative=False)
            if supplied != expected:
                msg = (
                    f"quantum fragment {definition.id!r} port {name!r} requires "
                    f"{expected!r}, but input {actual.id!r} declares {supplied!r}"
                )
                raise TypeError(msg)
            continue
        try:
            coerce_literal(
                _program_input_type(formal, non_negative=False),
                actual,
                path=("fragment", definition.id, name),
            )
        except ValueValidationError as error:
            raise TypeError(str(error)) from error


def _expand_fragment_calls(
    value: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    stack: tuple[FragmentDefinition[...], ...] = (),
) -> QuantumFragment:
    if isinstance(value, _FragmentCall):
        definition = value.definition
        if any(definition is active for active in stack):
            chain = " -> ".join((*tuple(item.id for item in stack), definition.id))
            raise ProgramBindingError(f"quantum fragment expansion cycle: {chain}")
        body = _evaluate_fragment_call(value, bindings)
        expanded = _expand_fragment_calls(
            body,
            bindings,
            stack=(*stack, definition),
        )
        _validate_expanded_fragment(value, expanded)
        return _ExpandedFragment(definition_id=definition.id, body=expanded)
    if isinstance(value, _ExpandedFragment):
        return replace(
            value,
            body=_expand_fragment_calls(value.body, bindings, stack=stack),
        )
    if isinstance(value, _QuantumSequenceFragment):
        return replace(
            value,
            operations=tuple(
                _expand_fragment_calls(operation, bindings, stack=stack)
                for operation in value.operations
            ),
        )
    if isinstance(value, _QuantumParallelFragment):
        return replace(
            value,
            branches=tuple(
                _expand_fragment_calls(branch, bindings, stack=stack)
                for branch in value.branches
            ),
        )
    if isinstance(value, _QuantumRepeatFragment):
        return replace(
            value,
            operation=_expand_fragment_calls(value.operation, bindings, stack=stack),
        )
    if isinstance(value, _QuantumConditionalFragment):
        return replace(
            value,
            when_true=_expand_fragment_calls(value.when_true, bindings, stack=stack),
            when_false=_expand_fragment_calls(value.when_false, bindings, stack=stack),
        )
    return value


def _evaluate_fragment_call(
    call: _FragmentCall,
    bindings: Mapping[str, object],
) -> QuantumFragment:
    resolved: dict[str, object] = {}
    for (name, actual), formal in zip(
        call.arguments,
        call.definition.parameters,
        strict=True,
    ):
        if isinstance(formal, Qubit | Coupler):
            resolved[name] = actual
            continue
        selected = bindings[actual.id] if isinstance(actual, ProgramInput) else actual
        try:
            resolved[name] = coerce_literal(
                _program_input_type(formal, non_negative=False),
                selected,
                path=("fragment", call.definition.id, name),
            )
        except ValueValidationError as error:
            raise ProgramBindingError(str(error)) from error
    return call.definition.__wrapped__(**resolved)


def _validate_expanded_fragment(
    call: _FragmentCall,
    body: QuantumFragment,
) -> None:
    facts = _summarize_fragment(body)
    if facts.results:
        msg = f"quantum fragment {call.definition.id!r} cannot produce results"
        raise ValueError(msg)
    if facts.inputs:
        rendered = ", ".join(repr(value.id) for value in facts.inputs)
        msg = (
            f"quantum fragment {call.definition.id!r} captures unbound inputs: "
            f"{rendered}"
        )
        raise ValueError(msg)
    allowed_elements = {
        (type(value), value.id)
        for _name, value in call.arguments
        if isinstance(value, Qubit | Coupler)
    }
    foreign_elements = {
        (type(value), value.id) for value in facts.element_uses
    } - allowed_elements
    if foreign_elements:
        rendered = ", ".join(
            repr(element_id)
            for _element_type, element_id in sorted(
                foreign_elements,
                key=lambda item: (item[0].__name__, item[1]),
            )
        )
        msg = (
            f"quantum fragment {call.definition.id!r} captures undeclared "
            f"elements: {rendered}"
        )
        raise ValueError(msg)


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
    result_axis_input_ids = _result_axis_input_ids(declaration.results)
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
            positive=input_handle.id in result_axis_input_ids,
        )
        try:
            concrete_bindings[input_handle.id] = coerce_literal(
                value_type,
                selected_bindings[input_handle.id],
                path=("bindings", input_handle.id),
            )
        except ValueValidationError as error:
            raise ProgramBindingError(str(error)) from error

    expanded_body = _expand_fragment_calls(declaration.body, concrete_bindings)
    gate_definitions = _bound_gate_definitions(expanded_body, concrete_bindings)
    realtime_values = _realtime_value_bindings(expanded_body, path=("body",))
    realtime_states = _realtime_state_bindings(expanded_body, path=("body",))
    concrete = QuantumProgramIR(
        id=declaration.ir_id,
        body=_bind_quantum_fragment(
            expanded_body,
            concrete_bindings,
            element_bindings=element_bindings,
            realtime_values=realtime_values,
            realtime_states=realtime_states,
            path=("body",),
        ),
    )
    verified = verify_quantum_program(concrete, gate_definitions)
    return BoundProgram(
        declaration=declaration,
        verified=verified,
    )


def _domain_program(
    declaration: Program,
    *,
    compiler_inputs: Mapping[str, ValueType] | None = None,
) -> DomainProgramDef:
    """Project a unified declaration into core's domain program seam."""

    repeat_input_ids = {
        input_handle.id
        for input_handle in _summarize_fragment(declaration.body).repeat_inputs
    }
    result_axis_input_ids = _result_axis_input_ids(declaration.results)
    return _core_domain_program(
        declaration.id,
        dialect_id=QUANTUM_PROGRAM_DIALECT_ID,
        dialect_version=QUANTUM_PROGRAM_DIALECT_VERSION,
        body=declaration,
        inputs={
            port.id: program_port_type(
                port,
                non_negative=port.id in repeat_input_ids,
                positive=port.id in result_axis_input_ids,
            )
            for port in declaration.ports
        },
        compiler_inputs=compiler_inputs,
        results={result.id: result for result in declaration.results},
    )


def _domain_execution(
    program: DomainProgramDef,
    *,
    id: str | None = None,  # noqa: A002
    inputs: Mapping[ProgramPort, ComputeInput] | None = None,
    compiler_inputs: Mapping[str, ComputeInput] | None = None,
    results: Mapping[ProgramResult, ProductRef] | None = None,
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
    expected_program = _domain_program(
        declaration,
        compiler_inputs={
            port.id: port.value_type for port in program.compiler_input_ports
        },
    )
    if (
        program.id != expected_program.id
        or program.input_ports != expected_program.input_ports
        or program.compiler_input_ports != expected_program.compiler_input_ports
        or program.result_ports != expected_program.result_ports
    ):
        msg = "quantum program domain ports do not match its Program body"
        raise ValueError(msg)
    selected_inputs: Mapping[ProgramPort, ComputeInput] = (
        {} if inputs is None else inputs
    )
    selected_results: Mapping[ProgramResult, ProductRef] = (
        {} if results is None else results
    )
    selected_compiler_inputs: Mapping[str, ComputeInput] = (
        {} if compiler_inputs is None else compiler_inputs
    )
    if set(selected_inputs) != set(declaration.ports):
        msg = "quantum domain execution inputs must bind every declared port"
        raise ValueError(msg)
    if set(selected_results) != set(declaration.results):
        msg = "quantum domain execution results must bind every declared result"
        raise ValueError(msg)
    if set(selected_compiler_inputs) != {
        port.id for port in program.compiler_input_ports
    }:
        msg = "quantum compiler inputs must bind every declared port"
        raise ValueError(msg)
    normalized_inputs = {
        handle.id: (
            float(value)
            if isinstance(handle, ProgramInput)
            and isinstance(handle.value_type.atom, FloatType)
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
        compiler_inputs=selected_compiler_inputs,
        results={handle.id: value for handle, value in selected_results.items()},
    )


def _program_call_module(
    program: Program,
    *,
    compiler_input_types: Mapping[str, ValueType] | None = None,
) -> ExperimentModule:
    """Build the reusable core module owned by one program definition."""

    selected_compiler_input_types = compiler_input_types or {}
    domain = _domain_program(
        program,
        compiler_inputs=selected_compiler_input_types,
    )
    local_inputs = {
        port.id: core_input(port.id, port.value_type) for port in domain.input_ports
    }
    local_compiler_inputs = {
        port.id: core_input(port.id, port.value_type)
        for port in domain.compiler_input_ports
    }
    shots_input = core_input(
        _SHOTS_INPUT_ID,
        ScalarType(IntType(minimum=1)),
    )
    builder = ModuleBuilder(id=f"{program.id}.call").inputs(
        *local_inputs.values(),
        *local_compiler_inputs.values(),
        shots_input,
    )
    for result in program.results:
        contract = result.contract
        builder = builder.product(
            result.id,
            unit=contract.unit,
            dtype=contract.dtype,
            axes=(
                shot_axis(shots_input),
                *(
                    product_axis(
                        axis.id,
                        size=(
                            local_inputs[axis.size.id]
                            if isinstance(axis.size, ProgramInput)
                            else axis.size
                        ),
                        kind=axis.kind,
                        unit=axis.unit,
                    )
                    for axis in contract.axes
                ),
            ),
        )
    execution = _domain_execution(
        domain,
        inputs={port: local_inputs[port.id] for port in program.ports},
        compiler_inputs=local_compiler_inputs,
        results={result: builder.products[result.id] for result in program.results},
    )
    return builder.domain(execution).build()


def _program_call(
    program: Program,
    instance_id: str,
    /,
    *,
    module: ExperimentModule,
    inputs: Mapping[str, ComputeInput],
    compiler_inputs: Mapping[str, ValueRef],
    shots: ComputeInput,
) -> QuantumProgramCall:
    """Instantiate one use of a definition's cached core module."""

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

    invocation = module.instantiate(
        instance_id,
        {
            **inputs,
            **compiler_inputs,
            _SHOTS_INPUT_ID: shots,
        },
    )
    return QuantumProgramCall(
        program=program,
        module_invocation=invocation,
        results=ProductOutputs(
            {result.id: invocation.products[result.id] for result in program.results}
        ),
        arguments=tuple(inputs.items()),
        compiler_arguments=tuple(compiler_inputs.items()),
        shots=shots,
    )


def _core_input_type(
    kind: GateParameterKind,
    *,
    non_negative: bool = False,
    positive: bool = False,
) -> ScalarType:
    if kind is GateParameterKind.INTEGER:
        minimum = 1 if positive else 0 if non_negative else None
        return ScalarType(IntType(minimum=minimum))
    if kind is GateParameterKind.NUMBER:
        return ScalarType(FloatType())
    if kind is GateParameterKind.ANGLE:
        return ScalarType(QuantityType(dimension="phase", unit="rad"))
    raise AssertionError(f"unsupported gate parameter kind {kind!r}")


def program_port_type(
    value: ProgramPort,
    *,
    non_negative: bool = False,
    positive: bool = False,
) -> ScalarType:
    """Return the core value contract for one quantum program port."""

    if isinstance(value, Qubit):
        return ScalarType(EntityType(entity_kind="logical_qubit"))
    if isinstance(value, Coupler):
        return ScalarType(EntityType(entity_kind="logical_coupler"))
    return _program_input_type(
        value,
        non_negative=non_negative,
        positive=positive,
    )


def _bind_fragment(
    fragment: CircuitFragment,
    bindings: Mapping[str, GateArgumentValue],
    *,
    element_bindings: ElementBindings,
    realtime_values: Mapping[RealtimeBit, RealtimeValueId] | None = None,
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
                    bindings[value.id] if isinstance(value, ProgramInput) else value,
                )
                for argument_id, value in fragment.arguments
            ),
        )
    if isinstance(fragment, Measurement):
        result = fragment.result
        return Measure(
            id=CircuitOperationId(_operation_id(path, "measure")),
            qubit=_bound_qubit_id(result.qubit, element_bindings),
            acquisition_slot_id=_physical_result_slot_id(result, path),
            acquisition_kind=result.acquisition_kind,
            realtime_bit_id=(
                None
                if fragment.realtime_bit is None
                else _bound_realtime_value_id(
                    fragment.realtime_bit,
                    realtime_values,
                )
            ),
        )
    if isinstance(fragment, _SequenceFragment):
        return IrSequence(
            tuple(
                _bind_fragment(
                    operation,
                    bindings,
                    element_bindings=element_bindings,
                    realtime_values=realtime_values,
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
                    realtime_values=realtime_values,
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
        if isinstance(fragment.count, ProgramInput)
        else fragment.count
    )
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        input_id = (
            fragment.count.id if isinstance(fragment.count, ProgramInput) else None
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
                realtime_values=realtime_values,
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
    realtime_values: Mapping[RealtimeBit, RealtimeValueId],
    realtime_states: Mapping[RealtimeBitState, RealtimeStateId],
    path: tuple[str, ...],
) -> QuantumNode:
    if isinstance(fragment, _ExpandedFragment):
        return _bind_quantum_fragment(
            fragment.body,
            bindings,
            element_bindings=element_bindings,
            realtime_values=realtime_values,
            realtime_states=realtime_states,
            path=(*path, f"fragment[{fragment.definition_id}]"),
        )
    if isinstance(fragment, _FragmentCall):
        raise AssertionError("quantum fragment calls must expand before binding")
    if isinstance(fragment, _GateFragment | Measurement):
        return cast(
            "GateCall | Measure",
            _bind_fragment(
                fragment,
                cast("Mapping[str, GateArgumentValue]", bindings),
                element_bindings=element_bindings,
                realtime_values=realtime_values,
                path=path,
            ),
        )
    if isinstance(fragment, _ImplementedGateFragment):
        call = _bind_fragment(
            fragment.gate,
            cast("Mapping[str, GateArgumentValue]", bindings),
            element_bindings=element_bindings,
            realtime_values=realtime_values,
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
    if isinstance(fragment, RealtimeBitState):
        return IrRealtimeBitStateInit(
            id=CircuitOperationId(_operation_id(path, "bit-state-init")),
            state_id=_bound_realtime_state_id(fragment, realtime_states),
            value=fragment.initial,
        )
    if isinstance(fragment, RealtimeBitRead):
        return IrRealtimeBitStateRead(
            id=CircuitOperationId(_operation_id(path, "bit-state-read")),
            state_id=_bound_realtime_state_id(fragment.state, realtime_states),
            output_id=_bound_realtime_value_id(fragment.bit, realtime_values),
        )
    if isinstance(fragment, RealtimeBitStore):
        return IrRealtimeBitStateWrite(
            id=CircuitOperationId(_operation_id(path, "bit-state-write")),
            state_id=_bound_realtime_state_id(fragment.state, realtime_states),
            source=RealtimeBitRef(
                _bound_realtime_value_id(fragment.source, realtime_values)
            ),
        )
    if isinstance(fragment, RealtimeXor):
        return IrRealtimeBitXor(
            id=CircuitOperationId(_operation_id(path, "bit-xor")),
            output_id=_bound_realtime_value_id(fragment.bit, realtime_values),
            left=RealtimeBitRef(
                _bound_realtime_value_id(fragment.left, realtime_values)
            ),
            right=RealtimeBitRef(
                _bound_realtime_value_id(fragment.right, realtime_values)
            ),
        )
    if isinstance(fragment, RealtimeBitEmit):
        return IrRealtimeResultEmit(
            id=CircuitOperationId(_operation_id(path, "bit-emit")),
            result_id=_physical_result_slot_id(fragment.result, path),
            source=RealtimeBitRef(
                _bound_realtime_value_id(fragment.source, realtime_values)
            ),
        )
    if isinstance(fragment, PauliFrameUpdate):
        return IrPauliFrameXor(
            id=CircuitOperationId(_operation_id(path, "pauli-frame-xor")),
            qubit=_bound_qubit_id(fragment.qubit, element_bindings),
            axis=fragment.axis,
            source=RealtimeBitRef(
                _bound_realtime_value_id(fragment.source, realtime_values)
            ),
        )
    if isinstance(fragment, Acquisition):
        slot_id = _physical_result_slot_id(fragment.result, path)
        bound_acquire = _bind_pulse_fragment(
            fragment,
            bindings,
            element_bindings=element_bindings,
            path=(),
            acquisition_slot_id=slot_id,
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
                    realtime_values=realtime_values,
                    realtime_states=realtime_states,
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
                    realtime_values=realtime_values,
                    realtime_states=realtime_states,
                    path=(*path, f"parallel[{index}]"),
                )
                for index, branch in enumerate(fragment.branches)
            )
        )
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        count = _bound_repeat_count(fragment.count, bindings)
        return IrQuantumRepeat(
            operation=(
                IrQuantumSequence(())
                if count == 0
                else _bind_quantum_fragment(
                    fragment.operation,
                    bindings,
                    element_bindings=element_bindings,
                    realtime_values=realtime_values,
                    realtime_states=realtime_states,
                    path=(*path, "repeat-body"),
                )
            ),
            count=count,
            axis_id=(None if fragment.result_axis is None else fragment.result_axis.id),
        )
    if isinstance(fragment, _QuantumConditionalFragment):
        return IrQuantumConditional(
            condition=RealtimeBitRef(
                _bound_realtime_value_id(fragment.condition, realtime_values)
            ),
            equals=fragment.equals,
            when_true=_bind_quantum_fragment(
                fragment.when_true,
                bindings,
                element_bindings=element_bindings,
                realtime_values=realtime_values,
                realtime_states=realtime_states,
                path=(*path, "when-true"),
            ),
            when_false=_bind_quantum_fragment(
                fragment.when_false,
                bindings,
                element_bindings=element_bindings,
                realtime_values=realtime_values,
                realtime_states=realtime_states,
                path=(*path, "when-false"),
            ),
        )
    msg = f"unsupported quantum fragment {type(fragment).__name__}"
    raise TypeError(msg)


def _bind_pulse_fragment(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
    acquisition_slot_id: AcquisitionSlotId | None = None,
) -> PulseInstruction:
    if isinstance(fragment, _ExpandedFragment):
        return _bind_pulse_fragment(
            fragment.body,
            bindings,
            element_bindings=element_bindings,
            path=(*path, f"fragment[{fragment.definition_id}]"),
            acquisition_slot_id=acquisition_slot_id,
        )
    if isinstance(fragment, _FragmentCall):
        raise AssertionError("quantum fragment calls must expand before binding")
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
            slot_id=(
                fragment.result.acquisition_slot_id
                if acquisition_slot_id is None
                else acquisition_slot_id
            ),
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


def _physical_result_slot_id(
    result: ProgramResult,
    path: tuple[str, ...],
) -> AcquisitionSlotId:
    acquisition_shape = (
        result.contract.acquisition_shape
        if isinstance(result, MeasurementResult)
        else ()
    )
    collection_axes = tuple(
        axis for axis in result.contract.axes if axis.id not in acquisition_shape
    )
    if not collection_axes:
        return (
            result.acquisition_slot_id
            if isinstance(result, MeasurementResult)
            else result.result_slot_id
        )
    return AcquisitionSlotId(result.id, scope=path)


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
    selected = bindings[value.id] if isinstance(value, ProgramInput) else value
    if not isinstance(selected, Quantity):
        raise AssertionError("verified quantity input must bind to Quantity")
    return selected


def _bound_repeat_count(
    count: RepeatCount,
    bindings: Mapping[str, object],
) -> int:
    selected = bindings[count.id] if isinstance(count, ProgramInput) else count
    if not isinstance(selected, int) or isinstance(selected, bool) or selected < 0:
        input_id = count.id if isinstance(count, ProgramInput) else None
        qualifier = f" input {input_id!r}" if input_id is not None else ""
        msg = f"repeat count{qualifier} must bind to a non-negative integer"
        raise ProgramBindingError(msg)
    return selected


def _bound_gate_definitions(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
) -> tuple[GateDefinition, ...]:
    """Derive the exact gate catalog from the point-bound fragment tree."""

    if isinstance(fragment, _ExpandedFragment):
        return _bound_gate_definitions(fragment.body, bindings)
    if isinstance(fragment, _FragmentCall):
        raise AssertionError("quantum fragment calls must expand before binding")
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if _bound_repeat_count(fragment.count, bindings) == 0:
            return ()
        return _bound_gate_definitions(fragment.operation, bindings)
    if isinstance(fragment, _QuantumConditionalFragment):
        return _unique_gate_definitions(
            (
                *_bound_gate_definitions(fragment.when_true, bindings),
                *_bound_gate_definitions(fragment.when_false, bindings),
            )
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        children = fragment.operations
    elif isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        children = fragment.branches
    else:
        return _unique_gate_definitions(_summarize_fragment(fragment).gate_definitions)
    return _unique_gate_definitions(
        tuple(
            definition
            for child in children
            for definition in _bound_gate_definitions(child, bindings)
        )
    )


def _realtime_value_bindings(
    fragment: QuantumFragment,
    *,
    path: tuple[str, ...],
) -> dict[RealtimeBit, RealtimeValueId]:
    """Resolve authored bit handles to exact producer-scoped SSA identities."""

    selected: dict[RealtimeBit, RealtimeValueId] = {}

    def collect(node: QuantumFragment, node_path: tuple[str, ...]) -> None:
        if isinstance(node, _ExpandedFragment):
            collect(node.body, (*node_path, f"fragment[{node.definition_id}]"))
            return
        bit = (
            node.realtime_bit
            if isinstance(node, Measurement)
            else node.bit
            if isinstance(node, RealtimeBitRead | RealtimeXor)
            else None
        )
        if bit is not None:
            if bit in selected:
                raise ProgramBindingError(
                    f"realtime bit {bit.id!r} has more than one producer"
                )
            selected[bit] = RealtimeValueId(
                bit.id,
                scope=node_path,
            )
            return
        if isinstance(node, _SequenceFragment | _QuantumSequenceFragment):
            for index, operation in enumerate(node.operations):
                collect(operation, (*node_path, f"sequence[{index}]"))
            return
        if isinstance(node, _ParallelFragment | _QuantumParallelFragment):
            for index, branch in enumerate(node.branches):
                collect(branch, (*node_path, f"parallel[{index}]"))
            return
        if isinstance(node, _RepeatFragment | _QuantumRepeatFragment):
            collect(node.operation, (*node_path, "repeat-body"))
            return
        if isinstance(node, _QuantumConditionalFragment):
            collect(node.when_true, (*node_path, "when-true"))
            collect(node.when_false, (*node_path, "when-false"))

    collect(fragment, path)
    return selected


def _realtime_state_bindings(
    fragment: QuantumFragment,
    *,
    path: tuple[str, ...],
) -> dict[RealtimeBitState, RealtimeStateId]:
    """Resolve authored state handles to exact initialization identities."""

    selected: dict[RealtimeBitState, RealtimeStateId] = {}

    def collect(node: QuantumFragment, node_path: tuple[str, ...]) -> None:
        if isinstance(node, _ExpandedFragment):
            collect(node.body, (*node_path, f"fragment[{node.definition_id}]"))
            return
        if isinstance(node, RealtimeBitState):
            if node in selected:
                raise ProgramBindingError(
                    f"realtime state {node.id!r} has more than one initializer"
                )
            selected[node] = RealtimeStateId(node.id, scope=node_path)
            return
        if isinstance(node, _SequenceFragment | _QuantumSequenceFragment):
            for index, operation in enumerate(node.operations):
                collect(operation, (*node_path, f"sequence[{index}]"))
            return
        if isinstance(node, _ParallelFragment | _QuantumParallelFragment):
            for index, branch in enumerate(node.branches):
                collect(branch, (*node_path, f"parallel[{index}]"))
            return
        if isinstance(node, _RepeatFragment | _QuantumRepeatFragment):
            collect(node.operation, (*node_path, "repeat-body"))
            return
        if isinstance(node, _QuantumConditionalFragment):
            collect(node.when_true, (*node_path, "when-true"))
            collect(node.when_false, (*node_path, "when-false"))

    collect(fragment, path)
    return selected


def _bound_realtime_value_id(
    bit: RealtimeBit,
    bindings: Mapping[RealtimeBit, RealtimeValueId] | None,
) -> RealtimeValueId:
    if bindings is not None and bit in bindings:
        return bindings[bit]
    raise ProgramBindingError(
        f"realtime bit {bit.id!r} is not produced by this quantum program"
    )


def _bound_realtime_state_id(
    state: RealtimeBitState,
    bindings: Mapping[RealtimeBitState, RealtimeStateId],
) -> RealtimeStateId:
    if state in bindings:
        return bindings[state]
    raise ProgramBindingError(
        f"realtime state {state.id!r} is not initialized by this quantum program"
    )


def _unique_gate_definitions(
    definitions: Iterable[GateDefinition],
) -> tuple[GateDefinition, ...]:
    by_id: dict[str, GateDefinition] = {}
    for definition in definitions:
        existing = by_id.get(definition.id.value)
        if existing is not None and existing != definition:
            msg = (
                f"quantum program gate {definition.id.value!r} has "
                "conflicting definitions"
            )
            raise ValueError(msg)
        by_id.setdefault(definition.id.value, definition)
    return tuple(by_id.values())


def _instantiate_bound_pulse_template(
    template: PulseTemplateDefinition[...],
    bound: inspect.BoundArguments,
) -> PulseFragment:
    elements: list[PulseElement] = []
    inputs: dict[str, _PulseTemplateArgument] = {}
    for formal in template.parameters:
        actual = cast("object", bound.arguments[formal.id])
        if isinstance(formal, Qubit | Coupler):
            elements.append(cast("PulseElement", actual))
        else:
            inputs[formal.id] = cast("_PulseTemplateArgument", actual)
    return _instantiate_pulse_template(template, tuple(elements), inputs)


def _instantiate_pulse_template(
    template: PulseTemplateDefinition[...],
    elements: tuple[PulseElement, ...],
    inputs: Mapping[str, _PulseTemplateArgument],
) -> PulseFragment:
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
    input_bindings: dict[ProgramInput, Quantity | int | float | ProgramInput] = {}
    for input_id, formal in expected.items():
        selected = inputs[input_id]
        if isinstance(selected, ProgramInput):
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
    input_bindings: Mapping[ProgramInput, Quantity | int | float | ProgramInput],
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
    bindings: Mapping[ProgramInput, Quantity | int | float | ProgramInput],
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
    bindings: Mapping[ProgramInput, Quantity | int | float | ProgramInput],
) -> object:
    return bindings[value] if isinstance(value, ProgramInput) else value


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


def _is_integer_input(value: ProgramInput) -> bool:
    return isinstance(value.value_type.atom, IntType)


def _program_input_type(
    value: ProgramInput,
    *,
    non_negative: bool,
    positive: bool = False,
) -> ScalarType:
    if not non_negative and not positive:
        return value.value_type
    atom = value.value_type.atom
    if not isinstance(atom, IntType):
        raise AssertionError("repeat and result-axis inputs must have an integer type")
    required_minimum = 1 if positive else 0
    minimum = (
        required_minimum
        if atom.minimum is None
        else max(required_minimum, atom.minimum)
    )
    return ScalarType(IntType(minimum=minimum, maximum=atom.maximum))


def _result_axis_input_ids(
    results: Iterable[ProgramResult],
) -> set[str]:
    return {
        axis.size.id
        for result in results
        for axis in result.contract.axes
        if isinstance(axis.size, ProgramInput)
    }


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
    results: tuple[ProgramResult, ...] = ()
    gate_definitions: tuple[GateDefinition, ...] = ()


def _summarize_fragment(fragment: QuantumFragment) -> _FragmentFacts:
    """Collect every closure fact in one structural fragment traversal."""

    if isinstance(fragment, _FragmentCall):
        return _FragmentFacts(
            element_uses=tuple(
                value
                for _name, value in fragment.arguments
                if isinstance(value, Qubit | Coupler)
            ),
            inputs=tuple(
                value
                for _name, value in fragment.arguments
                if isinstance(value, ProgramInput)
            ),
        )
    if isinstance(fragment, _ExpandedFragment):
        return _summarize_fragment(fragment.body)
    if isinstance(fragment, _GateFragment):
        return _FragmentFacts(
            element_uses=fragment.qubits,
            inputs=tuple(
                value
                for _argument_id, value in fragment.arguments
                if isinstance(value, ProgramInput)
            ),
            gate_definitions=(fragment.gate.definition,),
        )
    if isinstance(fragment, Measurement):
        return _FragmentFacts(
            element_uses=(fragment.result.qubit,),
            inputs=tuple(
                axis.size
                for axis in fragment.result.contract.axes
                if isinstance(axis.size, ProgramInput)
            ),
            results=(fragment.result,),
        )
    if isinstance(
        fragment,
        RealtimeBitState | RealtimeBitRead | RealtimeXor | RealtimeBitStore,
    ):
        return _FragmentFacts()
    if isinstance(fragment, RealtimeBitEmit):
        return _FragmentFacts(
            inputs=tuple(
                axis.size
                for axis in fragment.result.contract.axes
                if isinstance(axis.size, ProgramInput)
            ),
            results=(fragment.result,),
        )
    if isinstance(fragment, PauliFrameUpdate):
        return _FragmentFacts(element_uses=(fragment.qubit,))
    if isinstance(fragment, Acquisition):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(fragment.result.qubit,),
            inputs=(
                *(
                    (fragment.duration,)
                    if isinstance(fragment.duration, ProgramInput)
                    else ()
                ),
                *(
                    axis.size
                    for axis in fragment.result.contract.axes
                    if isinstance(axis.size, ProgramInput)
                ),
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
                if isinstance(fragment.duration, ProgramInput)
                else ()
            ),
        )
    if isinstance(fragment, _ShiftPhaseFragment):
        return _FragmentFacts(
            pulse_only=True,
            pulse_owners=(_signal_owner(fragment.signal),),
            element_uses=(_signal_element(fragment.signal),),
            inputs=(
                (fragment.phase,) if isinstance(fragment.phase, ProgramInput) else ()
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
            (fragment.count,) if isinstance(fragment.count, ProgramInput) else ()
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
    if isinstance(fragment, _QuantumConditionalFragment):
        return _merge_fragment_facts(
            (
                _summarize_fragment(fragment.when_true),
                _summarize_fragment(fragment.when_false),
            ),
            carries_pulse_structure=False,
        )
    if isinstance(fragment, _SequenceFragment | _QuantumSequenceFragment):
        children = fragment.operations
    elif isinstance(fragment, _ParallelFragment | _QuantumParallelFragment):
        children = fragment.branches
    else:
        raise AssertionError(f"unsupported quantum fragment {type(fragment).__name__}")
    child_facts = tuple(_summarize_fragment(child) for child in children)
    merged = _merge_fragment_facts(
        child_facts,
        carries_pulse_structure=isinstance(
            fragment,
            _QuantumSequenceFragment | _QuantumParallelFragment,
        ),
    )
    if fragment.result_axis is None:
        return merged
    return replace(merged, results=child_facts[0].results)


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
) -> tuple[ProgramInput, ...]:
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
        if isinstance(value, ProgramInput)
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


def _program_input_matches_kind(
    value: ProgramInput,
    kind: GateParameterKind,
) -> bool:
    atom = value.value_type.atom
    if kind is GateParameterKind.INTEGER:
        return isinstance(atom, IntType)
    if kind is GateParameterKind.NUMBER:
        return isinstance(atom, IntType | FloatType)
    if kind is not GateParameterKind.ANGLE or not isinstance(atom, QuantityType):
        return False
    if atom.dimension == "phase":
        return True
    if atom.unit is None:
        return False
    return _quantity_converts_to(Quantity(1, atom.unit), "rad")


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(values)
    return tuple(sorted(value for value in set(selected) if selected.count(value) > 1))


__all__ = [
    "INTEGRATED_IQ_RESULT",
    "QUANTUM_PROGRAM_DIALECT_ID",
    "QUANTUM_PROGRAM_DIALECT_VERSION",
    "REALTIME_BIT_RESULT",
    "Acquisition",
    "BoundProgram",
    "CircuitArgument",
    "CircuitFragment",
    "Coupler",
    "CouplerInput",
    "FragmentDefinition",
    "Gate",
    "GateImplementationDefinition",
    "Measurement",
    "MeasurementResult",
    "PauliFrameUpdate",
    "Program",
    "ProgramBindingError",
    "ProgramDefinition",
    "ProgramInput",
    "ProgramPort",
    "ProgramResult",
    "ProgramResults",
    "PulseElement",
    "PulseEnvelope",
    "PulseFragment",
    "PulseTemplateDefinition",
    "QuantumFragment",
    "QuantumProgramCall",
    "QuantumQuantity",
    "QuantumResultAxis",
    "QuantumResultContract",
    "Qubit",
    "QubitInput",
    "RealtimeBit",
    "RealtimeBitEmit",
    "RealtimeBitRead",
    "RealtimeBitState",
    "RealtimeBitStore",
    "RealtimeResult",
    "RealtimeResultContract",
    "RealtimeXor",
    "RepeatCount",
    "SingleQubitGate",
    "TwoQubitGate",
    "acquire",
    "barrier",
    "bind",
    "bit_state",
    "constant",
    "coupler",
    "delay",
    "describe",
    "drag",
    "draw",
    "drive",
    "emit_bit",
    "flux",
    "fragment",
    "gate",
    "gaussian",
    "implementation",
    "input",
    "integrated_iq_result",
    "measure",
    "parallel",
    "play",
    "program",
    "program_port_type",
    "pulse_template",
    "qubit",
    "raw_trace_result",
    "read_bit",
    "readout",
    "repeat",
    "scalar_input",
    "sequence",
    "shift_phase",
    "single_qubit_gate",
    "store_bit",
    "two_qubit_gate",
    "update_pauli_frame",
    "when",
    "xor_bits",
]
