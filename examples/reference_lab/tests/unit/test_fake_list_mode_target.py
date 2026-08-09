from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal

import pytest
from scopecat import Quantity
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
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
from scopecat_quantum.pulses import Sequence as PulseSequence
from scopecat_quantum.targets import TargetCompileEntry, TargetCompileRequest

from reference_lab.configuration import bootstrap_config
from reference_lab.targets.fake_list_mode import (
    FakeListRuntime,
    FakeListTarget,
    FakeListTargetCompiler,
    configured_fake_list_target,
)

Q0 = QubitId("q0")
DRIVE_Q0 = DriveSignal(Q0)
ACQUIRE_Q0 = AcquireSignal(Q0)
READOUT_Q0 = ReadoutSignal(Q0)


def _target() -> FakeListTarget:
    return configured_fake_list_target(bootstrap_config())


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
    slot = AcquisitionSlot(
        AcquisitionSlotId("result"),
        AcquisitionKind.INTEGRATED_IQ,
        ACQUIRE_Q0,
    )
    scheduled = schedule(
        PulseProgram(
            PulseProgramId("x-then-readout"),
            PulseSequence(
                (
                    Play(
                        PulseEventId("drive"),
                        DRIVE_Q0,
                        Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
                    ),
                    PulseParallel(
                        (
                            Play(
                                PulseEventId("stimulus"),
                                READOUT_Q0,
                                Constant(
                                    Quantity(8, "ns"),
                                    Quantity(0.4, "arb"),
                                ),
                            ),
                            Acquire(
                                PulseEventId("capture"),
                                ACQUIRE_Q0,
                                slot.id,
                                Quantity(8, "ns"),
                            ),
                        )
                    ),
                )
            ),
            acquisition_slots=(slot,),
        )
    )
    target = _target()
    compiler, request = _request(target, (scheduled,), repetitions=2)

    artifact = compiler.compile(request)
    [entry] = artifact.entries
    drive_binding = target.output_binding(DRIVE_Q0)
    readout_binding = target.output_binding(READOUT_Q0)
    assert drive_binding is not None
    assert readout_binding is not None
    waveforms = {waveform.channel_id: waveform.samples for waveform in entry.waveforms}

    assert scheduled.duration_seconds == Decimal("12e-9")
    assert waveforms[drive_binding.i_channel_id] == (0.25,) * 4 + (0.0,) * 8
    assert waveforms[drive_binding.q_channel_id] == (0.0,) * 12
    assert waveforms[readout_binding.i_channel_id] == (0.0,) * 4 + (0.4,) * 8
    assert waveforms[readout_binding.q_channel_id] == (0.0,) * 12
    [window] = entry.acquisitions
    assert window.slot_id == slot.id
    assert (window.start_sample, window.sample_count) == (4, 8)

    run = FakeListRuntime().execute(artifact)
    assert [
        (frame.shot_index, frame.entry_id, frame.slot_id) for frame in run.frames
    ] == [(shot, TargetCompileEntryId("entry-0"), slot.id) for shot in range(2)]
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
    binding = target.output_binding(DRIVE_Q0)
    assert binding is not None
    waveforms = {
        waveform.channel_id: waveform.samples
        for waveform in baseline.entries[0].waveforms
    }
    offsets_ns = (-1.5, -0.5, 0.5, 1.5)
    gaussians = tuple(0.2 * math.exp(-(offset**2) / 2.0) for offset in offsets_ns)
    expected = tuple(
        complex(gaussian, -0.5 * offset * gaussian)
        for offset, gaussian in zip(offsets_ns, gaussians, strict=True)
    )

    assert target.supported_envelopes == ("constant", "drag")
    assert waveforms[binding.i_channel_id] == pytest.approx(
        tuple(sample.real for sample in expected)
    )
    assert waveforms[binding.q_channel_id] == pytest.approx(
        tuple(sample.imag for sample in expected)
    )
    assert changed.artifact_fingerprint != baseline.artifact_fingerprint
