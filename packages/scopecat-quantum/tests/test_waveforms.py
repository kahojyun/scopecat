from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pytest
from scopecat import Quantity

from scopecat_quantum._ids import PulseEventId, PulseProgramId, QubitId
from scopecat_quantum.pulses import (
    Constant,
    CosineFlatTop,
    Delay,
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
    LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID,
    MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID,
    CarrierPhaseReference,
    Float64ReferenceRenderer,
    IqMatrix,
    SampledOutputBinding,
    SampledWaveformPlan,
    SampleGrid,
    TimingQuantizationPolicy,
    WaveformPlanningError,
    factor_phase_parameterized_waveforms,
    plan_sampled_waveforms,
    realize_event_timings,
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


def test_timing_only_planner_preserves_requested_and_realized_boundaries() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("timing-only"),
            Sequence(
                (
                    Play(
                        PulseEventId("first"),
                        DRIVE_Q0,
                        Constant(Quantity(0.5, "ns"), Quantity(1, "arb")),
                    ),
                    Play(
                        PulseEventId("second"),
                        DRIVE_Q0,
                        Constant(Quantity(1.5, "ns"), Quantity(1, "arb")),
                    ),
                )
            ),
        )
    )

    timings = realize_event_timings(
        program.events,
        grid=SampleGrid(
            2_000_000_000,
            TimingQuantizationPolicy(mode="strict"),
        ),
    )

    assert tuple(timing.start_sample for timing in timings) == (0, 1)
    assert tuple(timing.sample_count for timing in timings) == (1, 3)
    assert all(timing.start_error_seconds == 0 for timing in timings)
    assert all(timing.duration_error_seconds == 0 for timing in timings)


def test_timing_only_planner_retains_nearest_grid_error() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("timing-nearest"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(2.4, "ns"), Quantity(1, "arb")),
            ),
        )
    )

    [timing] = realize_event_timings(
        program.events,
        grid=SampleGrid(1_000_000_000),
    )

    assert timing.sample_count == 2
    assert timing.requested_duration_seconds == Decimal("2.4e-9")
    assert timing.duration_error_seconds == Decimal("-4e-10")


def test_timing_only_planner_preserves_structured_strict_grid_errors() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("timing-strict"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(2.4, "ns"), Quantity(1, "arb")),
            ),
        )
    )

    with pytest.raises(WaveformPlanningError) as caught:
        realize_event_timings(
            program.events,
            grid=SampleGrid(
                1_000_000_000,
                TimingQuantizationPolicy(mode="strict"),
            ),
        )

    assert {issue.code for issue in caught.value.issues} == {
        "sampled_event_end_off_grid"
    }
    assert caught.value.issues[0].event_id == PulseEventId("play")


def test_timing_only_planner_rejects_nearest_grid_collapse() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("timing-collapsed"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(0.4, "ns"), Quantity(1, "arb")),
            ),
        )
    )

    with pytest.raises(WaveformPlanningError) as caught:
        realize_event_timings(
            program.events,
            grid=SampleGrid(1_000_000_000),
        )

    assert {issue.code for issue in caught.value.issues} == {"sampled_event_collapsed"}


def test_timing_only_planner_accepts_empty_and_zero_duration_events() -> None:
    grid = SampleGrid(1_000_000_000)
    assert realize_event_timings((), grid=grid) == ()
    program = schedule(
        PulseProgram(
            PulseProgramId("timing-zero-duration"),
            ShiftPhase(
                PulseEventId("shift"),
                DRIVE_Q0,
                Quantity(0.25, "rad"),
            ),
        )
    )

    [timing] = realize_event_timings(program.events, grid=grid)

    assert timing.start_sample == 0
    assert timing.sample_count == 0
    assert timing.duration_error_seconds == 0


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


def test_left_edge_cosine_flat_top_matches_legacy_periodic_hann() -> None:
    sample_count = 50
    amplitude = 0.3512
    program = schedule(
        PulseProgram(
            PulseProgramId("legacy-cosine"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                CosineFlatTop(
                    duration=Quantity(25, "ns"),
                    amplitude=Quantity(amplitude, "arb"),
                    rise_duration=Quantity(12.5, "ns"),
                    fall_duration=Quantity(12.5, "ns"),
                ),
            ),
        )
    )
    plan = plan_sampled_waveforms(
        program,
        bindings=(_binding(DRIVE_Q0),),
        grid=SampleGrid(2_000_000_000, sample_location="left_edge"),
    )

    rendered = Float64ReferenceRenderer().render(plan)
    expected = (
        amplitude
        * 0.5
        * (1.0 - np.cos(math.tau * np.arange(sample_count) / sample_count))
    )

    assert plan.semantics_id == LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID
    assert rendered.semantics_id == LEFT_EDGE_SAMPLED_WAVEFORM_SEMANTICS_ID
    np.testing.assert_allclose(rendered.buffers[0], expected, atol=1e-15)
    np.testing.assert_allclose(rendered.buffers[1], np.zeros(sample_count))


def test_left_edge_cosine_flat_top_preserves_legacy_readout_edges() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("legacy-readout"),
            Play(
                PulseEventId("play"),
                READOUT_Q0,
                CosineFlatTop(
                    duration=Quantity(200, "ns"),
                    amplitude=Quantity(1, "arb"),
                    rise_duration=Quantity(1, "ns"),
                    fall_duration=Quantity(1, "ns"),
                ),
            ),
        )
    )
    rendered = Float64ReferenceRenderer().render(
        plan_sampled_waveforms(
            program,
            bindings=(_binding(READOUT_Q0),),
            grid=SampleGrid(2_000_000_000, sample_location="left_edge"),
        )
    )

    assert rendered.buffers[0].size == 400
    np.testing.assert_allclose(rendered.buffers[0][:4], (0.0, 0.5, 1.0, 1.0))
    np.testing.assert_allclose(rendered.buffers[0][-4:], (1.0, 1.0, 1.0, 0.5))


def test_carrier_phase_reference_selects_schedule_signal_or_event_origin() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("carrier-origins"),
            Sequence(
                (
                    Delay(PulseEventId("initial"), DRIVE_Q0, Quantity(1, "ns")),
                    Play(
                        PulseEventId("first"),
                        DRIVE_Q0,
                        Constant(Quantity(2, "ns"), Quantity(1, "arb")),
                    ),
                    Delay(PulseEventId("gap"), DRIVE_Q0, Quantity(1, "ns")),
                    Play(
                        PulseEventId("second"),
                        DRIVE_Q0,
                        Constant(Quantity(2, "ns"), Quantity(1, "arb")),
                    ),
                )
            ),
        )
    )

    def render(
        reference: CarrierPhaseReference,
    ) -> tuple[np.ndarray, np.ndarray]:
        binding = SampledOutputBinding(
            signal=DRIVE_Q0,
            i_lane=0,
            q_lane=1,
            intermediate_frequency_hz=250_000_000,
            mixer=IDENTITY_IQ,
            carrier_phase_reference=reference,
        )
        rendered = Float64ReferenceRenderer().render(
            plan_sampled_waveforms(
                program,
                bindings=(binding,),
                grid=SampleGrid(1_000_000_000, sample_location="left_edge"),
            )
        )
        return rendered.buffers[0], rendered.buffers[1]

    schedule_i, schedule_q = render("schedule_origin")
    signal_i, signal_q = render("signal_first_play")
    event_i, event_q = render("event_origin")

    np.testing.assert_allclose(
        schedule_i[[1, 2, 4, 5]], (0.0, -1.0, 1.0, 0.0), atol=1e-15
    )
    np.testing.assert_allclose(
        schedule_q[[1, 2, 4, 5]], (1.0, 0.0, 0.0, 1.0), atol=1e-15
    )
    np.testing.assert_allclose(signal_i[[1, 2, 4, 5]], (1.0, 0.0, 0.0, 1.0), atol=1e-15)
    np.testing.assert_allclose(
        signal_q[[1, 2, 4, 5]], (0.0, 1.0, -1.0, 0.0), atol=1e-15
    )
    np.testing.assert_allclose(event_i[[1, 2, 4, 5]], (1.0, 0.0, 1.0, 0.0), atol=1e-15)
    np.testing.assert_allclose(event_q[[1, 2, 4, 5]], (0.0, 1.0, 0.0, 1.0), atol=1e-15)


def test_default_sample_location_retains_midpoint_semantics() -> None:
    plan = _phase_plan(0.0)

    assert plan.grid.sample_location == "midpoint"
    assert plan.semantics_id == MIDPOINT_SAMPLED_WAVEFORM_SEMANTICS_ID


def test_event_origin_is_the_continuous_boundary_not_the_first_sample() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("midpoint-event-origin"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                Constant(Quantity(2, "ns"), Quantity(1, "arb")),
            ),
        )
    )
    binding = SampledOutputBinding(
        signal=DRIVE_Q0,
        i_lane=0,
        q_lane=1,
        intermediate_frequency_hz=250_000_000,
        mixer=IDENTITY_IQ,
        carrier_phase_reference="event_origin",
    )

    rendered = Float64ReferenceRenderer().render(
        plan_sampled_waveforms(
            program,
            bindings=(binding,),
            grid=SampleGrid(1_000_000_000),
        )
    )

    half_sqrt_two = math.sqrt(0.5)
    np.testing.assert_allclose(
        rendered.buffers[0],
        (half_sqrt_two, -half_sqrt_two),
    )
    np.testing.assert_allclose(
        rendered.buffers[1],
        (half_sqrt_two, half_sqrt_two),
    )


def test_event_origin_preserves_a_subsample_continuous_start() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("subsample-event-origin"),
            Sequence(
                (
                    Delay(PulseEventId("initial"), DRIVE_Q0, Quantity(1.2, "ns")),
                    Play(
                        PulseEventId("play"),
                        DRIVE_Q0,
                        Constant(Quantity(2, "ns"), Quantity(1, "arb")),
                    ),
                )
            ),
        )
    )
    binding = SampledOutputBinding(
        signal=DRIVE_Q0,
        i_lane=0,
        q_lane=1,
        intermediate_frequency_hz=250_000_000,
        mixer=IDENTITY_IQ,
        carrier_phase_reference="event_origin",
    )

    plan = plan_sampled_waveforms(
        program,
        bindings=(binding,),
        grid=SampleGrid(1_000_000_000),
    )
    rendered = Float64ReferenceRenderer().render(plan)
    [event] = plan.render_events
    relative_positions = np.array((0.3e-9, 1.3e-9))
    phases = math.tau * binding.intermediate_frequency_hz * relative_positions

    assert event.timing.start_sample == 1
    assert event.carrier_origin_seconds == Decimal("1.2e-9")
    np.testing.assert_allclose(rendered.buffers[0][1:3], np.cos(phases))
    np.testing.assert_allclose(rendered.buffers[1][1:3], np.sin(phases))


def test_nearest_rejects_cosine_edges_longer_than_realized_duration() -> None:
    program = schedule(
        PulseProgram(
            PulseProgramId("collapsed-cosine-plateau"),
            Play(
                PulseEventId("play"),
                DRIVE_Q0,
                CosineFlatTop(
                    duration=Quantity(2.4, "ns"),
                    amplitude=Quantity(1, "arb"),
                    rise_duration=Quantity(1.2, "ns"),
                    fall_duration=Quantity(1.2, "ns"),
                ),
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
        "sampled_cosine_edges_exceed_realized_duration"
    }


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
