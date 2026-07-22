from __future__ import annotations

from dataclasses import replace

import pytest
from scopecat import Quantity
from scopecat_quantum import (
    AcquisitionKind,
    AcquisitionSlotId,
    Measure,
    MeasurementDiscriminator,
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    PulseImplementationId,
    PulseProgramId,
    RealtimeBitXor,
    ResolvedPulseImplementations,
    TargetAcquisitionLayout,
    TargetCompilationError,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetResultAxisLayout,
    compile_target,
    lower_quantum_program_to_structured_pulses,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.targets.fake_realtime import (
    FakeFeedbackRoute,
    FakeRealtimeCompiler,
    FakeRealtimeCompileRequest,
    FakeRealtimeProgram,
    FakeRealtimeRegister,
    FakeRealtimeRuntime,
    RtEmit,
    RtHalt,
    RtJump,
    RtJumpIf,
    RtLabel,
    RtPulseTimeline,
    RtScheduledAcquire,
    RtScheduledPlay,
    RtWait,
    RtXor,
    default_fake_realtime_target,
    prepare_fake_realtime_request,
)


def _compile(
    program: FakeRealtimeProgram,
    *,
    result_layouts: tuple[TargetAcquisitionLayout, ...] = (),
    repetitions: int = 1,
):
    target = default_fake_realtime_target()
    compiler = FakeRealtimeCompiler(TargetCompilerId("fake-rt.v1"), target)
    request = FakeRealtimeCompileRequest(
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        entry_id=TargetCompileEntryId("point-0"),
        program=program,
        result_layouts=result_layouts,
        repetitions=repetitions,
    )
    return target, compile_target(compiler, request)


def _measurement_implementation(
    measurement: Measure,
) -> MeasurementPulseImplementation:
    target = quantum.qubit(measurement.qubit.value)
    duration = Quantity(8, "ns")
    template = quantum.materialize_pulse_recipe_body(
        "test.readout.template",
        quantum.parallel(
            quantum.play(
                quantum.readout(target),
                quantum.constant(
                    duration=duration,
                    amplitude=Quantity(0.2, "arb"),
                ),
            ),
            quantum.acquire(
                target,
                duration=duration,
                result="template-result",
            ),
        ),
        measurement=(measurement.qubit, AcquisitionKind.INTEGRATED_IQ),
    )
    return MeasurementPulseImplementation(
        id=PulseImplementationId(f"test.readout[{measurement.qubit.value}]"),
        key=MeasurementPulseImplementationKey.from_measurement(measurement),
        pulse_template=template,
        discriminator=MeasurementDiscriminator(
            "binary-iq-threshold",
            AcquisitionKind.INTEGRATED_IQ,
        ),
    )


def test_active_reset_uses_runtime_measurement_without_recompilation() -> None:
    target = default_fake_realtime_target()
    measured = FakeRealtimeRegister("measured")
    program = FakeRealtimeProgram(
        id="active-reset",
        instructions=(
            RtPulseTimeline(
                duration_ticks=16,
                acquisitions=(
                    RtScheduledAcquire(
                        target.inputs[0],
                        "reset-bit",
                        measured,
                        start_ticks=0,
                        duration_ticks=16,
                    ),
                ),
            ),
            RtWait(target.discrimination_latency_ticks),
            RtJumpIf(measured, equals=1, target="correct"),
            RtJump("done"),
            RtLabel("correct"),
            RtPulseTimeline(
                duration_ticks=8,
                plays=(
                    RtScheduledPlay(
                        target.outputs[0],
                        "x180",
                        start_ticks=0,
                        duration_ticks=8,
                    ),
                ),
            ),
            RtLabel("done"),
            RtHalt(),
        ),
    )
    compiler = FakeRealtimeCompiler(
        TargetCompilerId("quantum-lab-demo.fake-realtime.compiler.v1"), target
    )
    request = FakeRealtimeCompileRequest(
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        entry_id=TargetCompileEntryId("point-0"),
        program=program,
        result_layouts=(
            TargetAcquisitionLayout(
                TargetCompileEntryId("point-0"), AcquisitionSlotId("reset-bit")
            ),
        ),
        repetitions=1,
    )
    artifact = compile_target(compiler, request)
    runtime = FakeRealtimeRuntime(target)

    ground = runtime.execute(artifact, {"reset-bit": (0,)})
    excited = runtime.execute(artifact, {"reset-bit": (1,)})

    assert ground.artifact is excited.artifact
    assert sum(event.operation == "pulsetimeline" for event in ground.events) == 1
    assert sum(event.operation == "pulsetimeline" for event in excited.events) == 2
    # The taken path replaces one classical Jump with an eight-tick timeline.
    assert excited.shot_end_ticks[0] - ground.shot_end_ticks[0] == 7


def test_authored_active_reset_lowers_to_one_bounded_realtime_artifact() -> None:
    q0 = quantum.qubit("q0")
    measured = quantum.measure(
        q0,
        result="reset-iq",
        bit="reset-bit",
    )
    declaration = quantum._close_program(
        "authored-active-reset",
        quantum.repeat(
            quantum.sequence(
                measured,
                quantum.when(
                    measured.bit,
                    quantum.play(
                        quantum.drive(q0),
                        quantum.constant(
                            duration=Quantity(8, "ns"),
                            amplitude=Quantity(0.2, "arb"),
                        ),
                    ),
                ),
            ),
            3,
            axis="round",
        ),
    )
    bound = quantum.bind(declaration)
    measurement = next(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, Measure)
    )
    implementation = _measurement_implementation(measurement)
    structured = lower_quantum_program_to_structured_pulses(
        bound.verified,
        ResolvedPulseImplementations(measurements=(implementation,)),
        output_id=PulseProgramId("authored-active-reset-pulses"),
    )
    default_target = default_fake_realtime_target()
    target = replace(
        default_target,
        feedback_routes=(
            *default_target.feedback_routes,
            FakeFeedbackRoute(
                default_target.inputs[0],
                default_target.outputs[1],
                latency_ticks=40,
            ),
        ),
    )
    compiler = FakeRealtimeCompiler(TargetCompilerId("fake-rt.v1"), target)
    entry_id = TargetCompileEntryId("point-0")
    request = prepare_fake_realtime_request(
        entry_id,
        structured,
        target=target,
        compiler_id=compiler.id,
        result_layouts=(
            TargetAcquisitionLayout(
                entry_id,
                AcquisitionSlotId("reset-iq"),
                (TargetResultAxisLayout("round", 3),),
            ),
        ),
        repetitions=1,
    )

    compiled = compile_target(compiler, request)
    run = FakeRealtimeRuntime(target).execute(
        compiled,
        {"reset-iq": (0, 1, 0)},
    )

    assert request.result_layouts[0].acquisition_addresses == (
        TargetAcquisitionLayout(
            entry_id,
            AcquisitionSlotId("reset-iq"),
            (TargetResultAxisLayout("round", 3),),
        ).acquisition_addresses
    )
    assert [record.value for record in run.records] == [0, 1, 0]
    assert sum(event.operation == "pulsetimeline" for event in run.events) == 4
    assert [
        instruction.duration_ticks
        for instruction in request.program.instructions
        if isinstance(instruction, RtWait)
    ] == [12]

    missing_route_target = replace(
        target,
        feedback_routes=tuple(
            route
            for route in target.feedback_routes
            if not (
                route.source == target.inputs[0]
                and route.destination == target.outputs[0]
            )
        ),
    )
    with pytest.raises(TargetCompilationError) as caught:
        prepare_fake_realtime_request(
            entry_id,
            structured,
            target=missing_route_target,
            compiler_id=compiler.id,
            result_layouts=request.result_layouts,
            repetitions=1,
        )
    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_feedback_route_missing"
    ]

    with pytest.raises(TargetCompilationError) as caught:
        prepare_fake_realtime_request(
            entry_id,
            structured,
            target=replace(target, discriminator_ids=()),
            compiler_id=compiler.id,
            result_layouts=request.result_layouts,
            repetitions=1,
        )
    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_discriminator_unsupported"
    ]


def test_repetition_rounds_emit_detector_history() -> None:
    target = default_fake_realtime_target()
    q0 = quantum.qubit("q0")
    previous_state = quantum.bit_state("previous-syndrome", initial=0)
    previous = quantum.read_bit(previous_state, id="previous")
    measurement = quantum.measure(
        q0,
        result="syndrome",
        bit="current",
    )
    detector = quantum.xor_bits(
        measurement.bit,
        previous.bit,
        id="detector",
    )
    declaration = quantum._close_program(
        "repetition-detectors",
        quantum.sequence(
            previous_state,
            quantum.repeat(
                quantum.sequence(
                    previous,
                    measurement,
                    detector,
                    quantum.emit_bit(detector.bit, result="detector"),
                    quantum.store_bit(previous_state, measurement.bit),
                ),
                3,
                axis="round",
            ),
        ),
    )
    bound = quantum.bind(declaration)
    measurement_ir = next(
        operation
        for operation in bound.verified.operations
        if isinstance(operation, Measure)
    )
    structured = lower_quantum_program_to_structured_pulses(
        bound.verified,
        ResolvedPulseImplementations(
            measurements=(_measurement_implementation(measurement_ir),)
        ),
        output_id=PulseProgramId("repetition-detector-pulses"),
    )
    assert [result.id for result in declaration.results] == ["syndrome", "detector"]
    assert [axis.id for axis in declaration.results.detector.contract.axes] == ["round"]
    [result_origin] = structured.realtime_result_provenance
    assert result_origin.result_id.local_id == "detector"
    assert result_origin.source_value_id == next(
        operation.output_id
        for operation in bound.verified.operations
        if isinstance(operation, RealtimeBitXor)
    )
    compiler = FakeRealtimeCompiler(TargetCompilerId("fake-rt.v1"), target)
    entry_id = TargetCompileEntryId("point-0")
    request = prepare_fake_realtime_request(
        entry_id,
        structured,
        target=target,
        compiler_id=compiler.id,
        result_layouts=(
            TargetAcquisitionLayout(
                entry_id,
                AcquisitionSlotId("syndrome"),
                (TargetResultAxisLayout("round", 3),),
            ),
            TargetAcquisitionLayout(
                entry_id,
                AcquisitionSlotId("detector"),
                (TargetResultAxisLayout("round", 3),),
            ),
        ),
        repetitions=1,
    )
    artifact = compile_target(compiler, request)

    assert artifact.artifact.realtime_result_provenance == (result_origin,)

    run = FakeRealtimeRuntime(target).execute(
        artifact,
        {"syndrome": (0, 1, 0)},
    )

    assert [
        record.value for record in run.records if record.result_id == "detector"
    ] == [
        0,
        1,
        1,
    ]
    assert sum(event.operation == "pulsetimeline" for event in run.events) == 3
    assert any(isinstance(item, RtXor) for item in request.program.instructions)
    assert any(isinstance(item, RtEmit) for item in request.program.instructions)


def test_compiler_rejects_feedback_read_before_ready_tick() -> None:
    target = default_fake_realtime_target()
    measured = FakeRealtimeRegister("measured")
    with pytest.raises(TargetCompilationError) as caught:
        _compile(
            FakeRealtimeProgram(
                id="missing-feedback-wait",
                instructions=(
                    RtPulseTimeline(
                        duration_ticks=4,
                        acquisitions=(
                            RtScheduledAcquire(
                                target.inputs[0],
                                "bit",
                                measured,
                                start_ticks=0,
                                duration_ticks=4,
                            ),
                        ),
                    ),
                    RtJumpIf(measured, equals=1, target="done"),
                    RtLabel("done"),
                    RtHalt(),
                ),
            ),
            result_layouts=(
                TargetAcquisitionLayout(
                    TargetCompileEntryId("point-0"), AcquisitionSlotId("bit")
                ),
            ),
        )

    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_feedback_read_too_early"
    ]


def test_compiler_rejects_register_use_without_a_definition() -> None:
    source = FakeRealtimeRegister("missing")

    with pytest.raises(TargetCompilationError) as caught:
        _compile(
            FakeRealtimeProgram(
                id="uninitialized-register",
                instructions=(
                    RtJumpIf(source, equals=1, target="done"),
                    RtLabel("done"),
                    RtHalt(),
                ),
            )
        )

    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_register_uninitialized"
    ]


def test_compiler_proves_machine_record_layout_coverage() -> None:
    target = default_fake_realtime_target()

    with pytest.raises(TargetCompilationError) as caught:
        _compile(
            FakeRealtimeProgram(
                id="missing-record-layout",
                instructions=(
                    RtPulseTimeline(
                        duration_ticks=4,
                        acquisitions=(
                            RtScheduledAcquire(
                                target.inputs[0],
                                "undeclared",
                                FakeRealtimeRegister("capture"),
                                start_ticks=0,
                                duration_ticks=4,
                            ),
                        ),
                    ),
                    RtHalt(),
                ),
            )
        )

    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_result_layout_missing"
    ]


def test_compiler_rejects_unbounded_machine_back_edges() -> None:
    with pytest.raises(TargetCompilationError) as caught:
        _compile(
            FakeRealtimeProgram(
                id="unbounded-loop",
                instructions=(RtLabel("loop"), RtJump("loop"), RtHalt()),
            )
        )

    assert {issue.code for issue in caught.value.issues} == {
        "fake_realtime_nonterminating_control_flow",
        "fake_realtime_unbounded_back_edge",
    }


def test_compiler_rejects_unknown_branch_label() -> None:
    with pytest.raises(TargetCompilationError) as caught:
        _compile(
            FakeRealtimeProgram(
                id="bad-jump",
                instructions=(RtJump("missing"), RtHalt()),
            )
        )

    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_unknown_jump_target"
    ]
