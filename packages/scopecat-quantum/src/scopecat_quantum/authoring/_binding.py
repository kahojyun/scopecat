# pyright: reportPrivateUsage=false
"""Binding and lowering from symbolic fragments to verified quantum IR."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import (
    cast,
)

from scopecat import Quantity
from scopecat.authoring.value_types import ValueValidationError, coerce_literal
from scopecat.kernel.entity import EntityRef

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    CouplerId,
    PulseEventId,
    PulseProgramId,
    QubitId,
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
    FrameSignal,
    Gaussian,
    Play,
    PlaySignal,
    PulseInstruction,
    PulseProgram,
    ShiftPhase,
)
from scopecat_quantum.pulses import Parallel as IrPulseParallel
from scopecat_quantum.pulses import Sequence as IrPulseSequence

from ._analysis import (
    _operation_id,
    _program_input_type,
    _pulse_envelope_parts,
    _result_axis_input_ids,
    _summarize_fragment,
    _unique_gate_definitions,
    program_port_type,
)
from ._definitions import (
    _substitute_signal,
)
from ._expansion import (
    _expand_fragment_calls,
)
from ._ir import (
    Acquisition,
    CircuitFragment,
    ElementBindings,
    Measurement,
    ProgramBindingError,
    ProgramInput,
    ProgramResult,
    ProgramResults,
    PulseEnvelope,
    QuantumFragment,
    QuantumQuantity,
    Qubit,
    RealtimeBit,
    RepeatCount,
    _BarrierFragment,
    _DelayFragment,
    _ExpandedFragment,
    _FragmentCall,
    _GateFragment,
    _ImplementedGateFragment,
    _ParallelFragment,
    _PlayFragment,
    _PulseTemplateCallFragment,
    _QuantumConditionalFragment,
    _QuantumParallelFragment,
    _QuantumRepeatFragment,
    _QuantumSequenceFragment,
    _RepeatFragment,
    _SequenceFragment,
    _ShiftPhaseFragment,
)
from ._programs import (
    Program,
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


def materialize_pulse_recipe_body(
    id: str,
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
    concrete = QuantumProgramIR(
        id=declaration.ir_id,
        body=_bind_quantum_fragment(
            expanded_body,
            concrete_bindings,
            element_bindings=element_bindings,
            realtime_values=realtime_values,
            path=("body",),
        ),
    )
    verified = verify_quantum_program(concrete, gate_definitions)
    return BoundProgram(
        declaration=declaration,
        verified=verified,
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
    path: tuple[str, ...],
) -> QuantumNode:
    if isinstance(fragment, _ExpandedFragment):
        return _bind_quantum_fragment(
            fragment.body,
            bindings,
            element_bindings=element_bindings,
            realtime_values=realtime_values,
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
                path=(*path, "when-true"),
            ),
            when_false=_bind_quantum_fragment(
                fragment.when_false,
                bindings,
                element_bindings=element_bindings,
                realtime_values=realtime_values,
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
    if not result.contract.axes:
        return result.acquisition_slot_id
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
        bit = node.realtime_bit if isinstance(node, Measurement) else None
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


def _bound_realtime_value_id(
    bit: RealtimeBit,
    bindings: Mapping[RealtimeBit, RealtimeValueId] | None,
) -> RealtimeValueId:
    if bindings is not None and bit in bindings:
        return bindings[bit]
    raise ProgramBindingError(
        f"realtime bit {bit.id!r} is not produced by this quantum program"
    )


def _bound_qubit_id(qubit: Qubit, bindings: ElementBindings) -> QubitId:
    selected = bindings.get(qubit.ir_id, qubit.ir_id)
    if not isinstance(selected, QubitId):
        raise AssertionError("qubit ports must bind to logical qubits")
    return selected
