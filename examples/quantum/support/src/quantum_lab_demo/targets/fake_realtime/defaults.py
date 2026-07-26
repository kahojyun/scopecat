"""Small static configuration for the fake realtime target."""

from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum._ids import TargetId
from scopecat_quantum.pulses import DriveSignal

from quantum_lab_demo.targets.configuration import (
    FAKE_REALTIME_TARGET_KIND,
    configured_acquisition_signal,
    configured_output_signal,
    configured_quantum_routes,
)
from quantum_lab_demo.targets.fake_realtime.model import (
    FakeFeedbackRoute,
    FakeRealtimeInputBinding,
    FakeRealtimeInputId,
    FakeRealtimeOutputBinding,
    FakeRealtimeOutputId,
    FakeRealtimeTarget,
)


def configured_fake_realtime_target(
    config: ConfigProfileSnapshot,
) -> FakeRealtimeTarget:
    """Build realtime lanes and feedback routes from accepted static routing."""

    target_id, routes = configured_quantum_routes(
        config,
        target_kind=FAKE_REALTIME_TARGET_KIND,
    )
    output_bindings = tuple(
        FakeRealtimeOutputBinding(signal, FakeRealtimeOutputId(route.endpoint_id))
        for route in routes
        if (signal := configured_output_signal(route)) is not None
    )
    input_bindings = tuple(
        FakeRealtimeInputBinding(signal, FakeRealtimeInputId(route.endpoint_id))
        for route in routes
        if (signal := configured_acquisition_signal(route)) is not None
    )
    drive_by_qubit = {
        binding.signal.qubit: binding.output
        for binding in output_bindings
        if isinstance(binding.signal, DriveSignal)
    }
    feedback_routes = tuple(
        FakeFeedbackRoute(
            binding.input,
            drive_by_qubit[binding.signal.qubit],
            latency_ticks=12,
        )
        for binding in input_bindings
        if binding.signal.qubit in drive_by_qubit
    )
    return _fake_realtime_target(
        target_id=target_id,
        outputs=tuple(dict.fromkeys(binding.output for binding in output_bindings)),
        inputs=tuple(dict.fromkeys(binding.input for binding in input_bindings)),
        output_bindings=output_bindings,
        input_bindings=input_bindings,
        feedback_routes=feedback_routes,
    )


def _fake_realtime_target(
    *,
    target_id: str,
    outputs: tuple[FakeRealtimeOutputId, ...],
    inputs: tuple[FakeRealtimeInputId, ...],
    output_bindings: tuple[FakeRealtimeOutputBinding, ...],
    input_bindings: tuple[FakeRealtimeInputBinding, ...],
    feedback_routes: tuple[FakeFeedbackRoute, ...],
) -> FakeRealtimeTarget:
    return FakeRealtimeTarget(
        id=TargetId(target_id),
        clock_hz=250_000_000,
        max_result_records=65_536,
        max_loop_iterations=4096,
        decision_latency_ticks=1,
        discrimination_latency_ticks=8,
        discriminator_ids=("binary-iq-threshold",),
        outputs=outputs,
        inputs=inputs,
        output_bindings=output_bindings,
        input_bindings=input_bindings,
        feedback_routes=feedback_routes,
    )


__all__ = ["configured_fake_realtime_target"]
