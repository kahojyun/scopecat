"""Deterministic sampled-output planning and reference rendering.

The pulse scheduler retains exact continuous time.  This module owns the
portable sampled-output semantics that begin after a laboratory has selected
numeric output lanes and end before device-specific quantization or encoding.
One plan belongs to one sample grid; targets with heterogeneous clocks build
one plan per physical timing domain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray

from scopecat_quantum._ids import PulseEventId, PulseProgramId
from scopecat_quantum.pulses import (
    DRAG,
    AnalyticEnvelope,
    Constant,
    CosineFlatTop,
    DriveSignal,
    FrameSignal,
    Gaussian,
    Play,
    PlaySignal,
    ReadoutSignal,
    ScheduledPulseEvent,
    ScheduledPulseProgram,
    ShiftPhase,
)

MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID = "scopecat.sampled.midpoint.v1"
LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID = "scopecat.sampled.left-edge.v1"
SAMPLED_WAVEFORM_SEMANTICS_ID = MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID

type TimingQuantizationMode = Literal["strict", "nearest"]
type SampleLocation = Literal["midpoint", "left_edge"]
type CarrierPhaseReference = Literal[
    "schedule_origin",
    "signal_first_play",
    "event_origin",
]
type SampledWaveformSemanticsId = Literal[
    "scopecat.sampled.midpoint.v1",
    "scopecat.sampled.left-edge.v1",
]


@dataclass(frozen=True, slots=True)
class TimingQuantizationPolicy:
    """How exact continuous boundaries are projected onto one sample grid."""

    mode: TimingQuantizationMode = "nearest"
    boundary_rounding: Literal["half_even"] = "half_even"


@dataclass(frozen=True, slots=True)
class SampleGrid:
    """One fixed sampled-output clock and its boundary policy."""

    sample_rate_hz: int
    timing: TimingQuantizationPolicy = field(default_factory=TimingQuantizationPolicy)
    sample_location: SampleLocation = "midpoint"

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample rate must be positive")


@dataclass(frozen=True, slots=True)
class IqMatrix:
    """Linear map from one ideal complex sample to two physical lanes."""

    ii: float
    iq: float
    qi: float
    qq: float


@dataclass(frozen=True, slots=True)
class SampledOutputBinding:
    """Numeric realization of one logical output on two renderer lanes."""

    signal: PlaySignal
    i_lane: int
    q_lane: int
    intermediate_frequency_hz: float
    mixer: IqMatrix
    carrier_phase_reference: CarrierPhaseReference = "schedule_origin"


@dataclass(frozen=True, slots=True)
class RealizedEventTiming:
    """Requested continuous timing and its deterministic sampled realization."""

    event_id: PulseEventId
    requested_start_seconds: Decimal
    requested_duration_seconds: Decimal
    sample_rate_hz: int
    start_sample: int
    sample_count: int

    @property
    def end_sample(self) -> int:
        return self.start_sample + self.sample_count

    @property
    def realized_start_seconds(self) -> Decimal:
        return _sample_seconds(self.start_sample, self.sample_rate_hz)

    @property
    def realized_duration_seconds(self) -> Decimal:
        return _sample_seconds(self.sample_count, self.sample_rate_hz)

    @property
    def start_error_seconds(self) -> Decimal:
        return self.realized_start_seconds - self.requested_start_seconds

    @property
    def duration_error_seconds(self) -> Decimal:
        return self.realized_duration_seconds - self.requested_duration_seconds


@dataclass(frozen=True, slots=True)
class SampledRenderEvent:
    """One fully timed and frame-resolved analytic output event."""

    event_id: PulseEventId
    envelope: AnalyticEnvelope
    timing: RealizedEventTiming
    binding: SampledOutputBinding
    effective_phase_radians: float
    carrier_origin_seconds: Decimal


@dataclass(frozen=True, slots=True)
class SampledWaveformPlan:
    """Pure numeric work for one scheduled program and one sample grid."""

    program_id: PulseProgramId
    semantics_id: SampledWaveformSemanticsId
    grid: SampleGrid
    sample_count: int
    lane_count: int
    event_timings: tuple[RealizedEventTiming, ...]
    render_events: tuple[SampledRenderEvent, ...]

    def timing_for(self, event_id: PulseEventId) -> RealizedEventTiming:
        for timing in self.event_timings:
            if timing.event_id == event_id:
                return timing
        raise KeyError(event_id)


@dataclass(frozen=True, slots=True)
class PhaseParameterizedSampledWaveforms:
    """One sampled-waveform structure plus a phase row for each entry."""

    template: SampledWaveformPlan
    phase_rows: tuple[tuple[float, ...], ...]


def factor_phase_parameterized_waveforms(
    plans: tuple[SampledWaveformPlan, ...],
) -> PhaseParameterizedSampledWaveforms | None:
    """Factor a complete batch when phase is its only varying render input.

    Return ``None`` unless at least two plans share their grid, shape, timing,
    bindings, and envelope structure so callers can retain ordinary per-plan
    rendering.
    """

    if len(plans) < 2:
        return None
    reference = plans[0]
    if not reference.render_events:
        return None
    for candidate in plans[1:]:
        if (
            candidate.semantics_id != reference.semantics_id
            or candidate.grid != reference.grid
            or candidate.sample_count != reference.sample_count
            or candidate.lane_count != reference.lane_count
            or not _same_render_structure(
                reference.render_events,
                candidate.render_events,
            )
        ):
            return None
    return PhaseParameterizedSampledWaveforms(
        template=replace(
            reference,
            render_events=tuple(
                replace(event, effective_phase_radians=0.0)
                for event in reference.render_events
            ),
        ),
        phase_rows=tuple(
            tuple(event.effective_phase_radians for event in plan.render_events)
            for plan in plans
        ),
    )


def _same_render_structure(
    reference: tuple[SampledRenderEvent, ...],
    candidate: tuple[SampledRenderEvent, ...],
) -> bool:
    return len(reference) == len(candidate) and all(
        reference_event.binding == candidate_event.binding
        and reference_event.timing.start_sample == candidate_event.timing.start_sample
        and reference_event.timing.sample_count == candidate_event.timing.sample_count
        and reference_event.carrier_origin_seconds
        == candidate_event.carrier_origin_seconds
        and replace(
            candidate_event.envelope,
            phase=reference_event.envelope.phase,
        )
        == reference_event.envelope
        for reference_event, candidate_event in zip(
            reference,
            candidate,
            strict=True,
        )
    )


@dataclass(frozen=True, slots=True, eq=False)
class RenderedWaveforms:
    """Read-only normalized physical-lane buffers and their final peaks."""

    semantics_id: SampledWaveformSemanticsId
    sample_rate_hz: int
    buffers: tuple[NDArray[np.float64], ...]
    lane_peaks: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class WaveformPlanningIssue:
    """One deterministic failure while realizing a continuous schedule."""

    code: str
    message: str
    event_id: PulseEventId | None = None


class WaveformPlanningError(ValueError):
    """Aggregate of independently discoverable sampled-output failures."""

    __slots__ = ("issues",)

    def __init__(self, issues: tuple[WaveformPlanningIssue, ...]) -> None:
        if not issues:
            raise ValueError("waveform planning errors require at least one issue")
        self.issues = tuple(sorted(set(issues), key=_issue_sort_key))
        super().__init__("; ".join(issue.message for issue in self.issues))


def realize_event_timings(
    events: tuple[ScheduledPulseEvent, ...],
    *,
    grid: SampleGrid,
) -> tuple[RealizedEventTiming, ...]:
    """Project exact event boundaries onto one sampled-output clock.

    This timing-only entry point lets device targets reuse the same continuous
    schedule semantics even when their waveform encoding or renderer remains
    device-specific.  Every shared boundary is quantized once.
    """

    boundaries = {
        boundary
        for event in events
        for boundary in (
            event.start_seconds,
            event.start_seconds + event.duration_seconds,
        )
    }
    boundary_samples = {
        boundary: _quantize_boundary(boundary, grid) for boundary in boundaries
    }
    issues: list[WaveformPlanningIssue] = []
    timings = _realize_event_timings(
        events,
        grid=grid,
        boundary_samples=boundary_samples,
        issues=issues,
    )
    if issues:
        raise WaveformPlanningError(tuple(issues))
    return timings


def plan_sampled_waveforms(
    program: ScheduledPulseProgram,
    *,
    bindings: tuple[SampledOutputBinding, ...],
    grid: SampleGrid,
) -> SampledWaveformPlan:
    """Resolve exact boundaries, output bindings, and phase frames.

    Every unique absolute boundary is quantized once.  Adjacent events therefore
    share the same integer boundary and cannot acquire a rounding gap or overlap.
    """

    issues: list[WaveformPlanningIssue] = []
    binding_by_signal: dict[PlaySignal, SampledOutputBinding] = {}
    for binding in bindings:
        if binding.signal in binding_by_signal:
            issues.append(
                WaveformPlanningIssue(
                    code="sampled_output_binding_duplicate",
                    message=(
                        f"logical output {binding.signal!r} is bound more than once"
                    ),
                )
            )
        else:
            binding_by_signal[binding.signal] = binding

    boundaries = {Decimal(0), program.duration_seconds}
    for event in program.events:
        boundaries.add(event.start_seconds)
        boundaries.add(event.start_seconds + event.duration_seconds)
    boundary_samples = {
        boundary: _quantize_boundary(boundary, grid) for boundary in boundaries
    }

    program_end_sample = boundary_samples[program.duration_seconds]
    if program_end_sample is None:
        issues.append(
            WaveformPlanningIssue(
                code="sampled_program_duration_off_grid",
                message=(
                    f"program {program.id.value!r} duration is not on the strict "
                    "sample grid"
                ),
            )
        )
    elif program.duration_seconds > 0 and program_end_sample <= 0:
        issues.append(
            WaveformPlanningIssue(
                code="sampled_program_collapsed",
                message=f"program {program.id.value!r} collapses to zero samples",
            )
        )

    timings = _realize_event_timings(
        program.events,
        grid=grid,
        boundary_samples=boundary_samples,
        issues=issues,
    )
    timings_by_id = {timing.event_id: timing for timing in timings}
    first_play_start_by_signal: dict[PlaySignal, Decimal] = {}
    for event in program.events:
        timing = timings_by_id.get(event.id)
        if (
            isinstance(event.instruction, Play)
            and timing is not None
            and timing.sample_count > 0
        ):
            first_play_start_by_signal.setdefault(
                event.instruction.signal,
                event.start_seconds,
            )
    render_events: list[SampledRenderEvent] = []
    frame_phases: dict[FrameSignal, float] = {}
    for event in program.events:
        timing = timings_by_id.get(event.id)

        instruction = event.instruction
        if isinstance(instruction, ShiftPhase):
            frame_phases[instruction.signal] = frame_phases.get(
                instruction.signal, 0.0
            ) + float(instruction.phase.value)
            continue
        if not isinstance(instruction, Play):
            continue
        binding = binding_by_signal.get(instruction.signal)
        if binding is None:
            issues.append(
                WaveformPlanningIssue(
                    code="sampled_output_signal_unbound",
                    message=(
                        f"event {event.id.value!r} output {instruction.signal!r} "
                        "has no sampled-output binding"
                    ),
                    event_id=event.id,
                )
            )
            continue
        if timing is None or timing.sample_count <= 0:
            continue
        if isinstance(instruction.envelope, CosineFlatTop):
            edge_duration_seconds = Decimal(
                str(instruction.envelope.rise_duration.to("s").value)
            ) + Decimal(str(instruction.envelope.fall_duration.to("s").value))
            if edge_duration_seconds > timing.realized_duration_seconds:
                issues.append(
                    WaveformPlanningIssue(
                        code="sampled_cosine_edges_exceed_realized_duration",
                        message=(
                            f"event {event.id.value!r} cosine-flat-top edges exceed "
                            "its realized duration"
                        ),
                        event_id=event.id,
                    )
                )
        frame_phase = (
            frame_phases.get(instruction.signal, 0.0)
            if isinstance(instruction.signal, DriveSignal | ReadoutSignal)
            else 0.0
        )
        carrier_phase_reference = binding.carrier_phase_reference
        if carrier_phase_reference == "schedule_origin":
            carrier_origin_seconds = Decimal(0)
        elif carrier_phase_reference == "signal_first_play":
            carrier_origin_seconds = first_play_start_by_signal[instruction.signal]
        else:
            carrier_origin_seconds = event.start_seconds
        render_events.append(
            SampledRenderEvent(
                event_id=event.id,
                envelope=instruction.envelope,
                timing=timing,
                binding=binding,
                effective_phase_radians=(
                    float(instruction.envelope.phase.value) + frame_phase
                ),
                carrier_origin_seconds=carrier_origin_seconds,
            )
        )

    if issues:
        raise WaveformPlanningError(tuple(issues))
    assert program_end_sample is not None
    lane_count = (
        max(
            (
                lane
                for event in render_events
                for lane in (event.binding.i_lane, event.binding.q_lane)
            ),
            default=-1,
        )
        + 1
    )
    return SampledWaveformPlan(
        program_id=program.id,
        semantics_id=_sampled_waveform_semantics_id(grid),
        grid=grid,
        sample_count=program_end_sample,
        lane_count=lane_count,
        event_timings=timings,
        render_events=tuple(render_events),
    )


def _realize_event_timings(
    events: tuple[ScheduledPulseEvent, ...],
    *,
    grid: SampleGrid,
    boundary_samples: dict[Decimal, int | None],
    issues: list[WaveformPlanningIssue],
) -> tuple[RealizedEventTiming, ...]:
    timings: list[RealizedEventTiming] = []
    for event in events:
        requested_end = event.start_seconds + event.duration_seconds
        start_sample = boundary_samples[event.start_seconds]
        end_sample = boundary_samples[requested_end]
        if start_sample is None:
            issues.append(
                WaveformPlanningIssue(
                    code="sampled_event_start_off_grid",
                    message=(
                        f"event {event.id.value!r} start is not on the strict "
                        "sample grid"
                    ),
                    event_id=event.id,
                )
            )
        if end_sample is None:
            issues.append(
                WaveformPlanningIssue(
                    code="sampled_event_end_off_grid",
                    message=(
                        f"event {event.id.value!r} end is not on the strict sample grid"
                    ),
                    event_id=event.id,
                )
            )
        if start_sample is None or end_sample is None:
            continue
        timing = RealizedEventTiming(
            event_id=event.id,
            requested_start_seconds=event.start_seconds,
            requested_duration_seconds=event.duration_seconds,
            sample_rate_hz=grid.sample_rate_hz,
            start_sample=start_sample,
            sample_count=end_sample - start_sample,
        )
        timings.append(timing)
        if event.duration_seconds > 0 and timing.sample_count <= 0:
            issues.append(
                WaveformPlanningIssue(
                    code="sampled_event_collapsed",
                    message=(f"event {event.id.value!r} collapses to zero samples"),
                    event_id=event.id,
                )
            )
    return tuple(timings)


@dataclass(frozen=True, slots=True)
class Float64ReferenceRenderer:
    """Readable authority for sampled-output numerical semantics."""

    def render(self, plan: SampledWaveformPlan) -> RenderedWaveforms:
        buffers = tuple(
            np.zeros(plan.sample_count, dtype=np.float64)
            for _ in range(plan.lane_count)
        )
        sample_rate_hz = plan.grid.sample_rate_hz
        sample_offset = 0.5 if plan.grid.sample_location == "midpoint" else 0.0
        for event in plan.render_events:
            timing = event.timing
            local_positions = (
                np.arange(timing.sample_count, dtype=np.float64) + sample_offset
            ) / sample_rate_hz
            absolute_positions = (
                timing.start_sample
                + np.arange(timing.sample_count, dtype=np.float64)
                + sample_offset
            ) / sample_rate_hz
            envelope = _envelope_samples(
                event.envelope,
                local_positions=local_positions,
                realized_duration_seconds=timing.sample_count / sample_rate_hz,
            )
            carrier_positions = absolute_positions - float(event.carrier_origin_seconds)
            carrier = np.exp(
                1j
                * (
                    event.effective_phase_radians
                    + math.tau
                    * event.binding.intermediate_frequency_hz
                    * carrier_positions
                )
            )
            samples = envelope * carrier
            mixer = event.binding.mixer
            physical_i = mixer.ii * samples.real + mixer.iq * samples.imag
            physical_q = mixer.qi * samples.real + mixer.qq * samples.imag
            selected = slice(timing.start_sample, timing.end_sample)
            buffers[event.binding.i_lane][selected] += physical_i
            buffers[event.binding.q_lane][selected] += physical_q

        lane_peaks = tuple(
            float(cast("np.float64", np.max(np.abs(buffer)))) if buffer.size else 0.0
            for buffer in buffers
        )
        for buffer in buffers:
            buffer.flags.writeable = False
        return RenderedWaveforms(
            semantics_id=plan.semantics_id,
            sample_rate_hz=sample_rate_hz,
            buffers=buffers,
            lane_peaks=lane_peaks,
        )


def _envelope_samples(
    envelope: AnalyticEnvelope,
    *,
    local_positions: np.ndarray[tuple[int], np.dtype[np.float64]],
    realized_duration_seconds: float,
) -> np.ndarray[tuple[int], np.dtype[np.complex128]]:
    amplitude = float(envelope.amplitude.value)
    if isinstance(envelope, Constant):
        return np.full(local_positions.shape, complex(amplitude), dtype=np.complex128)

    if isinstance(envelope, CosineFlatTop):
        samples = np.full(local_positions.shape, amplitude, dtype=np.float64)
        rise_seconds = float(envelope.rise_duration.value)
        if rise_seconds > 0:
            rising = local_positions < rise_seconds
            samples[rising] *= 0.5 * (
                1.0 - np.cos(math.pi * local_positions[rising] / rise_seconds)
            )
        fall_seconds = float(envelope.fall_duration.value)
        if fall_seconds > 0:
            fall_start = realized_duration_seconds - fall_seconds
            falling = local_positions >= fall_start
            samples[falling] *= 0.5 * (
                1.0
                + np.cos(
                    math.pi * (local_positions[falling] - fall_start) / fall_seconds
                )
            )
        return samples.astype(np.complex128)

    sigma_seconds = float(envelope.sigma.value)
    offsets = local_positions - realized_duration_seconds / 2.0
    gaussian = amplitude * np.exp(
        -(offsets * offsets) / (2.0 * sigma_seconds * sigma_seconds)
    )
    if isinstance(envelope, Gaussian):
        return gaussian.astype(np.complex128)

    assert isinstance(envelope, DRAG)
    beta_seconds = float(envelope.beta.value)
    derivative = -offsets * gaussian / (sigma_seconds * sigma_seconds)
    return gaussian + 1j * beta_seconds * derivative


def _sampled_waveform_semantics_id(
    grid: SampleGrid,
) -> SampledWaveformSemanticsId:
    if grid.sample_location == "midpoint":
        return MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID
    return LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID


def _quantize_boundary(seconds: Decimal, grid: SampleGrid) -> int | None:
    scaled = seconds * Decimal(grid.sample_rate_hz)
    integral = scaled.to_integral_value(rounding=ROUND_HALF_EVEN)
    if grid.timing.mode == "strict" and scaled != integral:
        return None
    return int(integral)


def _sample_seconds(sample: int, sample_rate_hz: int) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return Decimal(sample) / Decimal(sample_rate_hz)


def _issue_sort_key(issue: WaveformPlanningIssue) -> tuple[object, ...]:
    event = (
        (0, (), "")
        if issue.event_id is None
        else (1, issue.event_id.scope, issue.event_id.local_id)
    )
    return (event, issue.code, issue.message)


__all__ = [
    "LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID",
    "MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID",
    "SAMPLED_WAVEFORM_SEMANTICS_ID",
    "CarrierPhaseReference",
    "Float64ReferenceRenderer",
    "IqMatrix",
    "PhaseParameterizedSampledWaveforms",
    "RealizedEventTiming",
    "RenderedWaveforms",
    "SampleGrid",
    "SampleLocation",
    "SampledOutputBinding",
    "SampledRenderEvent",
    "SampledWaveformPlan",
    "SampledWaveformSemanticsId",
    "TimingQuantizationMode",
    "TimingQuantizationPolicy",
    "WaveformPlanningError",
    "WaveformPlanningIssue",
    "factor_phase_parameterized_waveforms",
    "plan_sampled_waveforms",
    "realize_event_timings",
]
