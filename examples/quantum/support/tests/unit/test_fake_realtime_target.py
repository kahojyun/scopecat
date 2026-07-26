from __future__ import annotations

from dataclasses import replace

import pytest
from scopecat import Quantity
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseImplementationId,
    PulseProgramId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.measurement_implementations import MeasurementDiscriminator
from scopecat_quantum.programs import (
    StructuredPulseRepeat,
    lower_quantum_program_to_structured_pulses,
)
from scopecat_quantum.pulse_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    ResolvedPulseImplementations,
)
from scopecat_quantum.targets import (
    TargetAcquisitionLayout,
    TargetCompilationError,
    TargetResultAxisLayout,
    compile_target,
)

from quantum_lab_demo.targets.fake_realtime.compiler import FakeRealtimeCompiler
from quantum_lab_demo.targets.fake_realtime.defaults import (
    configured_fake_realtime_target,
)
from quantum_lab_demo.targets.fake_realtime.model import (
    FakeRealtimeTarget,
)
from quantum_lab_demo.targets.fake_realtime.runtime import FakeRealtimeRuntime
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile


def _configured_target() -> FakeRealtimeTarget:
    return configured_fake_realtime_target(
        quantum_wiring_config_profile(target="fake-realtime")
    )


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


def _active_reset_program():
    q0 = quantum.qubit("q0")
    measured = quantum.measure(q0, result="reset-iq", bit="reset-bit")
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
    return lower_quantum_program_to_structured_pulses(
        bound.verified,
        ResolvedPulseImplementations(
            measurements=(_measurement_implementation(measurement),)
        ),
        output_id=PulseProgramId("authored-active-reset-pulses"),
    )


def _compiler_and_request(
    target: FakeRealtimeTarget,
):
    compiler = FakeRealtimeCompiler(TargetCompilerId("fake-rt.v2"), target)
    entry_id = TargetCompileEntryId("point-0")
    request = compiler.request(
        entry_id,
        _active_reset_program(),
        result_layouts=(
            TargetAcquisitionLayout(
                entry_id,
                AcquisitionSlotId("reset-iq"),
                (TargetResultAxisLayout("round", 3),),
            ),
        ),
        repetitions=1,
    )
    return compiler, request


def test_active_reset_executes_the_structured_artifact_without_recompilation() -> None:
    target = _configured_target()
    compiler, request = _compiler_and_request(target)
    compiled = compile_target(compiler, request)
    runtime = FakeRealtimeRuntime(target)

    ground = runtime.execute(compiled, {"reset-iq": (0, 0, 0)})
    mixed = runtime.execute(compiled, {"reset-iq": (0, 1, 0)})

    assert compiled.artifact.program is request.program
    assert isinstance(compiled.artifact.program.body, StructuredPulseRepeat)
    assert [record.value for record in mixed.records] == [0, 1, 0]
    assert sum(event.operation == "conditional" for event in mixed.events) == 3
    assert sum(event.operation == "pulse" for event in ground.events) == 3
    assert sum(event.operation == "pulse" for event in mixed.events) == 4
    assert mixed.shot_end_ticks[0] > ground.shot_end_ticks[0]
    first_condition = next(
        event for event in mixed.events if event.operation == "conditional"
    )
    assert first_condition.tick - mixed.records[0].tick == 12


def test_compiler_checks_feedback_routes_and_discriminators() -> None:
    target = _configured_target()
    removed_route = target.feedback_routes[0]
    missing_route = replace(
        target,
        feedback_routes=tuple(
            route for route in target.feedback_routes if route != removed_route
        ),
    )
    compiler, request = _compiler_and_request(missing_route)
    with pytest.raises(TargetCompilationError) as caught:
        compile_target(compiler, request)
    assert "fake_realtime_feedback_route_missing" in {
        issue.code for issue in caught.value.issues
    }

    unsupported = replace(target, discriminator_ids=())
    compiler, request = _compiler_and_request(unsupported)
    with pytest.raises(TargetCompilationError) as caught:
        compile_target(compiler, request)
    assert "fake_realtime_discriminator_unsupported" in {
        issue.code for issue in caught.value.issues
    }


def test_compiler_checks_clock_alignment_and_result_layout() -> None:
    target = replace(_configured_target(), clock_hz=300_000_000)
    compiler, request = _compiler_and_request(target)
    with pytest.raises(TargetCompilationError) as caught:
        compile_target(compiler, request)
    assert "fake_realtime_timing_not_on_clock" in {
        issue.code for issue in caught.value.issues
    }

    target = _configured_target()
    compiler = FakeRealtimeCompiler(TargetCompilerId("fake-rt.v2"), target)
    request = compiler.request(
        TargetCompileEntryId("point-0"),
        _active_reset_program(),
        result_layouts=(),
        repetitions=1,
    )
    with pytest.raises(TargetCompilationError) as caught:
        compile_target(compiler, request)
    assert [issue.code for issue in caught.value.issues] == [
        "fake_realtime_result_layout_mismatch"
    ]
