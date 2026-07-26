# pyright: reportPrivateUsage=false, reportUnusedFunction=false
"""Structural analysis and value typing for quantum authoring."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import (
    Annotated,
    cast,
    get_args,
    get_origin,
)

from scopecat import Quantity
from scopecat.authoring import (
    EntityType,
    FloatType,
    IntType,
    QuantityType,
    ScalarType,
)
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
from scopecat.kernel.entity import EntityRef

from scopecat_quantum._ids import (
    CouplerId,
    QubitId,
)
from scopecat_quantum.gates import (
    GateDefinition,
    GateParameterKind,
)
from scopecat_quantum.pulses import (
    AnalyticEnvelope,
    FluxSignal,
    LogicalSignal,
)

from ._ir import (
    Acquisition,
    Coupler,
    Measurement,
    ProgramInput,
    ProgramPort,
    ProgramResult,
    PulseElement,
    PulseEnvelope,
    QuantumFragment,
    QuantumQuantity,
    Qubit,
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
        return Qubit(ir_id=QubitId(name))
    if annotation is Coupler:
        return Coupler(ir_id=CouplerId(name))
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
            return ProgramInput(_id=name, value_type=_core_input_type(gate_kinds[0]))
        value_type = _quantum_scalar_type(scalar_types[0])
        if not _program_python_type_matches_scalar(python_type, value_type):
            raise TypeError(
                f"quantum program port {name!r} Python annotation is "
                f"incompatible with {value_type!r}"
            )
        return ProgramInput(_id=name, value_type=value_type)
    if annotation is int:
        return ProgramInput(
            _id=name,
            value_type=_core_input_type(GateParameterKind.INTEGER),
        )
    if annotation is float:
        return ProgramInput(
            _id=name,
            value_type=_core_input_type(GateParameterKind.NUMBER),
        )
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
