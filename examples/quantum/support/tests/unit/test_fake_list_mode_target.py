from __future__ import annotations

import cmath
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scopecat import Quantity
from scopecat_quantum import (
    DRAG,
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    CircuitProgram,
    CircuitPulseAcquisitionProvenance,
    CircuitSequence,
    Constant,
    Delay,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateCall,
    GateDefinition,
    GateId,
    Gaussian,
    Measure,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    Play,
    PreparedQuantumTargetEntry,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    PulseSequence,
    QuantumProgramId,
    QuantumProgramIR,
    QubitId,
    ReadoutSignal,
    ScheduledPulseProgram,
    ShiftPhase,
    TargetArtifact,
    TargetCompilationError,
    TargetCompileEntry,
    TargetCompileEntryId,
    TargetCompileRequest,
    TargetCompilerId,
    TargetId,
    compile_target,
    lower_circuit_to_pulses,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    schedule,
    select_calibrations,
    verify_circuit_program,
    verify_quantum_program,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeAcquisitionBinding,
    FakeAcquisitionWindow,
    FakeAwgChannelId,
    FakeDigitizerChannelId,
    FakeListEntry,
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeOutputBinding,
    FakeSegmentedDigitizer,
    default_fake_list_target,
)
from quantum_lab_demo.targets.fake_list_mode.model import (
    acquisition_slot_identity_payload,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeAcquisitionResponse,
    FakeAwgPlayback,
    FakeDigitizerValue,
)

Q0 = QubitId("q0")
Q1 = QubitId("q1")
Q2 = QubitId("q2")
DRIVE_Q0 = DriveSignal(Q0)
DRIVE_Q1 = DriveSignal(Q1)
ACQUIRE_Q0 = AcquireSignal(Q0)
ACQUIRE_Q1 = AcquireSignal(Q1)
READOUT_Q0 = ReadoutSignal(Q0)
READOUT_Q1 = ReadoutSignal(Q1)


@dataclass(frozen=True, slots=True)
class _IndexedAcquisitionResponse:
    fingerprint: str
    offset: int = 0

    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        base = complex(
            playback.shot_index + self.offset,
            window.start_sample + window.sample_count,
        )
        if window.kind is AcquisitionKind.INTEGRATED_IQ:
            return base
        return tuple(
            base + complex(index, -index) for index in range(window.sample_count)
        )


def _target(
    *,
    shared_output: bool = False,
    shared_acquisition: bool = False,
) -> FakeListTarget:
    return FakeListTarget(
        id=TargetId("fake-list-target"),
        sample_rate_hz=1_000_000_000,
        max_list_entries=16,
        max_samples_per_entry=1_024,
        max_waveform_memory_samples=16_384,
        max_capture_memory_samples=16_384,
        max_repetitions=128,
        max_frames=1_024,
        max_abs_amplitude=1.0,
        output_bindings=(
            FakeOutputBinding(DRIVE_Q0, FakeAwgChannelId("awg.0")),
            FakeOutputBinding(
                DRIVE_Q1,
                FakeAwgChannelId("awg.0" if shared_output else "awg.1"),
            ),
            FakeOutputBinding(READOUT_Q0, FakeAwgChannelId("awg.readout.0")),
            FakeOutputBinding(READOUT_Q1, FakeAwgChannelId("awg.readout.1")),
        ),
        acquisition_bindings=(
            FakeAcquisitionBinding(
                ACQUIRE_Q0,
                FakeDigitizerChannelId("adc.0"),
            ),
            FakeAcquisitionBinding(
                ACQUIRE_Q1,
                FakeDigitizerChannelId("adc.0" if shared_acquisition else "adc.1"),
            ),
        ),
    )


def _scheduled_program(
    name: str,
    *,
    qubit: QubitId,
    duration_ns: float = 4.0,
    amplitude: float = 0.25,
    amplitude_unit: str = "arb",
    kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    gaussian: bool = False,
) -> ScheduledPulseProgram:
    drive = DriveSignal(qubit)
    acquire = AcquireSignal(qubit)
    duration = Quantity(duration_ns, "ns")
    envelope = (
        Gaussian(
            duration=duration,
            amplitude=Quantity(amplitude, amplitude_unit),
            sigma=Quantity(1, "ns"),
        )
        if gaussian
        else Constant(
            duration=duration,
            amplitude=Quantity(amplitude, amplitude_unit),
        )
    )
    slot = AcquisitionSlot(
        AcquisitionSlotId(f"{name}-slot"),
        kind,
        acquire,
    )
    return schedule(
        PulseProgram(
            id=PulseProgramId(name),
            body=PulseParallel(
                (
                    Play(PulseEventId(f"{name}-play"), drive, envelope),
                    Acquire(
                        PulseEventId(f"{name}-acquire"),
                        acquire,
                        slot.id,
                        duration,
                    ),
                )
            ),
            acquisition_slots=(slot,),
        )
    )


def _scheduled_drag_program(
    name: str,
    *,
    duration_ns: float = 4.0,
    amplitude: float = 0.2,
    sigma_ns: float = 1.0,
    beta_ns: float = 0.5,
    phase_rad: float = 0.0,
):
    return schedule(
        PulseProgram(
            id=PulseProgramId(name),
            body=Play(
                PulseEventId(f"{name}-play"),
                DRIVE_Q0,
                DRAG(
                    duration=Quantity(duration_ns, "ns"),
                    amplitude=Quantity(amplitude, "arb"),
                    sigma=Quantity(sigma_ns, "ns"),
                    beta=Quantity(beta_ns, "ns"),
                    phase=Quantity(phase_rad, "rad"),
                ),
            ),
        )
    )


def _parallel_two_qubit_program(
    *,
    gaussian_q1: bool = False,
    q0_amplitude_unit: str = "arb",
):
    duration = Quantity(4, "ns")
    slots = (
        AcquisitionSlot(
            AcquisitionSlotId("q0-slot"),
            AcquisitionKind.INTEGRATED_IQ,
            ACQUIRE_Q0,
        ),
        AcquisitionSlot(
            AcquisitionSlotId("q1-slot"),
            AcquisitionKind.RAW_TRACE,
            ACQUIRE_Q1,
        ),
    )
    q1_envelope = (
        Gaussian(duration, Quantity(0.2, "arb"), Quantity(1, "ns"))
        if gaussian_q1
        else Constant(duration, Quantity(0.2, "arb"))
    )
    return schedule(
        PulseProgram(
            id=PulseProgramId("parallel-two-qubit"),
            body=PulseParallel(
                (
                    Play(
                        PulseEventId("q0-play"),
                        DRIVE_Q0,
                        Constant(duration, Quantity(0.2, q0_amplitude_unit)),
                    ),
                    Play(PulseEventId("q1-play"), DRIVE_Q1, q1_envelope),
                    Acquire(
                        PulseEventId("q0-acquire"),
                        ACQUIRE_Q0,
                        slots[0].id,
                        duration,
                    ),
                    Acquire(
                        PulseEventId("q1-acquire"),
                        ACQUIRE_Q1,
                        slots[1].id,
                        duration,
                    ),
                )
            ),
            acquisition_slots=slots,
        )
    )


def _prepared_measurement_entry(
    *,
    entry_id: str,
    program_id: str,
    qubit: QubitId,
    acquisition_kind: AcquisitionKind,
    acquisition_slot_id: AcquisitionSlotId,
) -> tuple[PreparedQuantumTargetEntry, Measure, MeasurementCalibration]:
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=qubit,
        acquisition_slot_id=acquisition_slot_id,
        acquisition_kind=acquisition_kind,
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=acquisition_kind,
        signal=AcquireSignal(qubit),
    )
    template = PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(qubit),
                    envelope=Constant(
                        duration=Quantity(4, "ns"),
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=AcquireSignal(qubit),
                    slot_id=template_slot.id,
                    duration=Quantity(4, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    calibration = MeasurementCalibration(
        id=CalibrationId(f"readout-{qubit.value}-{acquisition_kind.value}"),
        key=MeasurementCalibrationKey.from_measurement(measurement),
        pulse_template=template,
    )
    verified = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId(program_id),
            body=measurement,
        ),
        (),
    )
    lowered = lower_quantum_program_to_pulses(
        verified,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
        output_id=PulseProgramId(f"{entry_id}-pulses"),
    )
    return (
        prepare_quantum_target_entry(
            TargetCompileEntryId(entry_id),
            lowered,
        ),
        measurement,
        calibration,
    )


def _request(
    target: FakeListTarget,
    programs: Sequence[ScheduledPulseProgram],
    *,
    repetitions: int = 3,
    entry_ids: tuple[str, ...] | None = None,
) -> tuple[FakeListTargetCompiler, TargetCompileRequest]:
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    selected_entry_ids = entry_ids or tuple(
        f"entry-{label}"
        for label in ("alpha", "zeta", "gamma", "delta")[: len(programs)]
    )
    if len(selected_entry_ids) != len(programs):
        msg = "entry_ids must exactly cover programs"
        raise ValueError(msg)
    request = TargetCompileRequest(
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        entries=tuple(
            TargetCompileEntry(
                TargetCompileEntryId(selected_entry_ids[index]),
                program,
            )
            for index, program in enumerate(programs)
        ),
        repetitions=repetitions,
    )
    return compiler, request


def _compile_two_entries(*, repetitions: int = 3):
    target = _target()
    compiler, request = _request(
        target,
        (
            _scheduled_program("q0-program", qubit=Q0),
            _scheduled_program(
                "q1-program",
                qubit=Q1,
                kind=AcquisitionKind.RAW_TRACE,
            ),
        ),
        repetitions=repetitions,
    )
    return compile_target(compiler, request)


def _issue_codes(error: TargetCompilationError) -> set[str]:
    return {issue.code for issue in error.issues}


def test_compiler_builds_immutable_ordered_list_artifact() -> None:
    compiled = _compile_two_entries()
    artifact = compiled.artifact

    assert isinstance(artifact, TargetArtifact)
    assert artifact.source_entry_ids == (
        TargetCompileEntryId("entry-alpha"),
        TargetCompileEntryId("entry-zeta"),
    )
    assert [entry.list_index for entry in artifact.entries] == [0, 1]
    assert [entry.sample_count for entry in artifact.entries] == [4, 4]
    assert all(len(entry.waveforms) == 1 for entry in artifact.entries)
    assert all(
        len(waveform.samples) == entry.sample_count
        for entry in artifact.entries
        for waveform in entry.waveforms
    )
    assert artifact.entries[0].waveforms[0].samples == (0.25 + 0j,) * 4
    assert artifact.entries[1].acquisitions[0].kind is AcquisitionKind.RAW_TRACE
    assert artifact.artifact_fingerprint.startswith("sha256:")
    assert artifact.id.value.endswith(
        artifact.artifact_fingerprint.removeprefix("sha256:")
    )


def test_compiler_accumulates_frame_phase_per_entry_and_adds_envelope_phase() -> None:
    phase_program = schedule(
        PulseProgram(
            id=PulseProgramId("frame-phase"),
            body=PulseSequence(
                (
                    ShiftPhase(
                        PulseEventId("shift-quarter"),
                        DRIVE_Q0,
                        Quantity(math.pi / 4, "rad"),
                    ),
                    Play(
                        PulseEventId("first-play"),
                        DRIVE_Q0,
                        Constant(
                            Quantity(4, "ns"),
                            Quantity(0.25, "arb"),
                            Quantity(math.pi / 4, "rad"),
                        ),
                    ),
                    ShiftPhase(
                        PulseEventId("shift-half"),
                        DRIVE_Q0,
                        Quantity(math.pi / 2, "rad"),
                    ),
                    Play(
                        PulseEventId("second-play"),
                        DRIVE_Q0,
                        Constant(
                            Quantity(4, "ns"),
                            Quantity(0.25, "arb"),
                            Quantity(math.pi / 4, "rad"),
                        ),
                    ),
                )
            ),
        )
    )
    reset_program = schedule(
        PulseProgram(
            id=PulseProgramId("frame-reset"),
            body=Play(
                PulseEventId("plain-play"),
                DRIVE_Q0,
                Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
            ),
        )
    )
    compiler, request = _request(
        _target(),
        (phase_program, reset_program),
        repetitions=1,
    )

    artifact = compile_target(compiler, request).artifact

    assert artifact.entries[0].waveforms[0].samples == pytest.approx(
        (0.25j,) * 4 + (-0.25 + 0j,) * 4
    )
    assert artifact.entries[1].waveforms[0].samples == (0.25 + 0j,) * 4


def test_compiler_wraps_large_frame_and_envelope_phases_before_combining() -> None:
    large_phase = 1e308
    program = schedule(
        PulseProgram(
            id=PulseProgramId("large-frame-phase"),
            body=PulseSequence(
                (
                    ShiftPhase(
                        PulseEventId("first-shift"),
                        DRIVE_Q0,
                        Quantity(large_phase, "rad"),
                    ),
                    ShiftPhase(
                        PulseEventId("second-shift"),
                        DRIVE_Q0,
                        Quantity(large_phase, "rad"),
                    ),
                    Play(
                        PulseEventId("play"),
                        DRIVE_Q0,
                        Constant(
                            Quantity(4, "ns"),
                            Quantity(0.25, "arb"),
                            Quantity(large_phase, "rad"),
                        ),
                    ),
                )
            ),
        )
    )
    compiler, request = _request(_target(), (program,), repetitions=1)

    artifact = compile_target(compiler, request).artifact

    reduced = math.remainder(large_phase, math.tau)
    combined = math.remainder(
        math.remainder(reduced + reduced, math.tau) + reduced,
        math.tau,
    )
    expected = cmath.rect(0.25, combined)
    assert artifact.entries[0].waveforms[0].samples == pytest.approx((expected,) * 4)


def test_fake_target_uses_structural_acquisition_slot_identity() -> None:
    structurally_first = AcquisitionSlotId("slot", scope=("a", "b"))
    rendered_first = AcquisitionSlotId("slot", scope=("a/b",))
    assert rendered_first.value < structurally_first.value
    windows = tuple(
        FakeAcquisitionWindow(
            event_id=PulseEventId(f"capture-{index}"),
            slot_id=slot_id,
            signal=ACQUIRE_Q0,
            channel_id=FakeDigitizerChannelId("adc.0"),
            start_sample=0,
            sample_count=1,
            kind=AcquisitionKind.INTEGRATED_IQ,
        )
        for index, slot_id in enumerate((rendered_first, structurally_first))
    )

    entry = FakeListEntry(
        list_index=0,
        entry_id=TargetCompileEntryId("entry"),
        program_id=PulseProgramId("program"),
        sample_count=1,
        waveforms=(),
        acquisitions=windows,
    )

    assert tuple(window.slot_id for window in entry.acquisitions) == (
        structurally_first,
        rendered_first,
    )
    assert acquisition_slot_identity_payload(rendered_first) == {
        "scope": ["a/b"],
        "local_id": "slot",
    }


def test_calibrated_gate_circuit_reaches_fake_list_target() -> None:
    gate = GateDefinition(GateId("x"), qubit_arity=1)
    first = GateCall(CircuitOperationId("first"), gate.id, (Q0,))
    second = GateCall(CircuitOperationId("second"), gate.id, (Q0,))
    circuit = verify_circuit_program(
        CircuitProgram(
            CircuitId("two-x-gates"),
            CircuitSequence((first, second)),
        ),
        (gate,),
    )
    template = PulseProgram(
        PulseProgramId("x-template"),
        Play(
            PulseEventId("drive"),
            DRIVE_Q0,
            Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
        ),
    )
    selection = select_calibrations(
        circuit,
        CalibrationCatalog(
            gates=GateCalibrationCatalog(
                (
                    GateCalibration(
                        CalibrationId("x-q0"),
                        GateCalibrationKey.from_call(first),
                        template,
                    ),
                )
            )
        ),
    )
    lowered = lower_circuit_to_pulses(
        circuit,
        selection,
        output_id=PulseProgramId("two-x-pulses"),
    )
    scheduled = schedule(lowered.program)

    assert len({event.id for event in scheduled.events}) == 2
    assert scheduled.events[0].id.scope != scheduled.events[1].id.scope
    target = _target()
    compiler, request = _request(target, (scheduled,), repetitions=1)
    artifact = compile_target(compiler, request).artifact
    entry = artifact.entries[0]
    assert entry.sample_count == 8
    assert entry.waveforms[0].samples == (0.25 + 0j,) * 8
    assert entry.acquisitions == ()


def test_calibrated_measurement_reaches_fake_awg_and_digitizer() -> None:
    gate = GateDefinition(GateId("x"), qubit_arity=1)
    gate_call = GateCall(CircuitOperationId("x"), gate.id, (Q0,))
    measurement = Measure(
        CircuitOperationId("measure"),
        Q0,
        AcquisitionSlotId("result"),
        AcquisitionKind.INTEGRATED_IQ,
    )
    circuit = verify_circuit_program(
        CircuitProgram(
            CircuitId("x-then-measure"),
            CircuitSequence((gate_call, measurement)),
        ),
        (gate,),
    )
    gate_template = PulseProgram(
        PulseProgramId("x-template"),
        Play(
            PulseEventId("drive"),
            DRIVE_Q0,
            Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
        ),
    )
    template_slot = AcquisitionSlot(
        AcquisitionSlotId("template-result"),
        AcquisitionKind.INTEGRATED_IQ,
        ACQUIRE_Q0,
    )
    measurement_template = PulseProgram(
        PulseProgramId("readout-template"),
        PulseParallel(
            (
                Play(
                    PulseEventId("stimulus"),
                    READOUT_Q0,
                    Constant(Quantity(8, "ns"), Quantity(0.4, "arb")),
                ),
                Acquire(
                    PulseEventId("capture"),
                    ACQUIRE_Q0,
                    template_slot.id,
                    Quantity(8, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    selection = select_calibrations(
        circuit,
        CalibrationCatalog(
            gates=GateCalibrationCatalog(
                (
                    GateCalibration(
                        CalibrationId("x-q0"),
                        GateCalibrationKey.from_call(gate_call),
                        gate_template,
                    ),
                )
            ),
            measurements=MeasurementCalibrationCatalog(
                (
                    MeasurementCalibration(
                        CalibrationId("readout-q0"),
                        MeasurementCalibrationKey.from_measurement(measurement),
                        measurement_template,
                    ),
                )
            ),
        ),
    )
    lowered = lower_circuit_to_pulses(
        circuit,
        selection,
        output_id=PulseProgramId("x-then-readout"),
    )
    scheduled = schedule(lowered.program)

    assert scheduled.duration_seconds == Decimal("12e-9")
    assert tuple(slot.id for slot in scheduled.acquisition_slots) == (
        measurement.acquisition_slot_id,
    )
    assert {
        provenance.event_id.scope[:4]
        for provenance in lowered.event_provenance
        if provenance.operation_id == measurement.id
    } == {("circuits", "x-then-measure", "operations", "measure")}
    target = _target()
    compiler, request = _request(target, (scheduled,), repetitions=2)
    compiled = compile_target(compiler, request)
    entry = compiled.artifact.entries[0]
    waveforms = {
        waveform.channel_id.value: waveform.samples for waveform in entry.waveforms
    }
    assert entry.sample_count == 12
    assert waveforms["awg.0"] == (0.25 + 0j,) * 4 + (0j,) * 8
    assert waveforms["awg.readout.0"] == (0j,) * 4 + (0.4 + 0j,) * 8
    assert len(entry.acquisitions) == 1
    window = entry.acquisitions[0]
    assert window.slot_id == measurement.acquisition_slot_id
    assert window.start_sample == 4
    assert window.sample_count == 8
    assert window.kind is AcquisitionKind.INTEGRATED_IQ

    run = FakeListRuntime().execute(compiled)
    assert tuple(
        (frame.shot_index, frame.entry_id, frame.slot_id) for frame in run.frames
    ) == (
        (0, TargetCompileEntryId("entry-alpha"), measurement.acquisition_slot_id),
        (1, TargetCompileEntryId("entry-alpha"), measurement.acquisition_slot_id),
    )
    assert all(isinstance(frame.value, complex) for frame in run.frames)
    assert run == FakeListRuntime().execute(compiled)


def test_prepared_quantum_batch_resolves_reused_slots_from_runtime_frames() -> None:
    target = _target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    shared_slot_id = AcquisitionSlotId(
        "result",
        scope=("circuit-local",),
    )
    iq_entry, iq_measurement, iq_calibration = _prepared_measurement_entry(
        entry_id="iq-entry",
        program_id="iq-program",
        qubit=Q0,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        acquisition_slot_id=shared_slot_id,
    )
    trace_entry, trace_measurement, trace_calibration = _prepared_measurement_entry(
        entry_id="trace-entry",
        program_id="trace-program",
        qubit=Q1,
        acquisition_kind=AcquisitionKind.RAW_TRACE,
        acquisition_slot_id=shared_slot_id,
    )
    repetitions = 3
    batch = prepare_quantum_target_batch(
        (iq_entry, trace_entry),
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=repetitions,
    )

    compiled = compile_target(compiler, batch.request)
    run = FakeListRuntime().execute(compiled)

    assert len(batch.acquisition_addresses) == 2
    assert len(set(batch.acquisition_addresses)) == 2
    assert {address.slot_id for address in batch.acquisition_addresses} == {
        shared_slot_id
    }
    assert len(run.playbacks) == repetitions * 2
    assert len(run.frames) == repetitions * 2
    assert {frame.address for frame in run.frames} == set(batch.acquisition_addresses)
    assert all(
        tuple(frame.shot_index for frame in run.frames if frame.address == address)
        == tuple(range(repetitions))
        for address in batch.acquisition_addresses
    )

    expected = {
        iq_entry.id: (
            iq_entry.source_program_id,
            iq_measurement,
            iq_calibration,
        ),
        trace_entry.id: (
            trace_entry.source_program_id,
            trace_measurement,
            trace_calibration,
        ),
    }
    for frame in run.frames:
        origin = batch.acquisition_origin_for(frame.address)
        source_program_id, measurement, calibration = expected[frame.entry_id]
        assert origin.address == frame.address
        assert origin.source_program_id == source_program_id
        assert isinstance(origin.provenance, CircuitPulseAcquisitionProvenance)
        assert origin.provenance.measurement_id == measurement.id
        assert origin.provenance.acquisition_slot_id == measurement.acquisition_slot_id
        assert origin.provenance.calibration_id == calibration.id
        assert frame.slot_id == shared_slot_id
        assert frame.kind is measurement.acquisition_kind
        if frame.kind is AcquisitionKind.INTEGRATED_IQ:
            assert isinstance(frame.value, complex)
        else:
            assert isinstance(frame.value, tuple)
            assert len(frame.value) == 4


def test_runtime_loops_full_list_per_shot_and_correlates_frames() -> None:
    compiled = _compile_two_entries(repetitions=3)

    first = FakeListRuntime().execute(compiled)
    second = FakeListRuntime().execute(compiled)

    assert [
        (playback.shot_index, playback.list_index, playback.entry_id.value)
        for playback in first.playbacks
    ] == [
        (
            shot,
            list_index,
            ("entry-alpha", "entry-zeta")[list_index],
        )
        for shot in range(3)
        for list_index in range(2)
    ]
    assert [
        (
            frame.frame_index,
            frame.shot_index,
            frame.list_index,
            frame.entry_id.value,
            frame.slot_id.value,
        )
        for frame in first.frames
    ] == [
        (
            frame_index,
            shot,
            list_index,
            ("entry-alpha", "entry-zeta")[list_index],
            f"q{list_index}-program-slot",
        )
        for frame_index, (shot, list_index) in enumerate(
            (shot, list_index) for shot in range(3) for list_index in range(2)
        )
    ]
    assert isinstance(first.frames[0].value, complex)
    raw_value = first.frames[1].value
    assert isinstance(raw_value, tuple)
    assert len(raw_value) == 4
    assert first == second
    assert first.fingerprint.startswith("sha256:")


def test_runtime_accepts_deterministic_custom_acquisition_response() -> None:
    compiled = _compile_two_entries(repetitions=3)
    response = _IndexedAcquisitionResponse(
        fingerprint="sha256:" + "1" * 64,
        offset=7,
    )
    runtime = FakeListRuntime(
        digitizer=FakeSegmentedDigitizer(response=response),
    )

    first = runtime.execute(compiled)
    second = runtime.execute(compiled)
    default_run = FakeListRuntime().execute(compiled)

    assert isinstance(response, FakeAcquisitionResponse)
    assert first == second
    assert first.response is response
    assert first.fingerprint != default_run.fingerprint
    for frame in first.frames:
        expected = complex(frame.shot_index + response.offset, 4)
        if frame.kind is AcquisitionKind.INTEGRATED_IQ:
            assert frame.value == expected
        else:
            assert isinstance(frame.value, tuple)
            assert frame.value == tuple(
                expected + complex(index, -index) for index in range(4)
            )


def test_custom_acquisition_response_run_rejects_tampering() -> None:
    response = _IndexedAcquisitionResponse(
        fingerprint="sha256:" + "2" * 64,
        offset=3,
    )
    run = FakeListRuntime(
        digitizer=FakeSegmentedDigitizer(response=response),
    ).execute(_compile_two_entries(repetitions=1))

    changed_response = replace(
        response,
        fingerprint="sha256:" + "3" * 64,
        offset=response.offset + 1,
    )
    with pytest.raises(ValueError, match="logical address"):
        replace(run, response=changed_response)

    changed_response_identity = replace(
        response,
        fingerprint="sha256:" + "4" * 64,
    )
    with pytest.raises(ValueError, match="fingerprint"):
        replace(run, response=changed_response_identity)

    changed_frame = replace(
        run.frames[0],
        value=cast("complex", run.frames[0].value) + 1,
    )
    with pytest.raises(ValueError, match="logical address"):
        replace(run, frames=(changed_frame, *run.frames[1:]))

    with pytest.raises(ValueError, match="fingerprint"):
        replace(run, fingerprint="sha256:" + "5" * 64)


def test_runtime_preserves_multiple_slot_order_within_each_list_entry() -> None:
    target = _target()
    compiler, request = _request(
        target,
        (_parallel_two_qubit_program(),),
        repetitions=2,
    )

    run = FakeListRuntime().execute(compile_target(compiler, request))

    assert [
        (frame.shot_index, frame.segment_index, frame.slot_id.value)
        for frame in run.frames
    ] == [
        (0, 0, "q0-slot"),
        (0, 1, "q1-slot"),
        (1, 0, "q0-slot"),
        (1, 1, "q1-slot"),
    ]


def test_complete_run_rejects_missing_or_mismatched_frames() -> None:
    run = FakeListRuntime().execute(_compile_two_entries(repetitions=1))

    with pytest.raises(ValueError, match="exactly cover"):
        replace(run, frames=run.frames[:-1])

    wrong_slot = replace(
        run.frames[0],
        slot_id=AcquisitionSlotId("wrong-slot"),
    )
    with pytest.raises(ValueError, match="acquisition window"):
        replace(run, frames=(wrong_slot, *run.frames[1:]))

    raw_frame = run.frames[1]
    assert isinstance(raw_frame.value, tuple)
    wrong_trace = replace(raw_frame, value=(1j,))
    with pytest.raises(ValueError, match="logical address"):
        replace(run, frames=(run.frames[0], wrong_trace))


def test_response_depends_on_waveform_but_not_physical_list_position() -> None:
    target = _target()
    low_program = _scheduled_program("low", qubit=Q0, amplitude=0.1)
    high_program = _scheduled_program("high", qubit=Q1, amplitude=0.8)
    compiler, request = _request(
        target,
        (low_program, high_program),
        repetitions=2,
        entry_ids=("logical-low", "logical-high"),
    )
    reversed_compiler, reversed_request = _request(
        target,
        (high_program, low_program),
        repetitions=2,
        entry_ids=("logical-high", "logical-low"),
    )

    original = FakeListRuntime().execute(compile_target(compiler, request))
    reordered = FakeListRuntime().execute(
        compile_target(reversed_compiler, reversed_request)
    )
    changed_compiler, changed_request = _request(
        target,
        (_scheduled_program("low", qubit=Q0, amplitude=0.9),),
        repetitions=2,
        entry_ids=("logical-low",),
    )
    changed = FakeListRuntime().execute(
        compile_target(changed_compiler, changed_request)
    )

    original_values = {
        (frame.entry_id, frame.shot_index, frame.slot_id): frame.value
        for frame in original.frames
    }
    reordered_values = {
        (frame.entry_id, frame.shot_index, frame.slot_id): frame.value
        for frame in reordered.frames
    }
    assert reordered_values == original_values
    low_address = (
        TargetCompileEntryId("logical-low"),
        0,
        AcquisitionSlotId("low-slot"),
    )
    changed_values = {
        (frame.entry_id, frame.shot_index, frame.slot_id): frame.value
        for frame in changed.frames
    }
    assert changed_values[low_address] != original_values[low_address]
    assert (
        changed.artifact.artifact_fingerprint != original.artifact.artifact_fingerprint
    )


def test_digitizer_rejects_reordered_or_incomplete_playback_coverage() -> None:
    compiled = _compile_two_entries(repetitions=2)
    artifact = compiled.artifact
    playbacks = FakeListRuntime().awg.play(artifact)
    digitizer = FakeSegmentedDigitizer()

    with pytest.raises(ValueError, match="shot-major list order"):
        digitizer.capture(artifact, tuple(reversed(playbacks)))
    with pytest.raises(ValueError, match="shot-major list order"):
        digitizer.capture(artifact, playbacks[:-1])


def test_capability_fingerprint_is_binding_order_invariant_and_limit_sensitive() -> (
    None
):
    target = _target()
    reordered = replace(
        target,
        output_bindings=tuple(reversed(target.output_bindings)),
        acquisition_bindings=tuple(reversed(target.acquisition_bindings)),
    )
    changed = replace(target, max_frames=target.max_frames + 1)

    assert reordered.capability_fingerprint == target.capability_fingerprint
    assert changed.capability_fingerprint != target.capability_fingerprint


def test_artifact_fingerprint_is_deterministic_and_entry_order_sensitive() -> None:
    target = _target()
    programs = (
        _scheduled_program("q0-program", qubit=Q0),
        _scheduled_program("q1-program", qubit=Q1),
    )
    compiler, request = _request(target, programs)
    first = compile_target(compiler, request).artifact
    second = compile_target(compiler, request).artifact
    reversed_compiler, reversed_request = _request(
        target,
        tuple(reversed(programs)),
        entry_ids=("entry-zeta", "entry-alpha"),
    )
    reversed_artifact = compile_target(
        reversed_compiler,
        reversed_request,
    ).artifact

    assert first == second
    assert first.artifact_fingerprint == second.artifact_fingerprint
    assert reversed_artifact.artifact_fingerprint != first.artifact_fingerprint


@given(st.integers(min_value=1, max_value=64))
def test_exact_sample_grid_accepts_integer_nanosecond_durations(
    duration_ns: int,
) -> None:
    target = _target()
    compiler, request = _request(
        target,
        (_scheduled_program("grid", qubit=Q0, duration_ns=duration_ns),),
        repetitions=1,
    )

    artifact = compile_target(compiler, request).artifact

    assert artifact.entries[0].sample_count == duration_ns


@given(st.integers(min_value=1, max_value=64))
def test_exact_sample_grid_rejects_half_sample_durations(duration_ns: int) -> None:
    target = _target()
    compiler, request = _request(
        target,
        (
            _scheduled_program(
                "off-grid",
                qubit=Q0,
                duration_ns=duration_ns + 0.5,
            ),
        ),
        repetitions=1,
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert {
        "fake_list_event_duration_off_grid",
        "fake_list_program_duration_off_grid",
    } <= _issue_codes(raised.value)


def test_compiler_aggregates_physical_collision_and_capability_errors() -> None:
    target = _target(shared_output=True, shared_acquisition=True)
    compiler, request = _request(
        target,
        (
            _parallel_two_qubit_program(
                gaussian_q1=True,
                q0_amplitude_unit="V",
            ),
        ),
        repetitions=1,
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert {
        "fake_list_amplitude_unit_unsupported",
        "fake_list_envelope_unsupported",
        "fake_list_physical_acquisition_overlap",
        "fake_list_physical_output_overlap",
    } <= _issue_codes(raised.value)
    assert {issue.entry_id for issue in raised.value.issues} == {
        TargetCompileEntryId("entry-alpha")
    }


def test_drag_is_midpoint_sampled_into_a_complex_waveform() -> None:
    target = _target()
    compiler, request = _request(
        target,
        (_scheduled_drag_program("drag-program"),),
        repetitions=1,
    )

    artifact = compile_target(compiler, request).artifact
    samples = artifact.entries[0].waveforms[0].samples
    offsets_ns = (-1.5, -0.5, 0.5, 1.5)
    gaussians = tuple(0.2 * math.exp(-(offset**2) / 2.0) for offset in offsets_ns)
    expected = tuple(
        complex(gaussian, -0.5 * offset * gaussian)
        for offset, gaussian in zip(offsets_ns, gaussians, strict=True)
    )

    assert target.supported_envelopes == ("constant", "drag")
    assert samples == pytest.approx(expected)
    assert samples[0].real == pytest.approx(samples[-1].real)
    assert samples[0].imag == pytest.approx(-samples[-1].imag)


def test_drag_uses_complex_sample_magnitude_for_amplitude_limit() -> None:
    target = _target()
    compiler, request = _request(
        target,
        (
            _scheduled_drag_program(
                "drag-limit",
                amplitude=0.6,
                beta_ns=4.0,
            ),
        ),
        repetitions=1,
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert "fake_list_amplitude_limit_exceeded" in _issue_codes(raised.value)


def test_drag_artifact_fingerprint_is_deterministic_and_beta_sensitive() -> None:
    target = _target()
    compiler, request = _request(
        target,
        (_scheduled_drag_program("drag-fingerprint"),),
        repetitions=1,
    )
    first = compile_target(compiler, request).artifact
    second = compile_target(compiler, request).artifact
    changed_compiler, changed_request = _request(
        target,
        (
            _scheduled_drag_program(
                "drag-fingerprint",
                beta_ns=0.75,
            ),
        ),
        repetitions=1,
    )
    changed = compile_target(changed_compiler, changed_request).artifact

    assert first == second
    assert first.artifact_fingerprint == second.artifact_fingerprint
    assert changed.artifact_fingerprint != first.artifact_fingerprint


def test_compiler_rejects_unbound_signal_and_amplitude_limit() -> None:
    target = _target()
    unbound_compiler, unbound_request = _request(
        target,
        (_scheduled_program("unbound", qubit=Q2),),
        repetitions=1,
    )
    limit_compiler, limit_request = _request(
        target,
        (_scheduled_program("loud", qubit=Q0, amplitude=1.1),),
        repetitions=1,
    )

    with pytest.raises(TargetCompilationError) as unbound:
        compile_target(unbound_compiler, unbound_request)
    with pytest.raises(TargetCompilationError) as loud:
        compile_target(limit_compiler, limit_request)

    assert {
        "fake_list_acquisition_signal_unbound",
        "fake_list_output_signal_unbound",
    } <= _issue_codes(unbound.value)
    assert "fake_list_amplitude_limit_exceeded" in _issue_codes(loud.value)


def test_compiler_aggregates_batch_memory_repetition_and_frame_limits() -> None:
    constrained = replace(
        _target(),
        max_list_entries=1,
        max_waveform_memory_samples=1,
        max_capture_memory_samples=1,
        max_repetitions=1,
        max_frames=1,
    )
    compiler, request = _request(
        constrained,
        (
            _scheduled_program("q0-program", qubit=Q0),
            _scheduled_program("q1-program", qubit=Q1),
        ),
        repetitions=2,
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert {
        "fake_list_capture_memory_limit_exceeded",
        "fake_list_entry_limit_exceeded",
        "fake_list_frame_limit_exceeded",
        "fake_list_repetition_limit_exceeded",
        "fake_list_waveform_memory_limit_exceeded",
    } <= _issue_codes(raised.value)


def test_compiler_rejects_samples_per_entry_limit() -> None:
    target = replace(
        _target(),
        max_samples_per_entry=3,
        max_waveform_memory_samples=1,
        max_capture_memory_samples=1,
        max_frames=1,
    )
    compiler, request = _request(
        target,
        (_scheduled_program("too-long", qubit=Q0),),
        repetitions=2,
    )

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert {
        "fake_list_capture_memory_limit_exceeded",
        "fake_list_frame_limit_exceeded",
        "fake_list_samples_per_entry_limit_exceeded",
        "fake_list_waveform_memory_limit_exceeded",
    } <= _issue_codes(raised.value)


def test_capacity_limits_are_inclusive_at_the_exact_boundary() -> None:
    target = replace(
        _target(),
        max_list_entries=2,
        max_samples_per_entry=4,
        max_waveform_memory_samples=8,
        max_capture_memory_samples=8,
        max_repetitions=1,
        max_frames=2,
    )
    compiler, request = _request(
        target,
        (
            _scheduled_program("q0-boundary", qubit=Q0),
            _scheduled_program("q1-boundary", qubit=Q1),
        ),
        repetitions=1,
    )

    artifact = compile_target(compiler, request).artifact

    assert len(artifact.entries) == target.max_list_entries


def test_nonzero_event_start_must_lie_on_exact_sample_grid() -> None:
    slot = AcquisitionSlot(
        AcquisitionSlotId("offset-slot"),
        AcquisitionKind.INTEGRATED_IQ,
        ACQUIRE_Q0,
    )
    program = schedule(
        PulseProgram(
            PulseProgramId("offset-program"),
            PulseSequence(
                (
                    Delay(
                        PulseEventId("half-sample-delay"),
                        DRIVE_Q0,
                        Quantity(0.5, "ns"),
                    ),
                    PulseParallel(
                        (
                            Play(
                                PulseEventId("offset-play"),
                                DRIVE_Q0,
                                Constant(
                                    Quantity(1.5, "ns"),
                                    Quantity(0.2, "arb"),
                                ),
                            ),
                            Acquire(
                                PulseEventId("offset-acquire"),
                                ACQUIRE_Q0,
                                slot.id,
                                Quantity(1.5, "ns"),
                            ),
                        )
                    ),
                )
            ),
            acquisition_slots=(slot,),
        )
    )
    compiler, request = _request(_target(), (program,), repetitions=1)

    with pytest.raises(TargetCompilationError) as raised:
        compile_target(compiler, request)

    assert "fake_list_event_start_off_grid" in _issue_codes(raised.value)


@given(st.integers(min_value=1, max_value=12))
def test_runtime_frame_count_matches_repetitions_times_windows(
    repetitions: int,
) -> None:
    compiled = _compile_two_entries(repetitions=repetitions)

    run = FakeListRuntime().execute(compiled)

    assert len(run.playbacks) == repetitions * 2
    assert len(run.frames) == repetitions * 2
    assert len(
        {(frame.entry_id, frame.shot_index, frame.slot_id) for frame in run.frames}
    ) == len(run.frames)


def test_default_target_is_explicit_lab_owned_hardware_configuration() -> None:
    target = default_fake_list_target()

    assert target.id == TargetId("quantum-lab-demo.fake-list-mode.v1")
    assert target.sample_rate_hz == 1_000_000_000
    assert len(target.output_bindings) == 10
    assert len(target.acquisition_bindings) == 4
    assert target.supported_envelopes == ("constant", "drag")
    assert target.capability_fingerprint.startswith("sha256:")
