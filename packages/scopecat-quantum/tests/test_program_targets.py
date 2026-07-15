from __future__ import annotations

from typing import cast

import pytest
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    GateId,
    PulseEventId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
)
from scopecat_quantum.circuit_pulses import (
    CircuitPulseAcquisitionProvenance,
    CircuitPulseEventProvenance,
)
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.measurement_calibrations import (
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
)
from scopecat_quantum.program_targets import (
    PreparedQuantumTargetBatch,
    PreparedQuantumTargetEntry,
    QuantumTargetAcquisitionOrigin,
    QuantumTargetEventOrigin,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    AuthoredPulseAcquisitionProvenance,
    AuthoredPulseEventProvenance,
    ImplementedGate,
    ImplementedGatePulseEventProvenance,
    LoweredQuantumPulseProgram,
    PulseBlock,
    QuantumProgramIR,
    Sequence,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
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
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileEntry,
    TargetCompileRequest,
    TargetEventAddress,
)

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


def _lowered_mixed_program() -> LoweredQuantumPulseProgram:
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
    catalog = CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=CalibrationId("x90-q0"),
                    key=GateCalibrationKey.from_call(gate),
                    pulse_template=_gate_template(),
                ),
            )
        ),
        measurements=MeasurementCalibrationCatalog(
            (
                MeasurementCalibration(
                    id=CalibrationId("readout-q0"),
                    key=MeasurementCalibrationKey.from_measurement(measurement),
                    pulse_template=_readout_template(
                        Q0,
                        program_id="measurement-template",
                    ),
                ),
            )
        ),
    )
    return lower_quantum_program_to_pulses(
        verified,
        catalog,
        output_id=PulseProgramId("mixed-program-pulses"),
    )


def _prepared(entry_id: str = "point-0") -> PreparedQuantumTargetEntry:
    return prepare_quantum_target_entry(
        TargetCompileEntryId(entry_id),
        _lowered_mixed_program(),
    )


def _batch(
    entries: tuple[PreparedQuantumTargetEntry, ...],
) -> PreparedQuantumTargetBatch:
    return prepare_quantum_target_batch(
        entries,
        target_id=TargetId("target"),
        compiler_id=TargetCompilerId("compiler.v1"),
        capability_fingerprint="capabilities:v1",
        repetitions=7,
    )


def test_preparation_exposes_one_scheduled_only_target_entry_with_total_origins() -> (
    None
):
    prepared = _prepared()

    assert prepared.source_program_id == QuantumProgramId("mixed-program")
    assert isinstance(prepared.target_entry.program, ScheduledPulseProgram)
    assert prepared.target_entry.program is prepared.scheduled
    assert prepared.scheduled.id == prepared.lowered.program.id
    assert prepared.event_addresses == prepared.target_entry.event_addresses
    assert prepared.acquisition_addresses == (
        prepared.target_entry.acquisition_addresses
    )
    assert tuple(origin.address for origin in prepared.event_origins) == (
        prepared.target_entry.event_addresses
    )
    assert tuple(origin.address for origin in prepared.acquisition_origins) == (
        prepared.target_entry.acquisition_addresses
    )

    assert any(
        isinstance(origin.provenance, CircuitPulseEventProvenance)
        for origin in prepared.event_origins
    )
    assert any(
        isinstance(origin.provenance, AuthoredPulseEventProvenance)
        for origin in prepared.event_origins
    )
    assert any(
        isinstance(origin.provenance, CircuitPulseAcquisitionProvenance)
        for origin in prepared.acquisition_origins
    )
    assert any(
        isinstance(origin.provenance, AuthoredPulseAcquisitionProvenance)
        for origin in prepared.acquisition_origins
    )
    for origin in prepared.event_origins:
        assert origin.source_program_id == prepared.source_program_id
        assert prepared.event_origin_for(origin.address) is origin
    for origin in prepared.acquisition_origins:
        assert origin.source_program_id == prepared.source_program_id
        assert prepared.acquisition_origin_for(origin.address) is origin


def test_preparation_accepts_an_explicit_gate_implementation_origin() -> None:
    source = QuantumProgramIR(
        id=QuantumProgramId("implemented-gate"),
        body=ImplementedGate(
            call=_gate_call(),
            pulse_template=_gate_template(),
            candidate_id="x90.candidate",
        ),
    )
    lowered = lower_quantum_program_to_pulses(
        verify_quantum_program(source, (X90,)),
        CalibrationCatalog(),
        output_id=PulseProgramId("implemented-gate-pulses"),
    )

    prepared = prepare_quantum_target_entry(
        TargetCompileEntryId("implemented-point"),
        lowered,
    )

    [origin] = prepared.event_origins
    assert isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
    assert origin.provenance.candidate_id == "x90.candidate"


def test_prepared_entry_rejects_incomplete_or_reordered_origin_coverage() -> None:
    prepared = _prepared()

    with pytest.raises(ValueError, match="event origins must exactly cover"):
        PreparedQuantumTargetEntry(
            prepared.lowered,
            prepared.scheduled,
            prepared.target_entry,
            prepared.event_origins[:-1],
            prepared.acquisition_origins,
        )
    with pytest.raises(ValueError, match="event origins must exactly cover"):
        PreparedQuantumTargetEntry(
            prepared.lowered,
            prepared.scheduled,
            prepared.target_entry,
            tuple(reversed(prepared.event_origins)),
            prepared.acquisition_origins,
        )
    with pytest.raises(ValueError, match="acquisition origins must exactly cover"):
        PreparedQuantumTargetEntry(
            prepared.lowered,
            prepared.scheduled,
            prepared.target_entry,
            prepared.event_origins,
            prepared.acquisition_origins[:-1],
        )


def test_prepared_entry_rejects_a_scheduled_subset_of_lowered_provenance() -> None:
    prepared = _prepared()
    event_subset = ScheduledPulseProgram(
        id=prepared.scheduled.id,
        duration_seconds=prepared.scheduled.duration_seconds,
        events=prepared.scheduled.events[:-1],
        acquisition_slots=prepared.scheduled.acquisition_slots,
    )
    with pytest.raises(ValueError, match="events must exactly cover"):
        PreparedQuantumTargetEntry(
            prepared.lowered,
            event_subset,
            TargetCompileEntry(prepared.id, event_subset),
            prepared.event_origins[:-1],
            prepared.acquisition_origins,
        )

    acquisition_subset = ScheduledPulseProgram(
        id=prepared.scheduled.id,
        duration_seconds=prepared.scheduled.duration_seconds,
        events=prepared.scheduled.events,
        acquisition_slots=prepared.scheduled.acquisition_slots[:-1],
    )
    with pytest.raises(ValueError, match="acquisitions must exactly cover"):
        PreparedQuantumTargetEntry(
            prepared.lowered,
            acquisition_subset,
            TargetCompileEntry(prepared.id, acquisition_subset),
            prepared.event_origins,
            prepared.acquisition_origins[:-1],
        )


def test_origins_reject_wrong_address_identity_and_program_space() -> None:
    prepared = _prepared()
    first_event = prepared.event_origins[0]
    second_event = prepared.event_origins[1]
    first_acquisition = prepared.acquisition_origins[0]
    second_acquisition = prepared.acquisition_origins[1]

    with pytest.raises(ValueError, match="event address must identify"):
        QuantumTargetEventOrigin(
            prepared.source_program_id,
            second_event.address,
            first_event.provenance,
        )
    with pytest.raises(ValueError, match="acquisition address must identify"):
        QuantumTargetAcquisitionOrigin(
            prepared.source_program_id,
            second_acquisition.address,
            first_acquisition.provenance,
        )
    with pytest.raises(TypeError, match="QuantumProgramId"):
        QuantumTargetEventOrigin(
            cast("QuantumProgramId", CircuitId("wrong-space")),
            first_event.address,
            first_event.provenance,
        )


def test_factory_and_lookups_reject_foreign_runtime_identities() -> None:
    lowered = _lowered_mixed_program()
    with pytest.raises(TypeError, match="TargetCompileEntryId"):
        prepare_quantum_target_entry(
            cast("TargetCompileEntryId", TargetId("wrong-space")),
            lowered,
        )
    with pytest.raises(TypeError, match="LoweredQuantumPulseProgram"):
        prepare_quantum_target_entry(
            TargetCompileEntryId("point"),
            cast("LoweredQuantumPulseProgram", object()),
        )

    prepared = prepare_quantum_target_entry(TargetCompileEntryId("point"), lowered)
    with pytest.raises(KeyError, match="does not belong"):
        prepared.event_origin_for(
            TargetEventAddress(
                TargetCompileEntryId("foreign"),
                prepared.event_addresses[0].event_id,
            )
        )
    with pytest.raises(KeyError, match="does not belong"):
        prepared.acquisition_origin_for(
            TargetAcquisitionAddress(
                TargetCompileEntryId("foreign"),
                prepared.acquisition_addresses[0].slot_id,
            )
        )


def test_batch_preserves_entry_order_and_total_qualified_origin_coverage() -> None:
    first = _prepared("first")
    second = _prepared("second")

    batch = _batch((second, first))

    assert batch.entries == (second, first)
    assert batch.request.entries == (second.target_entry, first.target_entry)
    assert batch.request.target_id == TargetId("target")
    assert batch.request.compiler_id == TargetCompilerId("compiler.v1")
    assert batch.request.capability_fingerprint == "capabilities:v1"
    assert batch.request.repetitions == 7
    assert batch.event_addresses == tuple(
        address for entry in (second, first) for address in entry.event_addresses
    )
    assert batch.acquisition_addresses == tuple(
        address for entry in (second, first) for address in entry.acquisition_addresses
    )
    assert tuple(origin.address for origin in batch.event_origins) == (
        batch.request.event_addresses
    )
    assert tuple(origin.address for origin in batch.acquisition_origins) == (
        batch.request.acquisition_addresses
    )
    assert len(set(batch.event_addresses)) == len(batch.event_addresses)
    assert len(set(batch.acquisition_addresses)) == len(batch.acquisition_addresses)
    assert len({address.event_id for address in batch.event_addresses}) == len(
        first.event_addresses
    )
    assert len({address.slot_id for address in batch.acquisition_addresses}) == len(
        first.acquisition_addresses
    )
    for entry in batch.entries:
        assert batch.entry_for(entry.id) is entry
    for origin in batch.event_origins:
        assert batch.event_origin_for(origin.address) is origin
    for origin in batch.acquisition_origins:
        assert batch.acquisition_origin_for(origin.address) is origin


def test_batch_constructor_rejects_order_and_origin_coverage_mismatches() -> None:
    first = _prepared("first")
    second = _prepared("second")
    batch = _batch((first, second))
    reversed_request = TargetCompileRequest(
        target_id=batch.request.target_id,
        compiler_id=batch.request.compiler_id,
        capability_fingerprint=batch.request.capability_fingerprint,
        entries=(second.target_entry, first.target_entry),
        repetitions=batch.request.repetitions,
    )

    with pytest.raises(ValueError, match="retain prepared entry order"):
        PreparedQuantumTargetBatch(
            batch.entries,
            reversed_request,
            batch.event_origins,
            batch.acquisition_origins,
        )
    with pytest.raises(ValueError, match="event origins must exactly cover"):
        PreparedQuantumTargetBatch(
            batch.entries,
            batch.request,
            batch.event_origins[:-1],
            batch.acquisition_origins,
        )
    with pytest.raises(ValueError, match="acquisition origins must exactly cover"):
        PreparedQuantumTargetBatch(
            batch.entries,
            batch.request,
            batch.event_origins,
            batch.acquisition_origins[:-1],
        )


def test_batch_factory_and_lookups_reject_duplicate_or_foreign_identities() -> None:
    prepared = _prepared("point")
    with pytest.raises(TypeError, match="at least one"):
        _batch(())
    with pytest.raises(TypeError, match="PreparedQuantumTargetEntry"):
        _batch(cast("tuple[PreparedQuantumTargetEntry, ...]", (object(),)))
    with pytest.raises(ValueError, match="entry ids must be unique"):
        _batch((prepared, prepared))

    batch = _batch((prepared,))
    with pytest.raises(KeyError, match="not in this batch"):
        batch.entry_for(TargetCompileEntryId("foreign"))
    with pytest.raises(KeyError, match="not in this batch"):
        batch.event_origin_for(
            TargetEventAddress(
                TargetCompileEntryId("foreign"),
                batch.event_addresses[0].event_id,
            )
        )
    with pytest.raises(KeyError, match="not in this batch"):
        batch.acquisition_origin_for(
            TargetAcquisitionAddress(
                TargetCompileEntryId("foreign"),
                batch.acquisition_addresses[0].slot_id,
            )
        )
