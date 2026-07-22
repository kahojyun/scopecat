"""Small static configuration for the fake realtime target."""

from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum import (
    AcquireSignal,
    CouplerId,
    DriveSignal,
    FluxSignal,
    QubitId,
    ReadoutSignal,
    TargetId,
)

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


def default_fake_realtime_target() -> FakeRealtimeTarget:
    """Return a four-lane target for bounded feedback and detector history."""

    qubits = tuple(QubitId(f"q{index}") for index in range(4))
    couplers = (CouplerId("coupler-q0-q1"), CouplerId("coupler-q2-q3"))
    drive_outputs = tuple(
        FakeRealtimeOutputId(f"drive-{qubit.value}") for qubit in qubits
    )
    readout_outputs = tuple(
        FakeRealtimeOutputId(f"readout-{qubit.value}") for qubit in qubits
    )
    flux_outputs = tuple(
        FakeRealtimeOutputId(f"flux-{coupler.value}") for coupler in couplers
    )
    outputs = (*drive_outputs, *readout_outputs, *flux_outputs)
    inputs = tuple(FakeRealtimeInputId(f"acquire-q{index}") for index in range(4))
    return _fake_realtime_target(
        target_id="quantum-lab-demo.fake-realtime.v1",
        outputs=outputs,
        inputs=inputs,
        output_bindings=tuple(
            FakeRealtimeOutputBinding(signal, output)
            for signal, output in (
                *zip(
                    (DriveSignal(qubit) for qubit in qubits),
                    drive_outputs,
                    strict=True,
                ),
                *zip(
                    (ReadoutSignal(qubit) for qubit in qubits),
                    readout_outputs,
                    strict=True,
                ),
                *zip(
                    (FluxSignal(coupler) for coupler in couplers),
                    flux_outputs,
                    strict=True,
                ),
            )
        ),
        input_bindings=tuple(
            FakeRealtimeInputBinding(AcquireSignal(qubit), input_id)
            for qubit, input_id in zip(qubits, inputs, strict=True)
        ),
        feedback_routes=tuple(
            FakeFeedbackRoute(source, destination, latency_ticks=12)
            for source, destination in zip(inputs, drive_outputs, strict=True)
        ),
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
        max_instructions=4096,
        max_waveforms=256,
        max_registers=64,
        max_result_records=65_536,
        max_loop_iterations=4096,
        classical_instruction_ticks=1,
        discrimination_latency_ticks=8,
        discriminator_ids=("binary-iq-threshold",),
        outputs=outputs,
        inputs=inputs,
        output_bindings=output_bindings,
        input_bindings=input_bindings,
        feedback_routes=feedback_routes,
    )


__all__ = ["configured_fake_realtime_target", "default_fake_realtime_target"]
