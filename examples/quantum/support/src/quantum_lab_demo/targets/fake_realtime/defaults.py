"""Small static configuration for the fake realtime target."""

from scopecat_quantum import (
    AcquireSignal,
    CouplerId,
    DriveSignal,
    FluxSignal,
    QubitId,
    ReadoutSignal,
    TargetId,
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
    """Return a four-lane target suitable for small feedback and QEC examples."""

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
    return FakeRealtimeTarget(
        id=TargetId("quantum-lab-demo.fake-realtime.v1"),
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


__all__ = ["default_fake_realtime_target"]
