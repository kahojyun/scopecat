from __future__ import annotations

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetCompileEntryId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.measurement_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
)
from scopecat_quantum.program_targets import (
    PreparedQuantumTargetBatch,
    PreparedQuantumTargetEntry,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    PulseBlock,
    QuantumProgramIR,
    QuantumPulseLoweringPlan,
    Sequence,
    plan_quantum_pulse_lowering,
    verify_quantum_program,
)
from scopecat_quantum.pulse_implementations import (
    GatePulseImplementation,
    GatePulseImplementationKey,
    ResolvedPulseImplementations,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
    ScheduledPulseProgram,
)
from scopecat_quantum.pulses import Parallel as PulseParallel

X90 = GateDefinition(GateId("x90"), qubit_arity=1)
Q0 = QubitId("q0")
Q1 = QubitId("q1")


def _gate_call() -> GateCall:
    return GateCall(
        id=CircuitOperationId("reference-x90"),
        gate_id=X90.id,
        qubits=(Q0,),
    )


def _gate_template() -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId("x90-template"),
        body=Delay(
            id=PulseEventId("drive"),
            signal=DriveSignal(Q0),
            duration=Quantity(4, "ns"),
        ),
    )


def _readout_template(qubit: QubitId, *, program_id: str) -> PulseProgram:
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(qubit),
    )
    duration = Quantity(8, "ns")
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(qubit),
                    envelope=Constant(
                        duration=duration,
                        amplitude=Quantity(0.25, "arb"),
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


def _pulse_lowering_plan() -> QuantumPulseLoweringPlan:
    gate = _gate_call()
    inline = PulseBlock(
        id=CircuitOperationId("inline-readout"),
        pulse_template=_readout_template(Q1, program_id="inline-template"),
    )
    measurement = Measure(
        id=CircuitOperationId("measure-q0"),
        qubit=Q0,
        acquisition_slot_id=AcquisitionSlotId("logical-result"),
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    source = QuantumProgramIR(
        id=QuantumProgramId("mixed-program"),
        body=Sequence((gate, inline, measurement)),
    )
    verified = verify_quantum_program(source, (X90,))
    implementations = ResolvedPulseImplementations(
        gates=(
            GatePulseImplementation(
                id=PulseImplementationId("x90-q0"),
                key=GatePulseImplementationKey.from_call(gate),
                pulse_template=_gate_template(),
            ),
        ),
        measurements=(
            MeasurementPulseImplementation(
                id=PulseImplementationId("readout-q0"),
                key=MeasurementPulseImplementationKey.from_measurement(measurement),
                pulse_template=_readout_template(
                    Q0,
                    program_id="measurement-template",
                ),
            ),
        ),
    )
    return plan_quantum_pulse_lowering(
        verified,
        implementations,
        output_id=PulseProgramId("mixed-program-pulses"),
    )


def _prepared(entry_id: str = "point-0") -> PreparedQuantumTargetEntry:
    return prepare_quantum_target_entry(
        TargetCompileEntryId(entry_id),
        _pulse_lowering_plan(),
    )


def _batch(
    entries: tuple[PreparedQuantumTargetEntry, ...],
) -> PreparedQuantumTargetBatch:
    return prepare_quantum_target_batch(
        entries,
        repetitions=7,
    )


def test_preparation_exposes_one_scheduled_target_entry() -> None:
    prepared = _prepared()

    assert isinstance(prepared.target_entry.program, ScheduledPulseProgram)
    assert prepared.target_entry.program is prepared.scheduled
    assert prepared.scheduled.id == PulseProgramId("mixed-program-pulses")
    assert prepared.acquisition_addresses == (
        prepared.target_entry.acquisition_addresses
    )


def test_batch_preserves_entry_order_and_acquisition_coverage() -> None:
    first = _prepared("first")
    second = _prepared("second")

    batch = _batch((second, first))

    assert batch.entries == (second, first)
    assert batch.request.entries == (second.target_entry, first.target_entry)
    assert batch.request.repetitions == 7
    assert batch.acquisition_addresses == tuple(
        address for entry in (second, first) for address in entry.acquisition_addresses
    )
    assert len(set(batch.acquisition_addresses)) == len(batch.acquisition_addresses)
    assert len({address.slot_id for address in batch.acquisition_addresses}) == len(
        first.acquisition_addresses
    )


def test_batch_factory_rejects_invalid_entries() -> None:
    prepared = _prepared("point")
    with pytest.raises(ValueError, match="at least one"):
        _batch(())
    with pytest.raises(ValueError, match="entry ids must be unique"):
        _batch((prepared, prepared))
