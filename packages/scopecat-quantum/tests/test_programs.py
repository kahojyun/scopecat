from __future__ import annotations

from decimal import Decimal

import pytest
from scopecat import Quantity

from scopecat_quantum import (
    DRAG,
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CircuitOperationId,
    Constant,
    Delay,
    DriveSignal,
    GateCall,
    GateDefinition,
    GateId,
    GatePulseImplementation,
    GatePulseImplementationKey,
    Measure,
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    Play,
    PulseEventId,
    PulseImplementationId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    ReadoutSignal,
    ResolvedPulseImplementations,
    schedule,
)
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    ImplementedGate,
    ImplementedGatePulseEventProvenance,
    PulseBlock,
    QuantumProgramIR,
    QuantumProgramVerificationError,
    Sequence,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
)

X90 = GateDefinition(GateId("x90"), qubit_arity=1)
Q0 = QubitId("q0")


def _gate_call(operation_id: str) -> GateCall:
    return GateCall(
        id=CircuitOperationId(operation_id),
        gate_id=X90.id,
        qubits=(Q0,),
    )


def _gate_template(program_id: str = "x90-reference") -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Delay(
            id=PulseEventId("drive"),
            signal=DriveSignal(Q0),
            duration=Quantity(16, "ns"),
        ),
    )


def _drag_template(program_id: str = "x90-drag-candidate") -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drag"),
            signal=DriveSignal(Q0),
            envelope=DRAG(
                duration=Quantity(16, "ns"),
                amplitude=Quantity(0.2, "arb"),
                sigma=Quantity(4, "ns"),
                beta=Quantity(0.75, "ns"),
            ),
        ),
    )


def _measurement(operation_id: str = "measure") -> Measure:
    return Measure(
        id=CircuitOperationId(operation_id),
        qubit=Q0,
        acquisition_slot_id=AcquisitionSlotId("result"),
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )


def _measurement_template() -> PulseProgram:
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(Q0),
    )
    duration = Quantity(8, "ns")
    return PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(Q0),
                    envelope=Constant(
                        duration=duration,
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=slot.signal,
                    slot_id=slot.id,
                    duration=duration,
                ),
            )
        ),
        acquisition_slots=(slot,),
    )


def _implementations(
    reference: GateCall, measurement: Measure
) -> ResolvedPulseImplementations:
    return ResolvedPulseImplementations(
        gates=(
            GatePulseImplementation(
                id=PulseImplementationId("x90-q0"),
                key=GatePulseImplementationKey.from_call(reference),
                pulse_template=_gate_template(),
            ),
        ),
        measurements=(
            MeasurementPulseImplementation(
                id=PulseImplementationId("readout-q0"),
                key=MeasurementPulseImplementationKey.from_measurement(measurement),
                pulse_template=_measurement_template(),
            ),
        ),
    )


def test_mixed_program_refines_only_unimplemented_operations() -> None:
    reference = _gate_call("reference-x90")
    candidate_call = _gate_call("candidate-x90")
    measurement = _measurement()
    source = QuantumProgramIR(
        id=QuantumProgramId("drag-sweep-point"),
        body=Sequence(
            (
                reference,
                ImplementedGate(
                    call=candidate_call,
                    pulse_template=_drag_template(),
                    candidate_id="x90.drag",
                ),
                measurement,
            )
        ),
    )

    verified = verify_quantum_program(source, (X90,))
    lowered = lower_quantum_program_to_pulses(
        verified,
        _implementations(reference, measurement),
        output_id=PulseProgramId("drag-sweep-point-pulses"),
    )

    assert tuple(operation.id for operation in verified.logical_circuit.operations) == (
        reference.id,
        candidate_call.id,
        measurement.id,
    )
    assert lowered.implementation_bindings.operation_ids == (
        reference.id,
        measurement.id,
    )
    assert schedule(lowered.program).duration_seconds == Decimal("40e-9")
    assert tuple(type(item) for item in lowered.event_provenance) == (
        # The logical reference and measurement retain implementation provenance.
        type(lowered.event_provenance[0]),
        ImplementedGatePulseEventProvenance,
        type(lowered.event_provenance[0]),
        type(lowered.event_provenance[0]),
    )
    candidate_origin = lowered.event_provenance[1]
    assert isinstance(candidate_origin, ImplementedGatePulseEventProvenance)
    assert candidate_origin.operation_id == candidate_call.id
    assert candidate_origin.candidate_id == "x90.drag"
    assert candidate_origin.event_id.scope[:4] == (
        "programs",
        source.id.value,
        "operations",
        candidate_call.id.value,
    )
    assert all(
        lowered.provenance_for(origin.event_id) is origin
        for origin in lowered.event_provenance
    )
    assert all(
        lowered.acquisition_provenance_for(origin.acquisition_slot_id) is origin
        for origin in lowered.acquisition_provenance
    )


def test_authored_pulse_block_can_own_an_acquisition() -> None:
    template = _measurement_template()
    block = PulseBlock(
        id=CircuitOperationId("inline-readout"),
        pulse_template=template,
    )
    verified = verify_quantum_program(
        QuantumProgramIR(QuantumProgramId("inline-pulse"), block),
        (),
    )

    lowered = lower_quantum_program_to_pulses(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("inline-pulse-lowered"),
    )

    assert lowered.implementation_bindings.operation_ids == ()
    assert all(
        isinstance(item, AuthoredPulseEventProvenance)
        for item in lowered.event_provenance
    )
    [acquisition_origin] = lowered.acquisition_provenance
    assert isinstance(acquisition_origin, AuthoredPulseAcquisitionProvenance)
    assert acquisition_origin.source_id == block.id
    assert acquisition_origin.template_acquisition_slot_id == (
        template.acquisition_slots[0].id
    )
    assert acquisition_origin.acquisition_slot_id.scope[:4] == (
        "programs",
        verified.program.id.value,
        "operations",
        block.id.value,
    )
    assert schedule(lowered.program).duration_seconds == Decimal("8e-9")


def test_authored_pulse_block_can_bind_a_template_slot_to_a_public_slot() -> None:
    template = _measurement_template()
    template_slot = template.acquisition_slots[0].id
    public_slot = AcquisitionSlotId("public-iq")
    block = PulseBlock(
        id=CircuitOperationId("explicit-readout"),
        pulse_template=template,
        acquisition_slot_bindings=((template_slot, public_slot),),
    )
    verified = verify_quantum_program(
        QuantumProgramIR(QuantumProgramId("explicit-readout"), block),
        (),
    )

    lowered = lower_quantum_program_to_pulses(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("explicit-readout-lowered"),
    )

    assert lowered.program.acquisition_slots[0].id == public_slot
    [origin] = lowered.acquisition_provenance
    assert origin.acquisition_slot_id == public_slot
    assert origin.template_acquisition_slot_id == template_slot


def test_pulse_block_rejects_invalid_acquisition_slot_bindings() -> None:
    template = _measurement_template()
    template_slot = template.acquisition_slots[0].id
    block = PulseBlock(
        id=CircuitOperationId("invalid-bindings"),
        pulse_template=template,
        acquisition_slot_bindings=(
            (template_slot, AcquisitionSlotId("same-output")),
            (template_slot, AcquisitionSlotId("same-output")),
            (AcquisitionSlotId("unknown"), AcquisitionSlotId("other")),
        ),
    )

    with pytest.raises(QuantumProgramVerificationError) as caught:
        verify_quantum_program(
            QuantumProgramIR(QuantumProgramId("invalid-bindings"), block),
            (),
        )

    assert {issue.code for issue in caught.value.issues} == {
        "quantum_pulse_acquisition_binding_duplicate",
        "quantum_pulse_acquisition_binding_unknown",
        "quantum_pulse_acquisition_output_duplicate",
    }


def test_pulse_blocks_reject_a_shared_explicit_acquisition_output() -> None:
    template = _measurement_template()
    template_slot = template.acquisition_slots[0].id
    shared_output = AcquisitionSlotId("shared-output")
    first = PulseBlock(
        id=CircuitOperationId("first-readout"),
        pulse_template=template,
        acquisition_slot_bindings=((template_slot, shared_output),),
    )
    second = PulseBlock(
        id=CircuitOperationId("second-readout"),
        pulse_template=template,
        acquisition_slot_bindings=((template_slot, shared_output),),
    )

    with pytest.raises(QuantumProgramVerificationError) as caught:
        verify_quantum_program(
            QuantumProgramIR(
                QuantumProgramId("shared-explicit-output"),
                Sequence((first, second)),
            ),
            (),
        )

    [issue] = caught.value.issues
    assert issue.code == "quantum_pulse_acquisition_output_duplicate"
    assert issue.operation_id == second.id


def test_explicit_acquisition_output_cannot_collide_with_a_default_output() -> None:
    template = _measurement_template()
    template_slot = template.acquisition_slots[0].id
    program_id = QuantumProgramId("explicit-default-output-conflict")
    default_block = PulseBlock(
        id=CircuitOperationId("default-readout"),
        pulse_template=template,
    )
    default_output = template_slot.prefixed(
        "programs",
        program_id.value,
        "operations",
        default_block.id.value,
    )
    explicit_block = PulseBlock(
        id=CircuitOperationId("explicit-readout"),
        pulse_template=template,
        acquisition_slot_bindings=((template_slot, default_output),),
    )

    with pytest.raises(QuantumProgramVerificationError) as caught:
        verify_quantum_program(
            QuantumProgramIR(
                program_id,
                Sequence((explicit_block, default_block)),
            ),
            (),
        )

    [issue] = caught.value.issues
    assert issue.code == "quantum_pulse_acquisition_output_duplicate"
    assert issue.operation_id == default_block.id


def test_gate_implementation_rejects_acquisition_side_effects() -> None:
    source = QuantumProgramIR(
        id=QuantumProgramId("invalid-candidate"),
        body=ImplementedGate(
            call=_gate_call("candidate"),
            pulse_template=_measurement_template(),
        ),
    )

    with pytest.raises(QuantumProgramVerificationError) as caught:
        verify_quantum_program(source, (X90,))

    assert {issue.code for issue in caught.value.issues} == {
        "quantum_gate_implementation_acquisition_unsupported"
    }
