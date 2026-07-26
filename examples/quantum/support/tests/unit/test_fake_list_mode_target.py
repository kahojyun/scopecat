from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

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
    TargetCompilerId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall, GateDefinition
from scopecat_quantum.programs import (
    CircuitPulseEventProvenance,
    QuantumProgramIR,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
)
from scopecat_quantum.programs import Sequence as QuantumSequence
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
    DriveSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
    ScheduledPulseProgram,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.targets import TargetCompileEntry, TargetCompileRequest

from quantum_lab_demo.targets.fake_list_mode import (
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    configured_fake_list_target,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile

Q0 = QubitId("q0")
DRIVE_Q0 = DriveSignal(Q0)
ACQUIRE_Q0 = AcquireSignal(Q0)
READOUT_Q0 = ReadoutSignal(Q0)


def _target() -> FakeListTarget:
    return configured_fake_list_target(quantum_wiring_config_profile())


def _request(
    target: FakeListTarget,
    programs: Sequence[ScheduledPulseProgram],
    *,
    repetitions: int,
) -> tuple[FakeListTargetCompiler, TargetCompileRequest]:
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    request = TargetCompileRequest(
        entries=tuple(
            TargetCompileEntry(
                TargetCompileEntryId(f"entry-{index}"),
                program,
            )
            for index, program in enumerate(programs)
        ),
        repetitions=repetitions,
    )
    return compiler, request


def test_fake_list_compiles_and_runs_one_calibrated_acquisition() -> None:
    gate = GateDefinition(GateId("x"), qubit_arity=1)
    gate_call = GateCall(CircuitOperationId("x"), gate.id, (Q0,))
    measurement = Measure(
        CircuitOperationId("measure"),
        Q0,
        AcquisitionSlotId("result"),
        AcquisitionKind.INTEGRATED_IQ,
    )
    program = verify_quantum_program(
        QuantumProgramIR(
            QuantumProgramId("x-then-measure"),
            QuantumSequence((gate_call, measurement)),
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
    lowered = lower_quantum_program_to_pulses(
        program,
        ResolvedPulseImplementations(
            gates=(
                GatePulseImplementation(
                    PulseImplementationId("x-q0"),
                    GatePulseImplementationKey.from_call(gate_call),
                    gate_template,
                ),
            ),
            measurements=(
                MeasurementPulseImplementation(
                    PulseImplementationId("readout-q0"),
                    MeasurementPulseImplementationKey.from_measurement(measurement),
                    measurement_template,
                ),
            ),
        ),
        output_id=PulseProgramId("x-then-readout"),
    )
    scheduled = schedule(lowered.program)
    target = _target()
    compiler, request = _request(target, (scheduled,), repetitions=2)

    artifact = compiler.compile(request)
    [entry] = artifact.entries
    drive_channel = target.output_channel(DRIVE_Q0)
    readout_channel = target.output_channel(READOUT_Q0)
    assert drive_channel is not None
    assert readout_channel is not None
    waveforms = {waveform.channel_id: waveform.samples for waveform in entry.waveforms}

    assert scheduled.duration_seconds == Decimal("12e-9")
    assert waveforms[drive_channel] == (0.25 + 0j,) * 4 + (0j,) * 8
    assert waveforms[readout_channel] == (0j,) * 4 + (0.4 + 0j,) * 8
    [window] = entry.acquisitions
    assert window.slot_id == measurement.acquisition_slot_id
    assert (window.start_sample, window.sample_count) == (4, 8)
    assert any(
        isinstance(origin, CircuitPulseEventProvenance)
        and origin.operation_id == measurement.id
        for origin in lowered.event_provenance
    )

    run = FakeListRuntime().execute(artifact)
    assert [
        (frame.shot_index, frame.entry_id, frame.slot_id) for frame in run.frames
    ] == [
        (shot, TargetCompileEntryId("entry-0"), measurement.acquisition_slot_id)
        for shot in range(2)
    ]
    assert all(isinstance(frame.value, complex) for frame in run.frames)


def test_fake_list_samples_drag_and_tracks_beta_in_artifact_identity() -> None:
    def compile_drag(beta_ns: float):
        target = _target()
        scheduled = schedule(
            PulseProgram(
                id=PulseProgramId("drag"),
                body=Play(
                    PulseEventId("drag-play"),
                    DRIVE_Q0,
                    DRAG(
                        duration=Quantity(4, "ns"),
                        amplitude=Quantity(0.2, "arb"),
                        sigma=Quantity(1, "ns"),
                        beta=Quantity(beta_ns, "ns"),
                    ),
                ),
            )
        )
        compiler, request = _request(target, (scheduled,), repetitions=1)
        return target, compiler.compile(request)

    target, baseline = compile_drag(0.5)
    _, changed = compile_drag(0.75)
    samples = baseline.entries[0].waveforms[0].samples
    offsets_ns = (-1.5, -0.5, 0.5, 1.5)
    gaussians = tuple(0.2 * math.exp(-(offset**2) / 2.0) for offset in offsets_ns)
    expected = tuple(
        complex(gaussian, -0.5 * offset * gaussian)
        for offset, gaussian in zip(offsets_ns, gaussians, strict=True)
    )

    assert target.supported_envelopes == ("constant", "drag")
    assert samples == pytest.approx(expected)
    assert changed.artifact_fingerprint != baseline.artifact_fingerprint
