# pyright: reportPrivateUsage=false
"""Binding and lowering from symbolic fragments to verified quantum IR."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import (
    cast,
)

from scopecat import Quantity
from scopecat.kernel.entity import EntityRef
from scopecat.program.value_types import ValueValidationError, coerce_literal

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    CouplerId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import (
    GateArgument,
    GateArgumentValue,
    GateCall,
    GateDefinition,
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
from scopecat_quantum.programs import ParallelEach as IrQuantumParallelEach
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
    ElementBindings,
    Measurement,
    ProgramBindingError,
    ProgramInput,
    ProgramResults,
    PulseEnvelope,
    QuantumFragment,
    QuantumQuantity,
    Qubit,
    QubitSet,
    RepeatCount,
    _DelayFragment,
    _ExpandedFragment,
    _FragmentCall,
    _GateFragment,
    _ImplementedGateFragment,
    _ParallelEachFragment,
    _ParallelFragment,
    _PlayFragment,
    _PulseTemplateCallFragment,
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

        return self.verified.unresolved.gate_definitions

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
    for entity_set in declaration.entity_sets:
        concrete_bindings[entity_set.id] = _bound_qubit_set(
            entity_set,
            selected_bindings[entity_set.id],
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

    expanded_body = _expand_fragment_calls(declaration.body, concrete_bindings)
    gate_definitions = _bound_gate_definitions(expanded_body, concrete_bindings)
    concrete = QuantumProgramIR(
        id=declaration.ir_id,
        body=_bind_quantum_fragment(
            expanded_body,
            concrete_bindings,
            element_bindings=element_bindings,
            path=("body",),
        ),
    )
    verified = verify_quantum_program(concrete, gate_definitions)
    return BoundProgram(
        declaration=declaration,
        verified=verified,
    )


def _bind_circuit_operation(
    fragment: _GateFragment | Measurement,
    bindings: Mapping[str, GateArgumentValue],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
    acquisition_scope: tuple[str, ...],
) -> GateCall | Measure:
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
    result = fragment.result
    return Measure(
        id=CircuitOperationId(_operation_id(path, "measure")),
        qubit=_bound_qubit_id(result.qubit, element_bindings),
        acquisition_slot_id=result.acquisition_slot_id.prefixed(*acquisition_scope),
        acquisition_kind=result.acquisition_kind,
    )


def _bind_quantum_fragment(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
    *,
    element_bindings: ElementBindings,
    path: tuple[str, ...],
    acquisition_scope: tuple[str, ...] = (),
) -> QuantumNode:
    if isinstance(fragment, _ExpandedFragment):
        return _bind_quantum_fragment(
            fragment.body,
            bindings,
            element_bindings=element_bindings,
            path=(*path, f"fragment[{fragment.definition_id}]"),
            acquisition_scope=acquisition_scope,
        )
    if isinstance(fragment, _FragmentCall):
        raise AssertionError("quantum fragment calls must expand before binding")
    if isinstance(fragment, _GateFragment | Measurement):
        return _bind_circuit_operation(
            fragment,
            cast("Mapping[str, GateArgumentValue]", bindings),
            element_bindings=element_bindings,
            path=path,
            acquisition_scope=acquisition_scope,
        )
    if isinstance(fragment, _ImplementedGateFragment):
        call = cast(
            "GateCall",
            _bind_circuit_operation(
                fragment.gate,
                cast("Mapping[str, GateArgumentValue]", bindings),
                element_bindings=element_bindings,
                path=(*path, "logical"),
                acquisition_scope=acquisition_scope,
            ),
        )
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
        slot_id = fragment.result.acquisition_slot_id.prefixed(*acquisition_scope)
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
        _PlayFragment | _DelayFragment | _ShiftPhaseFragment,
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
    if isinstance(fragment, _ParallelEachFragment):
        entities = bindings[fragment.entity_set.id]
        if not isinstance(entities, tuple):
            raise AssertionError("verified qubit-set bindings must be tuples")
        entity_refs = cast("tuple[EntityRef, ...]", entities)
        return IrQuantumParallelEach(
            entity_set_id=fragment.entity_set.id,
            entity_ids=tuple(QubitId(entity.id) for entity in entity_refs),
            branches=tuple(
                _bind_quantum_fragment(
                    fragment.operation,
                    bindings,
                    element_bindings={
                        **element_bindings,
                        fragment.entity_set.item.ir_id: QubitId(entity.id),
                    },
                    path=(*path, f"parallel_each[{index}]"),
                    acquisition_scope=(
                        *acquisition_scope,
                        f"{fragment.entity_set.id}[{index}]",
                    ),
                )
                for index, entity in enumerate(entity_refs)
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
                    acquisition_scope=acquisition_scope,
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
                    acquisition_scope=acquisition_scope,
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
                    path=(*path, "repeat-body"),
                    acquisition_scope=acquisition_scope,
                )
            ),
            count=count,
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


def _bound_qubit_set(entity_set: QubitSet, value: object) -> tuple[EntityRef, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ProgramBindingError(
            f"bindings.{entity_set.id}: expected a sequence of logical qubits"
        )
    rows = tuple(
        dict(cast("Mapping[str, object]", item))
        if isinstance(item, Mapping)
        else {"qubit": item}
        for item in value
    )
    try:
        normalized = coerce_literal(
            entity_set.value_type,
            rows,
            path=("bindings", entity_set.id),
        )
    except ValueValidationError as error:
        raise ProgramBindingError(str(error)) from error
    entities = tuple(
        cast("EntityRef", row["qubit"])
        for row in cast("tuple[dict[str, object], ...]", normalized)
    )
    if not entities:
        raise ProgramBindingError(
            f"bindings.{entity_set.id}: qubit set must not be empty"
        )
    return entities


def _bound_gate_definitions(
    fragment: QuantumFragment,
    bindings: Mapping[str, object],
) -> tuple[GateDefinition, ...]:
    """Derive the exact gate catalog from the point-bound fragment tree."""

    if isinstance(fragment, _ExpandedFragment):
        return _bound_gate_definitions(fragment.body, bindings)
    if isinstance(fragment, _FragmentCall):
        raise AssertionError("quantum fragment calls must expand before binding")
    if isinstance(fragment, _ParallelEachFragment):
        return _bound_gate_definitions(fragment.operation, bindings)
    if isinstance(fragment, _RepeatFragment | _QuantumRepeatFragment):
        if _bound_repeat_count(fragment.count, bindings) == 0:
            return ()
        return _bound_gate_definitions(fragment.operation, bindings)
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


def _bound_qubit_id(qubit: Qubit, bindings: ElementBindings) -> QubitId:
    selected = bindings.get(qubit.ir_id, qubit.ir_id)
    if not isinstance(selected, QubitId):
        raise AssertionError("qubit ports must bind to logical qubits")
    return selected
