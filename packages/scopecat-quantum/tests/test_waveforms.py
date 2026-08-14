from __future__ import annotations

import math

import numpy as np
import pytest
from scopecat import Quantity

from scopecat_quantum._ids import PulseEventId, PulseProgramId, QubitId
from scopecat_quantum.pulses import (
    Constant,
    DriveSignal,
    Gaussian,
    Parallel,
    Play,
    PulseProgram,
    ReadoutSignal,
    Sequence,
    ShiftPhase,
    schedule,
)
from scopecat_quantum.waveforms import (
    Float64ReferenceRenderer,
    IqMatrix,
    SampledOutputBinding,
    SampledWaveformPlan,
    SampleGrid,
    TimingQuantizationPolicy,
    WaveformPlanningError,
    factor_phase_parameterized_waveforms,
    plan_sampled_waveforms,
)

Q0 = QubitId("q0")
Q1 = QubitId("q1")
DRIVE_Q0 = DriveSignal(Q0)
READOUT_Q0 = ReadoutSignal(Q0)
READOUT_Q1 = ReadoutSignal(Q1)
IDENTITY_IQ = IqMatrix(ii=1.0, iq=0.0, qi=0.0, qq=1.0)


def _binding(signal: DriveSignal | ReadoutSignal) -> SampledOutputBinding:
    return SampledOutputBinding(
        signal=signal,
        i_lane=0,
        q_lane=1,
        intermediate_frequency_hz=0.0,
        mixer=IDENTITY_IQ,
    )


def _phase_plan(phase: float, *, amplitude: float = 0.25) -> SampledWaveformPlan:
    return plan_sampled_waveforms(
        schedule(
            PulseProgram(
                PulseProgramId(f"phase-{phase}-{amplitude}"),
                Play(
                    PulseEventId("play"),
                    DRIVE_Q0,
                    Constant(
                        Quantity(4, "ns"),
                        Quantity(amplitude, "arb"),
                        phase=Quantity(phase, "rad"),
                    ),
                ),
            )
        ),
        bindings=(_binding(DRIVE_Q0),),
        grid=SampleGrid(1_000_000_000),
    )


def test_phase_parameterization_factors_only_phase_rows() -> None:
    plans = (_phase_plan(0.0), _phase_plan(math.pi / 2))

    factored = factor_phase_parameterized_waveforms(plans)

    assert factored is not None
    assert factored.phase_rows == ((0.0,), (math.pi / 2,))
    assert factored.template.render_events[0].effective_phase_radians == 0.0
    assert (
        factor_phase_parameterized_waveforms(
            (plans[0], _phase_plan(0.0, amplitude=0.5))
        )
        is None
    )


def test_nearest_quantizes_shared_absolute_boundaries_once() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("fractional-sequence"),
            Sequence(
                tuple(
                    Play(
                        PulseEventId(f"play-{index}"),
                        DRIVE_Q0,
                        Constant(Quantity(2.4, "ns"), Quantity(index + 1, "arb")),
                    )
                    for index in range(4)
                )
            ),
        )
    )

    plan = plan_sampled_waveforms(
        program,
        bindings=(_binding(DRIVE_Q0),),
        grid=SampleGrid(1_000_000_000),
    )

    assert plan.sample_count == 10
    assert tuple(timing.start_sample for timing in plan.event_timings) == (0, 2, 5, 7)
    assert tuple(timing.sample_count for timing in plan.event_timings) == (2, 3, 2, 3)
    assert tuple(timing.end_sample for timing in plan.event_timings) == (2, 5, 7, 10)


def test_strict_rejects_off_grid_boundaries() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("strict"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(2.4, "ns"), Quantity(1, "arb")),
            ),
        )
    )

    with pytest.raises(WaveformPlanningError) as caught:
        plan_sampled_waveforms(
            program,
            bindings=(_binding(DRIVE_Q0),),
            grid=SampleGrid(
                1_000_000_000,
                TimingQuantizationPolicy(mode="strict"),
            ),
        )

    assert {issue.code for issue in caught.value.issues} == {
        "sampled_event_end_off_grid",
        "sampled_program_duration_off_grid",
    }


def test_nearest_rejects_a_positive_event_that_collapses() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("collapsed"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(0.4, "ns"), Quantity(1, "arb")),
            ),
        )
    )

    with pytest.raises(WaveformPlanningError) as caught:
        plan_sampled_waveforms(
            program,
            bindings=(_binding(DRIVE_Q0),),
            grid=SampleGrid(1_000_000_000),
        )

    assert {issue.code for issue in caught.value.issues} == {
        "sampled_event_collapsed",
        "sampled_program_collapsed",
    }


def test_shift_phase_precedes_same_time_playback() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("phase"),
            Sequence(
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
    plan = plan_sampled_waveforms(
        program,
        bindings=(_binding(DRIVE_Q0),),
        grid=SampleGrid(1_000_000_000),
    )

    rendered = Float64ReferenceRenderer().render(plan)

    np.testing.assert_allclose(rendered.buffers[0], (0.0, 0.0), atol=1e-15)
    np.testing.assert_allclose(rendered.buffers[1], (0.25, 0.25))
    assert all(buffer.dtype == np.float64 for buffer in rendered.buffers)
    assert all(buffer.flags.c_contiguous for buffer in rendered.buffers)
    assert all(not buffer.flags.writeable for buffer in rendered.buffers)


def test_gaussian_uses_midpoints_over_the_realized_span() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("gaussian"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Gaussian(
                    duration=Quantity(4, "ns"),
                    amplitude=Quantity(0.2, "arb"),
                    sigma=Quantity(1, "ns"),
                ),
            ),
        )
    )
    rendered = Float64ReferenceRenderer().render(
        plan_sampled_waveforms(
            program,
            bindings=(_binding(DRIVE_Q0),),
            grid=SampleGrid(1_000_000_000),
        )
    )
    expected = tuple(
        0.2 * math.exp(-(offset * offset) / 2.0) for offset in (-1.5, -0.5, 0.5, 1.5)
    )

    np.testing.assert_allclose(rendered.buffers[0], expected)
    np.testing.assert_allclose(rendered.buffers[1], (0.0,) * 4)


def test_final_lane_peak_is_measured_after_additive_accumulation() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("multiplexed"),
            Parallel(
                (
                    Play(
                        PulseEventId("q0"),
                        READOUT_Q0,
                        Constant(Quantity(2, "ns"), Quantity(0.6, "arb")),
                    ),
                    Play(
                        PulseEventId("q1"),
                        READOUT_Q1,
                        Constant(Quantity(2, "ns"), Quantity(0.6, "arb")),
                    ),
                )
            ),
        )
    )
    plan = plan_sampled_waveforms(
        program,
        bindings=(_binding(READOUT_Q0), _binding(READOUT_Q1)),
        grid=SampleGrid(1_000_000_000),
    )

    rendered = Float64ReferenceRenderer().render(plan)

    np.testing.assert_allclose(rendered.buffers[0], (1.2, 1.2))
    assert rendered.lane_peaks == pytest.approx((1.2, 0.0))
