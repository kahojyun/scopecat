"""two-qubit gate modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_cz_chevron_program,
    build_parallel_gate_set_program,
    render_cz_coupler_waveforms,
    render_cz_drive_waveforms,
    render_parallel_gate_coupler_waveforms,
    render_parallel_gate_drive_waveforms,
)
from quantum_lab_demo.experiments.ids import (
    CZ_CHEVRON_TEMPLATE_ID,
    PARALLEL_GATE_SET_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.parameter_refs import (
    qubit_param,
    two_qubit_gate_param,
    two_qubit_gate_param_for,
)

CZ_CHEVRON_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.cz_chevron",
        metadata={"template_id": CZ_CHEVRON_TEMPLATE_ID},
    )
    .entity_inputs_from("control_qubit", "partner_qubit", "coupler")
    .input("coupler_duration", kind="quantity")
    .input("coupler_amplitude", kind="quantity")
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("control_qubit", "partner_qubit"),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("coupler",),
    )
    .compute(
        "build-cz-chevron-program",
        fn=build_cz_chevron_program,
        inputs={
            "control_qubit": sc.input("control_qubit"),
            "partner_qubit": sc.input("partner_qubit"),
            "coupler": sc.input("coupler"),
            "duration": sc.var("coupler_duration"),
            "amplitude": sc.var("coupler_amplitude"),
            "control_echo_amplitude": two_qubit_gate_param("control_echo_amplitude"),
            "partner_echo_amplitude": two_qubit_gate_param("partner_echo_amplitude"),
            "coupler_parking_flux": two_qubit_gate_param("coupler_parking_flux"),
            "sample_rate_hz": two_qubit_gate_param("sample_rate_hz"),
            "control_drive_frequency": qubit_param(
                "drive_frequency",
                input_id="control_qubit",
            ),
            "partner_drive_frequency": qubit_param(
                "drive_frequency",
                input_id="partner_qubit",
            ),
        },
    )
    .compute(
        "render-cz-chevron-drive-waveforms",
        fn=render_cz_drive_waveforms,
        inputs={
            "program": sc.compute_result("build-cz-chevron-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-cz-chevron-coupler-waveforms",
        fn=render_cz_coupler_waveforms,
        inputs={
            "program": sc.compute_result("build-cz-chevron-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind_compute(
        "drive.play_gate_sequence.sequence",
        "build-cz-chevron-program",
        kind="gate_sequence",
    )
    .bind_compute(
        "drive.play_pulse_program.program",
        "render-cz-chevron-drive-waveforms",
        kind="pulse_program",
    )
    .bind("drive.play_pulse_program.length", sc.var("coupler_duration"))
    .bind(
        "drive.play_pulse_program.amplitude",
        two_qubit_gate_param("control_echo_amplitude"),
    )
    .bind(
        "drive.play_pulse_program.frequency",
        qubit_param("drive_frequency", input_id="control_qubit"),
    )
    .bind_compute(
        "coupler.play_coupler_pulse.program",
        "render-cz-chevron-coupler-waveforms",
        kind="pulse_program",
    )
    .build()
)

PARALLEL_GATE_SET_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.parallel_gate_set",
        metadata={"template_id": PARALLEL_GATE_SET_TEMPLATE_ID},
    )
    .entity_inputs_from(
        "control_qubit_a",
        "partner_qubit_a",
        "coupler_a",
        "control_qubit_b",
        "partner_qubit_b",
        "coupler_b",
    )
    .input("qubits", kind="entity_array")
    .input("gate_duration", kind="quantity")
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(
            "control_qubit_a",
            "partner_qubit_a",
            "control_qubit_b",
            "partner_qubit_b",
        ),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("coupler_a", "coupler_b"),
    )
    .compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        inputs={
            "control_qubit_a": sc.input("control_qubit_a"),
            "partner_qubit_a": sc.input("partner_qubit_a"),
            "coupler_a": sc.input("coupler_a"),
            "control_qubit_b": sc.input("control_qubit_b"),
            "partner_qubit_b": sc.input("partner_qubit_b"),
            "coupler_b": sc.input("coupler_b"),
            "gate_duration": sc.var("gate_duration"),
            "coupler_amplitude_a": two_qubit_gate_param_for(
                "coupler_parking_flux",
                control_input_id="control_qubit_a",
                partner_input_id="partner_qubit_a",
            ),
            "coupler_amplitude_b": two_qubit_gate_param_for(
                "coupler_parking_flux",
                control_input_id="control_qubit_b",
                partner_input_id="partner_qubit_b",
            ),
            "control_frequency_a": qubit_param(
                "drive_frequency",
                input_id="control_qubit_a",
            ),
            "partner_frequency_a": qubit_param(
                "drive_frequency",
                input_id="partner_qubit_a",
            ),
            "control_frequency_b": qubit_param(
                "drive_frequency",
                input_id="control_qubit_b",
            ),
            "partner_frequency_b": qubit_param(
                "drive_frequency",
                input_id="partner_qubit_b",
            ),
        },
    )
    .compute(
        "render-parallel-gate-drive-waveforms",
        fn=render_parallel_gate_drive_waveforms,
        inputs={
            "program": sc.compute_result("build-parallel-gate-set-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-parallel-gate-coupler-waveforms",
        fn=render_parallel_gate_coupler_waveforms,
        inputs={
            "program": sc.compute_result("build-parallel-gate-set-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind_compute(
        "drive.play_gate_sequence.sequence",
        "build-parallel-gate-set-program",
        kind="gate_sequence",
    )
    .bind_compute(
        "drive.play_pulse_program.program",
        "render-parallel-gate-drive-waveforms",
        kind="pulse_program",
    )
    .bind_compute(
        "coupler.play_coupler_pulse.program",
        "render-parallel-gate-coupler-waveforms",
        kind="pulse_program",
    )
    .build()
)

__all__ = [
    "CZ_CHEVRON_MODULE",
    "PARALLEL_GATE_SET_MODULE",
]
