from __future__ import annotations

from decimal import Decimal

import pytest
from scopecat import Quantity

from scopecat_quantum import programs as program_module
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import CircuitVerificationError, Measure
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.programs import (
    ImplementedGate,
    Parallel,
    ParallelEach,
    PulseBlock,
    QuantumProgramExpansionError,
    QuantumProgramIR,
    QuantumProgramVerificationError,
    Repeat,
    Sequence,
    materialize_quantum_pulse_program,
    plan_quantum_pulse_lowering,
    verify_quantum_program,
)
from scopecat_quantum.pulse_implementations import (
    GatePulseImplementation,
    GatePulseImplementationKey,
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    ResolvedPulseImplementations,
)
from scopecat_quantum.pulses import (
    DRAG,
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
    iter_pulse_leaves,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel

X90 = GateDefinition(GateId("x90"), qubit_arity=1)
Q0 = QubitId("q0")


def _gate_call(operation_id: str) -> GateCall:
    return GateCall(
        id=CircuitOperationId(operation_id),
        gate_id=X90.id,
        qubits=(Q0,),
    )


def test_parallel_branches_must_have_disjoint_qubits() -> None:
    source = QuantumProgramIR(
        id=QuantumProgramId("parallel"),
        body=Parallel(
            (
                _gate_call("left"),
                Sequence((_gate_call("right"),)),
            )
        ),
    )

    with pytest.raises(CircuitVerificationError) as error:
        verify_quantum_program(source, (X90,))

    assert [issue.code for issue in error.value.issues] == ["parallel_qubit_conflict"]


def test_parallel_each_verifies_template_before_budgeted_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = QubitId("$qubit")
    entity_ids = tuple(QubitId(f"q{index}") for index in range(1_000))
    source = QuantumProgramIR(
        id=QuantumProgramId("large-map"),
        body=ParallelEach(
            entity_set_id="qubits",
            item_id=item_id,
            entity_ids=entity_ids,
            operation=GateCall(
                id=CircuitOperationId("mapped-x90"),
                gate_id=X90.id,
                qubits=(item_id,),
            ),
        ),
    )
    calls = 0
    instantiate = program_module.instantiate_parallel_each_operation

    def record_instantiation(node: ParallelEach, entity_id: QubitId):
        nonlocal calls
        calls += 1
        return instantiate(node, entity_id)

    monkeypatch.setattr(
        program_module,
        "instantiate_parallel_each_operation",
        record_instantiation,
    )

    verified = verify_quantum_program(source, (X90,))

    assert calls == 0
    assert len(verified.unresolved.operations) == 1
    with pytest.raises(QuantumProgramExpansionError) as caught:
        plan_quantum_pulse_lowering(
            verified,
            ResolvedPulseImplementations(),
            output_id=PulseProgramId("large-map-pulses"),
            max_expanded_operations=999,
        )
    assert caught.value.expanded_operation_count == 1_000
    assert caught.value.limit == 999
    assert calls == 0

    plan = plan_quantum_pulse_lowering(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("large-map-pulses"),
        max_expanded_operations=1_000,
    )

    assert plan.body is verified.program.body
    assert plan.expanded_operation_count == 1_000
    assert calls == 0

    expanded = tuple(
        verified.iter_expanded_unresolved_operations(
            max_expanded_operations=1_000,
        )
    )

    assert len(expanded) == 1_000
    assert calls == 1_000


def test_repeat_streams_every_expanded_unresolved_operation() -> None:
    verified = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId("repeated-gate"),
            body=Repeat(_gate_call("repeated-x90"), count=3),
        ),
        (X90,),
    )

    workload = verified.require_expansion_budget(3)
    expanded = tuple(verified.iter_expanded_unresolved_operations())

    assert workload.expanded_operation_count == 3
    assert len(expanded) == 3


def test_parallel_width_composes_nested_parallel_and_entity_maps() -> None:
    item = QubitId("$qubit")
    entities = tuple(QubitId(f"q{index}") for index in range(4))

    def pulse_leaf(operation_id: str, qubit: QubitId) -> PulseBlock:
        return PulseBlock(
            id=CircuitOperationId(operation_id),
            pulse_template=PulseProgram(
                id=PulseProgramId(f"{operation_id}-template"),
                body=Delay(
                    id=PulseEventId("delay"),
                    signal=DriveSignal(qubit),
                    duration=Quantity(1, "ns"),
                ),
            ),
        )

    mapped = ParallelEach(
        entity_set_id="targets",
        item_id=item,
        entity_ids=entities,
        operation=Parallel(
            (
                pulse_leaf("mapped-drive", item),
                pulse_leaf("mapped-readout", item),
                pulse_leaf("mapped-acquire", item),
            )
        ),
    )
    verified = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId("nested-parallel-map"),
            body=Parallel((mapped, pulse_leaf("independent", Q0))),
        ),
        (X90,),
    )

    workload = verified.require_expansion_budget(None)

    assert workload.max_parallel_width == 13


def test_parallel_each_pulses_expand_only_at_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = QubitId("$qubit")
    entity_ids = tuple(QubitId(f"q{index}") for index in range(1_000))
    verified = verify_quantum_program(
        QuantumProgramIR(
            QuantumProgramId("large-pulse-map"),
            ParallelEach(
                entity_set_id="qubits",
                item_id=item_id,
                entity_ids=entity_ids,
                operation=PulseBlock(
                    id=CircuitOperationId("mapped-delay"),
                    pulse_template=PulseProgram(
                        id=PulseProgramId("mapped-delay-template"),
                        body=Delay(
                            id=PulseEventId("delay"),
                            signal=DriveSignal(item_id),
                            duration=Quantity(4, "ns"),
                        ),
                    ),
                ),
            ),
        ),
        (),
    )
    calls = 0
    instantiate = program_module.instantiate_parallel_each_operation

    def record_instantiation(node: ParallelEach, entity_id: QubitId):
        nonlocal calls
        calls += 1
        return instantiate(node, entity_id)

    monkeypatch.setattr(
        program_module,
        "instantiate_parallel_each_operation",
        record_instantiation,
    )

    plan = plan_quantum_pulse_lowering(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("large-pulse-map-output"),
        max_expanded_operations=1_000,
    )

    assert isinstance(plan.body, ParallelEach)
    assert calls == 0

    pulses = materialize_quantum_pulse_program(plan)

    assert isinstance(pulses.body, PulseParallel)
    assert len(pulses.body.branches) == 1_000
    assert calls == 1_000


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


def _measurement(
    operation_id: str = "measure",
) -> Measure:
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
    plan = plan_quantum_pulse_lowering(
        verified,
        _implementations(reference, measurement),
        output_id=PulseProgramId("drag-sweep-point-pulses"),
    )

    assert tuple(operation.id for operation in verified.logical_operations) == (
        reference.id,
        candidate_call.id,
        measurement.id,
    )
    pulses = materialize_quantum_pulse_program(plan)
    assert schedule(pulses).duration_seconds == Decimal("40e-9")
    leaves = tuple(iter_pulse_leaves(pulses.body))
    assert len(leaves) == 4
    assert any(
        leaf.id.scope[:4]
        == (
            "programs",
            source.id.value,
            "operations",
            candidate_call.id.value,
        )
        for leaf in leaves
    )
    assert pulses.acquisition_slots[0].id == measurement.acquisition_slot_id
    assert any(
        leaf.id.scope[:4]
        == (
            "programs",
            source.id.value,
            "operations",
            measurement.id.value,
        )
        for leaf in leaves
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

    plan = plan_quantum_pulse_lowering(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("inline-pulse-lowered"),
    )

    pulses = materialize_quantum_pulse_program(plan)
    [slot] = pulses.acquisition_slots
    assert slot.id.scope[:4] == (
        "programs",
        verified.program.id.value,
        "operations",
        block.id.value,
    )
    assert schedule(pulses).duration_seconds == Decimal("8e-9")


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

    plan = plan_quantum_pulse_lowering(
        verified,
        ResolvedPulseImplementations(),
        output_id=PulseProgramId("explicit-readout-lowered"),
    )

    pulses = materialize_quantum_pulse_program(plan)
    assert pulses.acquisition_slots[0].id == public_slot


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
