"""surface-code style modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_surface_code_round_program,
    render_surface_code_coupler_waveforms,
    render_surface_code_drive_waveforms,
)
from quantum_lab_demo.experiments.ids import TOY_SURFACE_CODE_ROUND_TEMPLATE_ID

TOY_SURFACE_CODE_ROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.surface_code.toy_round",
        metadata={"template_id": TOY_SURFACE_CODE_ROUND_TEMPLATE_ID},
    )
    .input("patch_qubits", kind="entity_array")
    .input("data_qubits", kind="entity_array")
    .input("ancilla_qubits", kind="entity_array")
    .input("couplers", kind="entity_array")
    .input("rounds", kind="count")
    .input("cycle_time", kind="quantity")
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("patch_qubits",),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("couplers",),
    )
    .resource(
        "readout",
        requires=("acquire_iq",),
        for_entities=("patch_qubits",),
    )
    .compute(
        "build-surface-code-round-program",
        fn=build_surface_code_round_program,
        inputs={
            "patch_qubits": sc.input("patch_qubits"),
            "data_qubits": sc.input("data_qubits"),
            "ancilla_qubits": sc.input("ancilla_qubits"),
            "couplers": sc.input("couplers"),
            "rounds": sc.input("rounds"),
            "cycle_time": sc.input("cycle_time"),
        },
    )
    .compute(
        "render-surface-code-drive-waveforms",
        fn=render_surface_code_drive_waveforms,
        inputs={
            "program": sc.compute_result("build-surface-code-round-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-surface-code-coupler-waveforms",
        fn=render_surface_code_coupler_waveforms,
        inputs={
            "program": sc.compute_result("build-surface-code-round-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind_compute(
        "drive.play_gate_sequence.sequence",
        "build-surface-code-round-program",
        kind="gate_sequence",
    )
    .bind_compute(
        "drive.play_pulse_program.program",
        "render-surface-code-drive-waveforms",
        kind="pulse_program",
    )
    .bind_compute(
        "coupler.play_coupler_pulse.program",
        "render-surface-code-coupler-waveforms",
        kind="pulse_program",
    )
    .bind("readout.acquire_iq.repetitions", sc.input("rounds"))
    .build()
)

__all__ = [
    "TOY_SURFACE_CODE_ROUND_MODULE",
]
