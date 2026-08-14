from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import numpy as np
import pytest
from scopecat import Quantity
from scopecat.planning.provider_binding import resolve_instrument_contract_catalog
from scopecat.records.measurement import (
    InstrumentAcquisitionEvidence,
    MeasurementArray,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareCollect,
    RunHardwareValue,
)
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
    Gaussian,
    Play,
    PulseProgram,
    ReadoutSignal,
    ScheduledPulseProgram,
    ShiftPhase,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.pulses import Sequence as PulseSequence
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompilationError,
    TargetCompileEntry,
    TargetCompileRequest,
)
from scopecat_quantum.waveforms import (
    Float64ReferenceRenderer,
    RenderedWaveforms,
    SampledWaveformPlan,
)

from reference_lab.configuration import bootstrap_config
from reference_lab.physical_policies import (
    IQ_OFFSET_COUPLING_POLICY_ID,
    IqOffsetCouplingGroupDefinition,
    IqOffsetPolicyDefinition,
    OutputOffsetRequirement,
    grouped_iq_offset_policy,
)
from reference_lab.provider import ReferenceLabProvider
from reference_lab.targets.list_mode import (
    ArtifactInspectionBounds,
    ListModeArtifact,
    ListModeTarget,
    ListModeTargetCompiler,
    configured_list_mode_target,
    inspect_list_mode_artifact,
)
from reference_lab.targets.list_mode.device_execution import InstrumentListModeRuntime
from reference_lab.targets.list_mode.model import IqMixerCalibration

Q0 = QubitId("q0")
Q1 = QubitId("q1")
DRIVE_Q0 = DriveSignal(Q0)
ACQUIRE_Q0 = AcquireSignal(Q0)
READOUT_Q0 = ReadoutSignal(Q0)
READOUT_Q1 = ReadoutSignal(Q1)


class _RecordingInstrumentExecutor:
    def __init__(self) -> None:
        self.batches: list[RunHardwareBatch] = []

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        self.batches.append(batch)
        now = datetime.now(UTC)
        values: list[RunHardwareValue] = []
        for action in batch.actions:
            if not isinstance(action, RunHardwareCollect):
                continue
            requests = {request.id: request for request in action.requests}
            for binding in action.bindings:
                request = requests[binding.request_id]
                [dimension] = request.dimensions
                assert dimension.size is not None
                for value_id in binding.value_ids:
                    capture_value: float | complex = float(len(values) + 1)
                    if request.dtype == "complex128":
                        capture_value = complex(capture_value)
                    values.append(
                        RunHardwareValue(
                            point_index=action.point_index,
                            value_id=value_id,
                            value=MeasurementArray.create(
                                dtype=request.dtype,
                                unit="V",
                                values=(capture_value,) * dimension.size,
                            ),
                            evidence=InstrumentAcquisitionEvidence(
                                command_id=action.effect_id,
                                instrument_id=action.instrument_id,
                                interface_id=request.interface_id,
                                component_path=tuple(request.component_path),
                                acquisition_id=request.acquisition_id,
                                result_id=request.result_id,
                                started_at=now,
                                completed_at=now,
                            ),
                        )
                    )
        return RunHardwareBatchReceipt(
            operation_id=batch.operation_id,
            values=tuple(values),
        )


class _IndeterminateInstrumentExecutor:
    def __init__(self) -> None:
        self.batches: list[RunHardwareBatch] = []

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        self.batches.append(batch)
        return RunHardwareBatchReceipt(
            operation_id=batch.operation_id,
            indeterminate=True,
        )


def _modulated_samples(
    amplitude: float,
    *,
    start_sample: int,
    sample_count: int,
    intermediate_frequency_hz: float,
    sample_rate_hz: int,
) -> tuple[complex, ...]:
    return tuple(
        amplitude
        * complex(
            math.cos(
                math.tau
                * intermediate_frequency_hz
                * (start_sample + index + 0.5)
                / sample_rate_hz
            ),
            math.sin(
                math.tau
                * intermediate_frequency_hz
                * (start_sample + index + 0.5)
                / sample_rate_hz
            ),
        )
        for index in range(sample_count)
    )


def _target() -> ListModeTarget:
    config = bootstrap_config()
    provider = ReferenceLabProvider()
    catalog = resolve_instrument_contract_catalog(
        config=config,
        provider_id=provider.provider_id,
        describe=provider.describe,
    )
    return configured_list_mode_target(config, catalog)


def _request(
    target: ListModeTarget,
    programs: Sequence[ScheduledPulseProgram],
    *,
    repetitions: int,
) -> tuple[ListModeTargetCompiler, TargetCompileRequest]:
    compiler = ListModeTargetCompiler(
        TargetCompilerId("list-mode-compiler.v1"),
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


def _calibrated_acquisition() -> tuple[ScheduledPulseProgram, AcquisitionSlot]:
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
    return scheduled, slot


def _compiled_calibrated_acquisition() -> tuple[
    ListModeTarget,
    ScheduledPulseProgram,
    AcquisitionSlot,
    ListModeArtifact,
]:
    scheduled, slot = _calibrated_acquisition()
    target = _target()
    compiler, request = _request(target, (scheduled,), repetitions=2)
    return target, scheduled, slot, compiler.compile(request)


def test_list_mode_compiler_projects_calibrated_physical_programs() -> None:
    target, scheduled, slot, artifact = _compiled_calibrated_acquisition()

    [entry] = artifact.entries
    drive_binding = target.output_binding(DRIVE_Q0)
    readout_binding = target.output_binding(READOUT_Q0)
    assert drive_binding is not None
    assert readout_binding is not None
    waveforms = {waveform.channel_id: waveform.samples for waveform in entry.waveforms}
    offset_requirements = artifact.host_state_requirements

    assert all(not waveform.flags.writeable for waveform in waveforms.values())
    assert all(waveform.flags.c_contiguous for waveform in waveforms.values())

    assert offset_requirements.policy_id == IQ_OFFSET_COUPLING_POLICY_ID
    assert offset_requirements.coupling_group_ids == (
        "drive-awg.outputs",
        "readout-awg.outputs",
    )
    assert {
        instrument_id: sum(
            requirement.channel_id.instrument_id == instrument_id
            for requirement in offset_requirements.output_offsets
        )
        for instrument_id in {"drive-awg", "readout-awg"}
    } == {"drive-awg": 9, "readout-awg": 2}
    assert set(waveforms) < {
        requirement.channel_id for requirement in offset_requirements.output_offsets
    }

    assert scheduled.duration_seconds == Decimal("12e-9")
    drive_samples = _modulated_samples(
        0.25,
        start_sample=0,
        sample_count=4,
        intermediate_frequency_hz=drive_binding.intermediate_frequency_hz,
        sample_rate_hz=target.sample_rate_hz,
    )
    readout_samples = _modulated_samples(
        0.4,
        start_sample=4,
        sample_count=8,
        intermediate_frequency_hz=readout_binding.intermediate_frequency_hz,
        sample_rate_hz=target.sample_rate_hz,
    )
    assert waveforms[drive_binding.i_channel_id] == pytest.approx(
        tuple(sample.real for sample in drive_samples) + (0.0,) * 8
    )
    assert waveforms[drive_binding.q_channel_id] == pytest.approx(
        tuple(sample.imag for sample in drive_samples) + (0.0,) * 8
    )
    assert waveforms[readout_binding.i_channel_id] == pytest.approx(
        (0.0,) * 4 + tuple(sample.real for sample in readout_samples)
    )
    assert waveforms[readout_binding.q_channel_id] == pytest.approx(
        (0.0,) * 4 + tuple(sample.imag for sample in readout_samples)
    )
    [window] = entry.acquisitions
    assert window.slot_id == slot.id
    assert (window.start_sample, window.sample_count) == (4, 8)
    assert window.input_id.component_path == ("inputs", "ch1")
    assert window.demodulator_slot_id.value == "demod0"
    assert window.intent.demodulation_frequency_hz == -300.0e6
    assert window.intent.output_representation == "integrated_iq"
    assert window.lowering.execution == "device"
    assert window.lowering.device_result_representation == "integrated_iq"
    assert len(artifact.awg_programs) == 2
    assert len(artifact.digitizer_programs) == 1
    assert artifact.instrument_ids == (
        "drive-awg",
        "readout-awg",
        "readout-digitizer",
        "timing-controller",
    )


def test_list_mode_worker_protocol_is_stable_per_execution_identity() -> None:
    _target, _scheduled, slot, artifact = _compiled_calibrated_acquisition()
    instruments = _RecordingInstrumentExecutor()
    instrument_runtime = InstrumentListModeRuntime()
    instrument_runtime.prepare(
        artifact,
        execution_id="test.calibrated-acquisition",
        instruments=instruments,
    )
    instrument_run = instrument_runtime.execute(
        artifact,
        execution_id="test.calibrated-acquisition",
        instruments=instruments,
    )
    assert instrument_run.results.addresses == (
        TargetAcquisitionAddress(
            entry_id=TargetCompileEntryId("entry-0"),
            slot_id=slot.id,
        ),
    )
    assert instrument_run.results.values.shape == (1, 2)
    assert instrument_run.results.values.nbytes == 2 * np.dtype(np.complex128).itemsize
    assert instrument_run.results.available.nbytes == 2 * np.dtype(np.bool_).itemsize
    assert not instrument_run.results.values.flags.writeable
    assert not instrument_run.results.available.flags.writeable
    assert np.all(instrument_run.results.available)
    first_value = cast("np.complex128", instrument_run.results.values[0, 0])
    second_value = cast("np.complex128", instrument_run.results.values[0, 1])
    assert second_value == pytest.approx(first_value)

    assert instruments.batches[0].operation_id.endswith(":load")
    assert instruments.batches[1].operation_id.endswith(":prepare")
    assert all(
        "target:test.calibrated-acquisition:" in batch.operation_id
        for batch in instruments.batches
    )
    assert [action.kind for action in instruments.batches[0].actions] == [
        "invoke",
        "invoke",
        "invoke",
        "invoke",
    ]
    assert [batch.operation_id.rsplit(":", 1)[-1] for batch in instruments.batches] == [
        "load",
        "prepare",
        "execute",
    ]
    assert [action.kind for action in instruments.batches[2].actions] == [
        "invoke",
        "invoke",
        "invoke",
        "invoke",
        "collect",
    ]

    other_execution = _RecordingInstrumentExecutor()
    other_runtime = InstrumentListModeRuntime()
    other_runtime.prepare(
        artifact,
        execution_id="test.other-invocation",
        instruments=other_execution,
    )
    other_runtime.execute(
        artifact,
        execution_id="test.other-invocation",
        instruments=other_execution,
    )
    assert {batch.operation_id for batch in instruments.batches}.isdisjoint(
        batch.operation_id for batch in other_execution.batches
    )
    retry = _RecordingInstrumentExecutor()
    retry_runtime = InstrumentListModeRuntime()
    retry_runtime.prepare(
        artifact,
        execution_id="test.calibrated-acquisition",
        instruments=retry,
    )
    retry_runtime.execute(
        artifact,
        execution_id="test.calibrated-acquisition",
        instruments=retry,
    )
    assert [batch.operation_id for batch in retry.batches] == [
        batch.operation_id for batch in instruments.batches
    ]


def test_list_mode_realtime_action_count_does_not_scale_with_repetitions() -> None:
    _target, _scheduled, _slot, artifact = _compiled_calibrated_acquisition()
    action_counts: list[list[int]] = []
    for repetitions in (1, 32):
        instruments = _RecordingInstrumentExecutor()
        runtime = InstrumentListModeRuntime()
        selected = replace(artifact, repetitions=repetitions)
        runtime.prepare(
            selected,
            execution_id=f"test.repetitions-{repetitions}",
            instruments=instruments,
        )
        runtime.execute(
            selected,
            execution_id=f"test.repetitions-{repetitions}",
            instruments=instruments,
        )
        action_counts.append([len(batch.actions) for batch in instruments.batches])

    assert action_counts == [[4, 3, 5], [4, 3, 5]]


def test_list_mode_acquisition_lowering_selects_target_or_device_dsp() -> None:
    target, scheduled, _slot, artifact = _compiled_calibrated_acquisition()
    [device_window] = artifact.entries[0].acquisitions
    assert device_window.lowering.execution == "device"
    assert device_window.lowering.device_result_representation == "integrated_iq"
    assert artifact.digitizer_programs[0].result_representation == "integrated_iq"

    target_dsp = replace(
        target,
        digitizer_result_representation="raw_trace",
    )
    target_compiler, target_request = _request(
        target_dsp,
        (scheduled,),
        repetitions=2,
    )
    target_artifact = target_compiler.compile(target_request)
    [target_window] = target_artifact.entries[0].acquisitions
    assert target_window.intent == device_window.intent
    assert target_window.lowering.execution == "target"
    assert target_window.lowering.device_result_representation == "raw_trace"
    assert target_artifact.digitizer_programs[0].result_representation == "raw_trace"


def test_indeterminate_awg_program_load_stops_before_realtime() -> None:
    scheduled, _slot = _calibrated_acquisition()
    compiler, request = _request(_target(), (scheduled,), repetitions=1)
    artifact = compiler.compile(request)
    instruments = _IndeterminateInstrumentExecutor()

    with pytest.raises(RuntimeError, match="outcome is indeterminate"):
        InstrumentListModeRuntime().prepare(
            artifact,
            execution_id="test.indeterminate-load",
            instruments=instruments,
        )

    assert len(instruments.batches) == 1
    assert instruments.batches[0].operation_id.endswith(":load")


def test_offset_coupling_groups_may_split_one_physical_awg() -> None:
    target = _target()
    [guard_requirement] = tuple(
        requirement
        for group in target.host_state_policy.coupling_groups
        for requirement in group.output_offsets
        if requirement.channel_id.component_path == ("outputs", "ch9")
    )
    target = replace(
        target,
        host_state_policy=grouped_iq_offset_policy(
            policy=IqOffsetPolicyDefinition(
                id=IQ_OFFSET_COUPLING_POLICY_ID,
                coupling_groups=(
                    IqOffsetCouplingGroupDefinition(
                        id="drive-awg.bank-01",
                        activation_chain_ids=("drive-q0", "drive-q1"),
                        required_chain_ids=("drive-q0", "drive-q1"),
                        required_output_slot_ids=("guard",),
                    ),
                    IqOffsetCouplingGroupDefinition(
                        id="drive-awg.bank-23",
                        activation_chain_ids=("drive-q2", "drive-q3"),
                        required_chain_ids=("drive-q2", "drive-q3"),
                    ),
                    IqOffsetCouplingGroupDefinition(
                        id="readout-awg.outputs",
                        activation_chain_ids=("readout",),
                        required_chain_ids=("readout",),
                    ),
                ),
            ),
            output_slots={"guard": guard_requirement},
            chain_outputs={
                binding.iq_chain_id: (
                    OutputOffsetRequirement(
                        channel_id=binding.i_channel_id,
                        offset_v=binding.mixer.i_offset_v,
                    ),
                    OutputOffsetRequirement(
                        channel_id=binding.q_channel_id,
                        offset_v=binding.mixer.q_offset_v,
                    ),
                )
                for binding in target.output_bindings
            },
        ),
    )
    scheduled = schedule(
        PulseProgram(
            PulseProgramId("q0-drive-only"),
            Play(
                PulseEventId("drive"),
                DRIVE_Q0,
                Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
            ),
        )
    )
    compiler, request = _request(target, (scheduled,), repetitions=1)

    requirements = compiler.compile(request).host_state_requirements

    assert requirements.coupling_group_ids == ("drive-awg.bank-01",)
    assert {
        requirement.channel_id.component_path
        for requirement in requirements.output_offsets
    } == {
        ("outputs", "ch1"),
        ("outputs", "ch2"),
        ("outputs", "ch3"),
        ("outputs", "ch4"),
        ("outputs", "ch9"),
    }


def test_list_mode_samples_drag_and_tracks_beta_in_artifact_identity() -> None:
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
    baseband = tuple(
        complex(gaussian, -0.5 * offset * gaussian)
        for offset, gaussian in zip(offsets_ns, gaussians, strict=True)
    )
    carrier = _modulated_samples(
        1.0,
        start_sample=0,
        sample_count=4,
        intermediate_frequency_hz=binding.intermediate_frequency_hz,
        sample_rate_hz=target.sample_rate_hz,
    )
    expected = tuple(
        envelope * rotation
        for envelope, rotation in zip(baseband, carrier, strict=True)
    )

    assert target.supported_envelopes == ("constant", "gaussian", "drag")
    assert waveforms[binding.i_channel_id] == pytest.approx(
        tuple(sample.real for sample in expected)
    )
    assert waveforms[binding.q_channel_id] == pytest.approx(
        tuple(sample.imag for sample in expected)
    )
    assert changed.artifact_fingerprint != baseline.artifact_fingerprint


def test_list_mode_renders_gaussian_and_records_realized_timing() -> None:
    target = _target()
    scheduled = schedule(
        PulseProgram(
            id=PulseProgramId("gaussian"),
            body=Play(
                PulseEventId("gaussian-play"),
                DRIVE_Q0,
                Gaussian(
                    duration=Quantity(2.4, "ns"),
                    amplitude=Quantity(0.2, "arb"),
                    sigma=Quantity(1, "ns"),
                ),
            ),
        )
    )
    compiler, request = _request(target, (scheduled,), repetitions=1)

    artifact = compiler.compile(request)
    [entry] = artifact.entries
    [timing] = entry.event_timings
    binding = target.output_binding(DRIVE_Q0)
    assert binding is not None
    waveforms = {waveform.channel_id: waveform.samples for waveform in entry.waveforms}
    gaussian = 0.2 * math.exp(-(0.5**2) / 2.0)
    carrier = _modulated_samples(
        gaussian,
        start_sample=0,
        sample_count=2,
        intermediate_frequency_hz=binding.intermediate_frequency_hz,
        sample_rate_hz=target.sample_rate_hz,
    )

    assert artifact.waveform_semantics_id == "scopecat.sampled.midpoint.v1"
    assert artifact.timing_quantization == "nearest"
    assert timing.requested_duration_seconds == Decimal("2.4E-9")
    assert timing.sample_count == 2
    assert timing.realized_duration_seconds == Decimal("2E-9")
    assert timing.duration_error_seconds == Decimal("-4E-10")
    assert waveforms[binding.i_channel_id] == pytest.approx(
        tuple(sample.real for sample in carrier)
    )
    assert waveforms[binding.q_channel_id] == pytest.approx(
        tuple(sample.imag for sample in carrier)
    )


def test_list_mode_artifact_inspection_is_bounded_and_preserves_peaks() -> None:
    target = _target()
    scheduled = schedule(
        PulseProgram(
            id=PulseProgramId("preview"),
            body=Play(
                PulseEventId("preview-play"),
                DRIVE_Q0,
                Gaussian(
                    duration=Quantity(100.4, "ns"),
                    amplitude=Quantity(0.8, "arb"),
                    sigma=Quantity(2, "ns"),
                ),
            ),
        )
    )
    compiler, request = _request(target, (scheduled, scheduled), repetitions=3)
    artifact = compiler.compile(request)

    inspection = inspect_list_mode_artifact(
        artifact,
        bounds=ArtifactInspectionBounds(
            max_entries=1,
            max_channels_per_entry=1,
            max_samples_per_waveform=10,
        ),
    )
    [entry] = inspection.points
    [preview] = entry.waveforms
    source = artifact.entry_waveforms(artifact.entries[0])[0].samples

    assert inspection.schema_id == "scopecat.compiled_artifact_inspection.v1"
    assert inspection.kind == "reference_lab.list_mode.v1"
    assert inspection.point_count == 2
    assert inspection.points_truncated
    assert inspection.fact("max_abs_boundary_error_seconds").value == "4E-10"
    assert entry.waveform_count == 2
    assert entry.waveforms_truncated
    assert preview.source_sample_count == 100
    assert len(preview.samples) <= 10
    assert preview.sample_indices == tuple(sorted(preview.sample_indices))
    assert preview.peak_abs == float(cast("np.float64", np.max(np.abs(source))))
    assert preview.peak_abs == max(abs(sample) for sample in preview.samples)
    assert inspection.bounds.max_points == 1
    assert inspection.bounds.max_waveforms_per_point == 1
    assert inspection.bounds.max_samples_per_waveform == 10

    complete = inspect_list_mode_artifact(
        artifact,
        bounds=ArtifactInspectionBounds(max_entries=2),
    )
    assert complete.points[0].realization_fingerprint == (
        complete.points[1].realization_fingerprint
    )


def test_list_mode_applies_shift_phase_before_playback() -> None:
    target = _target()
    scheduled = schedule(
        PulseProgram(
            id=PulseProgramId("phase-shift"),
            body=PulseSequence(
                (
                    ShiftPhase(
                        PulseEventId("shift"),
                        DRIVE_Q0,
                        Quantity(math.pi / 2, "rad"),
                    ),
                    Play(
                        PulseEventId("play"),
                        DRIVE_Q0,
                        Constant(Quantity(2, "ns"), Quantity(0.25, "arb")),
                    ),
                )
            ),
        )
    )
    compiler, request = _request(target, (scheduled,), repetitions=1)

    artifact = compiler.compile(request)
    binding = target.output_binding(DRIVE_Q0)
    assert binding is not None
    waveforms = {
        waveform.channel_id: waveform.samples
        for waveform in artifact.entries[0].waveforms
    }
    expected = tuple(
        sample * 1j
        for sample in _modulated_samples(
            0.25,
            start_sample=0,
            sample_count=2,
            intermediate_frequency_hz=binding.intermediate_frequency_hz,
            sample_rate_hz=target.sample_rate_hz,
        )
    )

    assert waveforms[binding.i_channel_id] == pytest.approx(
        tuple(sample.real for sample in expected)
    )
    assert waveforms[binding.q_channel_id] == pytest.approx(
        tuple(sample.imag for sample in expected)
    )


def test_list_mode_factors_phase_sweeps_without_per_point_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target()
    rendered_plans: list[SampledWaveformPlan] = []
    render = Float64ReferenceRenderer.render

    def record_render(
        self: Float64ReferenceRenderer,
        plan: SampledWaveformPlan,
    ) -> RenderedWaveforms:
        rendered_plans.append(plan)
        return render(self, plan)

    monkeypatch.setattr(Float64ReferenceRenderer, "render", record_render)

    def phase_program(program_id: str, phase: float) -> ScheduledPulseProgram:
        return schedule(
            PulseProgram(
                id=PulseProgramId(program_id),
                body=PulseSequence(
                    (
                        ShiftPhase(
                            PulseEventId("shift"),
                            DRIVE_Q0,
                            Quantity(phase, "rad"),
                        ),
                        Play(
                            PulseEventId("play"),
                            DRIVE_Q0,
                            Constant(Quantity(2, "ns"), Quantity(0.25, "arb")),
                        ),
                    )
                ),
            )
        )

    programs = (
        phase_program("phase-zero", 0.0),
        phase_program("phase-quarter", math.pi / 2),
    )
    compiler, request = _request(target, programs, repetitions=1)

    artifact = compiler.compile(request)

    assert artifact.phase_templates
    assert all(not entry.waveforms for entry in artifact.entries)
    assert len(rendered_plans) == 1
    for index, program in enumerate(programs):
        concrete_compiler, concrete_request = _request(
            target,
            (program,),
            repetitions=1,
        )
        concrete = concrete_compiler.compile(concrete_request)
        synthesized = artifact.entry_waveforms(artifact.entries[index])
        assert [waveform.channel_id for waveform in synthesized] == [
            waveform.channel_id for waveform in concrete.entries[0].waveforms
        ]
        for actual, expected_waveform in zip(
            synthesized,
            concrete.entries[0].waveforms,
            strict=True,
        ):
            np.testing.assert_allclose(
                actual.samples,
                expected_waveform.samples,
                atol=1e-15,
            )
        assert artifact.materialized_waveform_bytes(artifact.entries[index]) == sum(
            waveform.samples.nbytes for waveform in concrete.entries[0].waveforms
        )


def test_list_mode_defers_compact_sweep_amplitude_check_until_materialization() -> None:
    target = replace(_target(), max_abs_amplitude=0.1)

    def phase_program(program_id: str, phase: float) -> ScheduledPulseProgram:
        return schedule(
            PulseProgram(
                id=PulseProgramId(program_id),
                body=PulseSequence(
                    (
                        ShiftPhase(
                            PulseEventId("shift"),
                            DRIVE_Q0,
                            Quantity(phase, "rad"),
                        ),
                        Play(
                            PulseEventId("play"),
                            DRIVE_Q0,
                            Constant(Quantity(2, "ns"), Quantity(0.25, "arb")),
                        ),
                    )
                ),
            )
        )

    compiler, request = _request(
        target,
        (
            phase_program("phase-zero", 0.0),
            phase_program("phase-quarter", math.pi / 2),
        ),
        repetitions=1,
    )

    artifact = compiler.compile(request)

    with pytest.raises(ValueError, match=r"target limit is 0\.1"):
        artifact.entry_waveforms(artifact.entries[0])


def test_list_mode_checks_final_peak_after_readout_accumulation() -> None:
    target = _target()
    target = replace(
        target,
        output_bindings=tuple(
            replace(binding, intermediate_frequency_hz=0.0)
            if binding.signal in {READOUT_Q0, READOUT_Q1}
            else binding
            for binding in target.output_bindings
        ),
    )
    scheduled = schedule(
        PulseProgram(
            id=PulseProgramId("multiplexed-peak"),
            body=PulseParallel(
                (
                    Play(
                        PulseEventId("readout-q0"),
                        READOUT_Q0,
                        Constant(Quantity(2, "ns"), Quantity(0.6, "arb")),
                    ),
                    Play(
                        PulseEventId("readout-q1"),
                        READOUT_Q1,
                        Constant(Quantity(2, "ns"), Quantity(0.6, "arb")),
                    ),
                )
            ),
        )
    )
    compiler, request = _request(target, (scheduled,), repetitions=1)

    with pytest.raises(TargetCompilationError) as caught:
        compiler.compile(request)

    assert {issue.code for issue in caught.value.issues} == {
        "list_mode_amplitude_limit_exceeded"
    }


def test_list_mode_rejects_programs_larger_than_awg_memory() -> None:
    scheduled, _slot = _calibrated_acquisition()
    target = replace(_target(), max_program_waveform_bytes=1)
    compiler, request = _request(target, (scheduled,), repetitions=1)

    with pytest.raises(TargetCompilationError) as caught:
        compiler.compile(request)

    assert {issue.code for issue in caught.value.issues} == {
        "list_mode_program_waveform_memory_exceeded"
    }


def test_list_mode_applies_full_iq_mixer_matrix_to_physical_waveforms() -> None:
    target = _target()
    binding = target.output_binding(DRIVE_Q0)
    assert binding is not None
    calibrated_binding = replace(
        binding,
        mixer=IqMixerCalibration(
            ii=0.8,
            iq=0.1,
            qi=-0.2,
            qq=0.9,
            i_offset_v=0.01,
            q_offset_v=-0.02,
        ),
    )
    target = replace(
        target,
        output_bindings=tuple(
            calibrated_binding if candidate == binding else candidate
            for candidate in target.output_bindings
        ),
    )
    scheduled = schedule(
        PulseProgram(
            PulseProgramId("mixer-calibration"),
            Play(
                PulseEventId("drive"),
                DRIVE_Q0,
                Constant(Quantity(4, "ns"), Quantity(0.25, "arb")),
            ),
        )
    )
    compiler, request = _request(target, (scheduled,), repetitions=1)

    artifact = compiler.compile(request)
    waveforms = {
        waveform.channel_id: waveform.samples
        for waveform in artifact.entries[0].waveforms
    }
    ideal = _modulated_samples(
        0.25,
        start_sample=0,
        sample_count=4,
        intermediate_frequency_hz=calibrated_binding.intermediate_frequency_hz,
        sample_rate_hz=target.sample_rate_hz,
    )
    assert waveforms[calibrated_binding.i_channel_id] == pytest.approx(
        tuple(0.8 * sample.real + 0.1 * sample.imag for sample in ideal)
    )
    assert waveforms[calibrated_binding.q_channel_id] == pytest.approx(
        tuple(-0.2 * sample.real + 0.9 * sample.imag for sample in ideal)
    )
