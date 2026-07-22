"""Default laboratory configuration for the fake list-mode target."""

from __future__ import annotations

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
    FAKE_LIST_TARGET_KIND,
    configured_acquisition_signal,
    configured_output_signal,
    configured_quantum_routes,
)
from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionBinding,
    FakeAwgChannelId,
    FakeDigitizerChannelId,
    FakeListTarget,
    FakeOutputBinding,
)


def default_fake_list_target() -> FakeListTarget:
    """Return the demo lab's explicit four-qubit fake hardware target."""

    qubits = tuple(QubitId(f"q{index}") for index in range(4))
    output_bindings = (
        *(
            binding
            for index, qubit in enumerate(qubits)
            for binding in (
                FakeOutputBinding(
                    DriveSignal(qubit),
                    FakeAwgChannelId(f"awg.drive.{index}"),
                ),
                FakeOutputBinding(
                    ReadoutSignal(qubit),
                    FakeAwgChannelId(f"awg.readout.{index}"),
                ),
            )
        ),
        FakeOutputBinding(
            FluxSignal(CouplerId("coupler-q0-q1")),
            FakeAwgChannelId("awg.flux.0"),
        ),
        FakeOutputBinding(
            FluxSignal(CouplerId("coupler-q2-q3")),
            FakeAwgChannelId("awg.flux.1"),
        ),
    )
    acquisition_bindings = tuple(
        FakeAcquisitionBinding(
            AcquireSignal(qubit),
            FakeDigitizerChannelId(f"digitizer.readout.{index}"),
        )
        for index, qubit in enumerate(qubits)
    )
    return _fake_list_target(
        target_id="quantum-lab-demo.fake-list-mode.v1",
        output_bindings=output_bindings,
        acquisition_bindings=acquisition_bindings,
    )


def configured_fake_list_target(config: ConfigProfileSnapshot) -> FakeListTarget:
    """Build list-mode physical bindings from one accepted system snapshot."""

    target_id, routes = configured_quantum_routes(
        config,
        target_kind=FAKE_LIST_TARGET_KIND,
    )
    output_bindings = tuple(
        FakeOutputBinding(signal, FakeAwgChannelId(route.endpoint_id))
        for route in routes
        if (signal := configured_output_signal(route)) is not None
    )
    acquisition_bindings = tuple(
        FakeAcquisitionBinding(
            signal,
            FakeDigitizerChannelId(route.endpoint_id),
        )
        for route in routes
        if (signal := configured_acquisition_signal(route)) is not None
    )
    return _fake_list_target(
        target_id=target_id,
        output_bindings=output_bindings,
        acquisition_bindings=acquisition_bindings,
    )


def _fake_list_target(
    *,
    target_id: str,
    output_bindings: tuple[FakeOutputBinding, ...],
    acquisition_bindings: tuple[FakeAcquisitionBinding, ...],
) -> FakeListTarget:
    return FakeListTarget(
        id=TargetId(target_id),
        sample_rate_hz=1_000_000_000,
        max_list_entries=256,
        max_samples_per_entry=1_000_000,
        max_waveform_memory_samples=64_000_000,
        max_capture_memory_samples=64_000_000,
        max_repetitions=100_000,
        max_frames=1_000_000,
        max_abs_amplitude=1.0,
        output_bindings=output_bindings,
        acquisition_bindings=acquisition_bindings,
    )


__all__ = ["configured_fake_list_target", "default_fake_list_target"]
